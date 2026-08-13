"""Tray/webview wrapper around the existing in-process aiohttp bridge.

The module itself is safe to import without pystray, pywebview, or Pillow. Those
packages are loaded only by :func:`run_tray_app`; smoke mode uses none of them.
"""

from __future__ import annotations

import asyncio
import errno
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from contextlib import suppress
from typing import Any

from aiohttp import web

from server import main as server_main


SERVER_DEFAULT_PORT = server_main.PORT
START_TIMEOUT_SECONDS = 15.0
STOP_TIMEOUT_SECONDS = 2.0
RUNNER_SHUTDOWN_SECONDS = 3.0
SMOKE_HTTP_TIMEOUT_SECONDS = 5.0
FAMILY_COLOR = "#D97757"


class AppError(RuntimeError):
    """Expected application error that should be reported without a traceback."""


def _actual_site_port(site: web.TCPSite) -> int:
    """Read the port from the already-bound socket (important when port is zero)."""
    aiohttp_server = getattr(site, "_server", None)
    sockets = getattr(aiohttp_server, "sockets", None)
    if not sockets:
        raise RuntimeError("aiohttp did not expose a bound listening socket")
    return int(sockets[0].getsockname()[1])


def _deny_pending_requests() -> None:
    """Fail closed so graceful shutdown is not held by long approval requests."""
    for request in list(server_main.bridge.pending.values()):
        future = request.get("future")
        if isinstance(future, asyncio.Future) and not future.done():
            future.set_result("deny")


def _friendly_start_error(error: BaseException, port: int) -> str:
    address = f"{server_main.HOST}:{port}"
    if isinstance(error, OSError):
        message = str(error).lower()
        if error.errno == errno.EADDRINUSE or "address already in use" in message:
            return (
                f"cannot start bridge on {address}: the port is already in use; "
                "stop the other bridge or choose --port/CLAUDEMICRO_PORT"
            )
        if error.errno in (errno.EACCES, errno.EPERM):
            return f"cannot bind bridge to {address}: permission denied"
    return f"cannot start bridge on {address}: {error}"


class EmbeddedBridge:
    """Own one aiohttp bridge lifetime on a dedicated asyncio-loop thread."""

    def __init__(
        self,
        requested_port: int,
        *,
        report_thread_errors: bool = True,
    ):
        self.requested_port = requested_port
        self._report_thread_errors = report_thread_errors
        self.port: int | None = None
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._state_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._thread_main,
            name="ClaudeMicro-bridge",
            daemon=True,
        )

    def start(self) -> int:
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT_SECONDS):
            self.request_stop()
            self._thread.join(STOP_TIMEOUT_SECONDS)
            raise AppError("timed out while starting the embedded bridge")
        if self._error is not None:
            self._thread.join(STOP_TIMEOUT_SECONDS)
            raise AppError(_friendly_start_error(self._error, self.requested_port))
        if self.port is None:
            raise AppError("embedded bridge reported ready without a listening port")
        return self.port

    def request_stop(self) -> None:
        """Signal shutdown without blocking a GUI callback."""
        # Latch the request so a stop racing with loop startup is not lost.
        self._stop_requested.set()
        with self._state_lock:
            loop = self._loop
            stop_event = self._stop_event
        if loop is None or stop_event is None or loop.is_closed():
            return

        def deny_pending_and_stop() -> None:
            # Run Future resolution on the bridge loop. This fail-closes pending
            # decisions even if _serve() never reaches its cleanup block.
            try:
                _deny_pending_requests()
            finally:
                stop_event.set()

        with suppress(RuntimeError):
            loop.call_soon_threadsafe(deny_pending_and_stop)

    def stop(self) -> None:
        """Request graceful cleanup and wait for the owning loop to finish."""
        if not self._thread.is_alive():
            if self._error is not None and self.port is not None:
                raise AppError(f"embedded bridge stopped unexpectedly: {self._error}")
            return
        self.request_stop()
        self._thread.join(STOP_TIMEOUT_SECONDS)
        if self._thread.is_alive():
            print(
                "ClaudeMicro: bridge 停止待ちを打ち切りました(プロセス終了で回収)",
                file=sys.stderr,
            )
            return
        if self._error is not None and self.port is not None:
            raise AppError(f"embedded bridge shutdown failed: {self._error}")

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:  # propagate to the main thread without a thread traceback
            self._error = exc
            if self.port is not None and self._report_thread_errors:
                print(
                    f"ClaudeMicro: 内蔵 bridge が異常終了しました: {exc}",
                    file=sys.stderr,
                )
        finally:
            self._ready.set()

    async def _serve(self) -> None:
        runner: web.AppRunner | None = None
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        with self._state_lock:
            self._loop = loop
            self._stop_event = stop_event
        if self._stop_requested.is_set():
            stop_event.set()
        try:
            runner = web.AppRunner(
                server_main.create_app(),
                shutdown_timeout=RUNNER_SHUTDOWN_SECONDS,
            )
            await runner.setup()
            site = web.TCPSite(
                runner,
                host=server_main.HOST,
                port=self.requested_port,
            )
            await site.start()
            self.port = _actual_site_port(site)
            self._ready.set()
            await stop_event.wait()
        finally:
            # Pending /decision handlers can otherwise hold shutdown until their
            # normal approval timeout. Resolve them before AppRunner cleanup.
            try:
                try:
                    _deny_pending_requests()
                finally:
                    if runner is not None:
                        # Issue cancellation (including any in-flight osascript)
                        # before entering aiohttp's one bounded cleanup phase.
                        server_main.cancel_background_tasks(runner.app)
                        with suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(
                                runner.cleanup(),
                                RUNNER_SHUTDOWN_SECONDS + 1,
                            )
            finally:
                try:
                    # server.main deliberately owns core behavior only; the desktop
                    # process is the final owner and stops its HID reader on exit.
                    server_main.bridge.adapter.stop()
                finally:
                    server_main.bridge.loop = None
                    with self._state_lock:
                        self._stop_event = None
                        self._loop = None


def _console_url(port: int) -> str:
    base = f"http://{server_main.HOST}:{port}/"
    if not server_main.TOKEN:
        return base
    return f"{base}?{urllib.parse.urlencode({'token': server_main.TOKEN})}"


def run_smoke() -> None:
    """Start on port 0, make one real HTTP request, and shut down cleanly."""
    os.environ.setdefault("CLAUDEMICRO_NO_DEVICE", "1")
    bridge = EmbeddedBridge(0, report_thread_errors=False)
    primary_error: BaseException | None = None
    url = ""
    status = 0
    try:
        port = bridge.start()
        url = f"http://{server_main.HOST}:{port}/"
        # Explicitly disable proxies so a local health check never leaves the host.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(url, timeout=SMOKE_HTTP_TIMEOUT_SECONDS) as response:
                status = response.status
                body = response.read()
        except (OSError, urllib.error.URLError) as exc:
            raise AppError(f"smoke HTTP check failed for {url}: {exc}") from exc
        if status != 200:
            raise AppError(f"smoke HTTP check returned status {status} for {url}")
        if not body:
            raise AppError(f"smoke HTTP check returned an empty response for {url}")
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            bridge.stop()
        except AppError:
            if primary_error is None:
                raise
    print(f"Smoke test passed: {url} returned HTTP {status}")


def _load_gui_dependencies() -> tuple[Any, Any, Any, Any]:
    """Import optional GUI packages only for a real tray launch."""
    try:
        import pystray
        import webview
        from PIL import Image, ImageDraw
    except ImportError as exc:
        package = exc.name or "a GUI package"
        install_hint = (
            r".venv\Scripts\python.exe -m pip install -r requirements-app.txt"
            if sys.platform == "win32"
            else ".venv/bin/pip install -r requirements-app.txt"
        )
        raise AppError(
            f"missing GUI dependency {package!r}; "
            f"install with '{install_hint}'"
        ) from exc
    return pystray, webview, Image, ImageDraw


class _TrayController:
    """Coordinate click-driven tray actions and the single console window."""

    def __init__(
        self,
        *,
        bridge: EmbeddedBridge,
        url: str,
        pystray: Any,
        webview: Any,
        image_module: Any,
        draw_module: Any,
    ):
        self.bridge = bridge
        self.url = url
        self.pystray = pystray
        self.webview = webview
        self.image_module = image_module
        self.draw_module = draw_module
        self._lock = threading.RLock()
        self._quitting = False
        self._window: Any | None = None
        self._icon: Any | None = None

    def create_window(self) -> None:
        window = self.webview.create_window(
            "ClaudeMicro Console",
            self.url,
            width=1080,
            height=760,
            min_size=(720, 520),
        )
        window.events.closing += self._on_window_closing
        window.events.closed += self._on_window_closed
        with self._lock:
            self._window = window

    def create_icon(self) -> None:
        image = self.image_module.new("RGBA", (64, 64), (0, 0, 0, 0))
        drawing = self.draw_module.Draw(image)
        drawing.ellipse((8, 8, 56, 56), fill=FAMILY_COLOR)
        menu = self.pystray.Menu(
            self.pystray.MenuItem(
                "コンソールを開く",
                self.open_console,
                default=True,
            ),
            self.pystray.MenuItem("ブラウザで開く", self.open_browser),
            self.pystray.Menu.SEPARATOR,
            self.pystray.MenuItem("終了", self.quit),
        )
        with self._lock:
            self._icon = self.pystray.Icon(
                "ClaudeMicro",
                image,
                "ClaudeMicro",
                menu,
            )

    def open_console(self, _icon: Any = None, _item: Any = None) -> None:
        with self._lock:
            if self._quitting:
                return
            window = self._window
        if window is None:
            # Ordinary closes are vetoed and hidden below. If the backend truly
            # destroyed its last window, Cocoa has also ended the shared GUI loop,
            # so attempting to create one from this AppKit callback is not safe.
            print("ClaudeMicro: the console window is no longer available", file=sys.stderr)
            return
        try:
            window.show()
            with suppress(Exception):
                window.restore()
        except Exception as exc:
            print(f"ClaudeMicro: could not show console: {exc}", file=sys.stderr)

    def open_browser(self, _icon: Any = None, _item: Any = None) -> None:
        if not webbrowser.open(self.url):
            print("ClaudeMicro: the default browser did not accept the console URL", file=sys.stderr)

    def quit(self, _icon: Any = None, _item: Any = None) -> None:
        """Non-blocking callback; main-thread cleanup happens after GUI exit."""
        with self._lock:
            if self._quitting:
                return
            self._quitting = True
            icon = self._icon
            window = self._window
        self.bridge.request_stop()
        if window is not None:
            try:
                window.destroy()
                return
            except Exception as exc:
                print(f"ClaudeMicro: could not close console: {exc}", file=sys.stderr)
        # On macOS pystray and pywebview share NSApplication. Let destroying the
        # final webview end that loop first; stop pystray directly only as fallback.
        if icon is not None:
            with suppress(Exception):
                icon.stop()

    def _on_window_closing(self) -> bool:
        with self._lock:
            if self._quitting:
                return True
            window = self._window
        # Returning False cancels destruction. Hiding preserves the only pywebview
        # window (and therefore its main loop) while the tray keeps the app resident.
        if window is not None:
            with suppress(Exception):
                window.hide()
        return False

    def _on_window_closed(self) -> None:
        with self._lock:
            self._window = None

    def stop_ui(self) -> None:
        with self._lock:
            self._quitting = True
            icon = self._icon
            window = self._window
        if window is not None:
            with suppress(Exception):
                window.destroy()
        if icon is not None:
            with suppress(Exception):
                icon.visible = False
            with suppress(Exception):
                icon.stop()


def run_tray_app(requested_port: int) -> None:
    """Start the embedded bridge, tray icon, and console webview."""
    if threading.current_thread() is not threading.main_thread():
        raise AppError("the tray application must be started on the main thread")

    pystray, webview, image_module, draw_module = _load_gui_dependencies()
    bridge = EmbeddedBridge(requested_port)
    controller: _TrayController | None = None
    primary_error: BaseException | None = None
    try:
        port = bridge.start()
        url = _console_url(port)
        controller = _TrayController(
            bridge=bridge,
            url=url,
            pystray=pystray,
            webview=webview,
            image_module=image_module,
            draw_module=draw_module,
        )
        controller.create_window()
        controller.create_icon()

        # Both Cocoa backends normally want the process main thread. pywebview owns
        # that thread; pystray's documented detached mode attaches its native icon
        # to the same macOS application run loop instead of starting a competing one.
        controller._icon.run_detached()
        print(f"ClaudeMicro console: {url}")
        webview.start(debug=False)
    except BaseException as exc:
        primary_error = exc
        if isinstance(exc, (AppError, KeyboardInterrupt)):
            raise
        raise AppError(f"GUI failed: {exc}") from exc
    finally:
        if controller is not None:
            controller.stop_ui()
        try:
            bridge.stop()
        except AppError:
            if primary_error is None:
                raise
