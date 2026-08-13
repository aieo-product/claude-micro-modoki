"""Windows compatibility guards that can be exercised without hardware."""

import asyncio
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import codex_hook_client
import hook_client
from server import config as config_mod

# Avoid loading a developer-specific config while server.main creates its global Bridge.
with mock.patch.object(
        config_mod, "load",
        return_value=config_mod._deep_merge(config_mod.DEFAULT_CONFIG, {})):
    from server import main as server_main
from app import tray as app_tray


_FRONTMOST_APP_SCRIPT = (
    'tell application "System Events" to name of first application process '
    'whose frontmost is true'
)


class ModeCandidateHysteresisTests(unittest.TestCase):
    def test_only_confirms_after_two_consecutive_matching_candidates(self):
        last_candidate = None
        observations = 0
        confirmed_modes = []

        candidates = [
            "claude-app",
            "cmux-claude",
            "claude-app",
            "claude-app",
            "claude-app",
            "cmux-claude",
            "cmux-claude",
        ]
        for candidate in candidates:
            (last_candidate,
             observations,
             confirmed) = server_main._confirm_mode_candidate(
                candidate, last_candidate, observations)
            confirmed_modes.append(confirmed)

        self.assertEqual(
            confirmed_modes,
            [None, None, None, "claude-app", None, None, "cmux-claude"],
        )
        self.assertIsNone(last_candidate)
        self.assertEqual(observations, 0)


class ModeDaemonHysteresisIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_resets_streaks_and_confirms_only_a_stable_candidate(self):
        poll_sec = 0.25
        all_modes = ["claude-app", "codex-app", "cmux-claude", "cmux-codex"]
        without_codex_app = [mode for mode in all_modes if mode != "codex-app"]
        cfg = config_mod._deep_merge(config_mod.DEFAULT_CONFIG, {})
        cfg["mode"]["poll_sec"] = poll_sec

        # Each reset follows a one-observation streak of the same candidate:
        # current mode, auto off/on, disabled candidate, then no frontmost app.
        observations = [
            ("ChatGPT", all_modes),
            ("Claude", all_modes),
            ("ChatGPT", all_modes),
            ("cmux", all_modes),
            ("cmux", all_modes),
            ("ChatGPT", all_modes),
            ("ChatGPT", without_codex_app),
            ("ChatGPT", all_modes),
            ("cmux", all_modes),
            (None, all_modes),
            ("cmux", all_modes),
            # Period-2 candidates must never be confirmed.
            ("ChatGPT", all_modes),
            ("cmux", all_modes),
            ("ChatGPT", all_modes),
            ("cmux", all_modes),
            # A stable candidate is confirmed on its second observation.
            ("ChatGPT", all_modes),
            ("ChatGPT", all_modes),
        ]
        observation_index = 0
        manual_pause_seen = False
        confirmations = []

        async def frontmost_app():
            nonlocal observation_index
            if observation_index >= len(observations):
                raise asyncio.CancelledError
            front, enabled = observations[observation_index]
            observation_index += 1
            cfg["mode"]["enabled"] = enabled
            return front

        async def advance_poll(delay):
            nonlocal manual_pause_seen
            if delay == poll_sec and observation_index == 4:
                server_main.bridge.auto_mode = False
            elif delay == 5 and not server_main.bridge.auto_mode:
                manual_pause_seen = True
                server_main.bridge.auto_mode = True

        def record_confirmation(mode):
            confirmations.append((observation_index, mode))

        frontmost = mock.AsyncMock(side_effect=frontmost_app)
        sleep = mock.AsyncMock(side_effect=advance_poll)
        with mock.patch.object(server_main.bridge, "cfg", cfg), \
                mock.patch.object(server_main.bridge, "mode", "claude-app"), \
                mock.patch.object(server_main.bridge, "auto_mode", True), \
                mock.patch.object(server_main, "_frontmost_app", frontmost), \
                mock.patch.object(server_main.asyncio, "sleep", sleep), \
                mock.patch.object(
                    server_main.bridge,
                    "set_mode",
                    side_effect=record_confirmation,
                ) as set_mode:
            await server_main.mode_daemon({})

        # N observations delay a switch by at most (N - 1) * poll_sec.
        self.assertEqual(server_main.MODE_HYSTERESIS_OBSERVATIONS, 2)
        self.assertTrue(manual_pause_seen)
        self.assertEqual(frontmost.await_count, len(observations) + 1)
        set_mode.assert_called_once_with("codex-app")
        self.assertEqual(confirmations, [(len(observations), "codex-app")])


class EmbeddedBridgeShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_stop_denies_pending_decisions_on_bridge_loop(self):
        loop = asyncio.get_running_loop()
        pending = loop.create_future()
        already_resolved = loop.create_future()
        already_resolved.set_result("accept")
        stop_event = asyncio.Event()
        bridge = app_tray.EmbeddedBridge(0)
        with bridge._state_lock:
            bridge._loop = loop
            bridge._stop_event = stop_event

        requests = {
            1: {"future": pending},
            2: {"future": already_resolved},
        }
        with mock.patch.object(server_main.bridge, "pending", requests):
            bridge.request_stop()
            await asyncio.sleep(0)
            bridge.request_stop()
            await asyncio.sleep(0)

        self.assertTrue(bridge._stop_requested.is_set())
        self.assertTrue(stop_event.is_set())
        self.assertEqual(pending.result(), "deny")
        self.assertEqual(already_resolved.result(), "accept")

    async def test_stop_timeout_warns_and_returns_normally(self):
        bridge = app_tray.EmbeddedBridge(0)
        thread = mock.Mock()
        thread.is_alive.side_effect = [True, True]
        bridge._thread = thread

        with mock.patch.object(bridge, "request_stop") as request_stop, \
                mock.patch.object(
                    app_tray.sys,
                    "stderr",
                    new_callable=io.StringIO,
                ) as stderr:
            result = bridge.stop()

        self.assertIsNone(result)
        self.assertEqual(app_tray.STOP_TIMEOUT_SECONDS, 2.0)
        request_stop.assert_called_once_with()
        thread.join.assert_called_once_with(2.0)
        self.assertEqual(
            stderr.getvalue().splitlines(),
            ["ClaudeMicro: bridge 停止待ちを打ち切りました(プロセス終了で回収)"],
        )

    async def test_runner_cleanup_timeout_does_not_escape(self):
        runner = mock.Mock()
        runner.app = object()
        runner.setup = mock.AsyncMock()

        async def wait_forever():
            await asyncio.Event().wait()

        runner.cleanup = mock.AsyncMock(side_effect=wait_forever)
        site = mock.Mock()
        site.start = mock.AsyncMock()
        bridge = app_tray.EmbeddedBridge(0)
        bridge._stop_requested.set()

        with mock.patch.object(app_tray.web, "AppRunner", return_value=runner), \
                mock.patch.object(app_tray.web, "TCPSite", return_value=site), \
                mock.patch.object(app_tray, "_actual_site_port", return_value=12345), \
                mock.patch.object(app_tray, "RUNNER_SHUTDOWN_SECONDS", -0.99), \
                mock.patch.object(
                    server_main, "cancel_background_tasks", mock.Mock()), \
                mock.patch.object(server_main.bridge.adapter, "stop") as stop:
            await bridge._serve()

        runner.cleanup.assert_awaited_once_with()
        stop.assert_called_once_with()
        self.assertIsNone(bridge._loop)
        self.assertIsNone(bridge._stop_event)


class BackgroundTaskCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_cancels_and_awaits_both_tasks(self):
        finished = []

        async def background(name):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0)
                finished.append(name)

        tasks = {
            "mode_task": asyncio.create_task(background("mode")),
            "led_task": asyncio.create_task(background("led")),
        }
        await asyncio.sleep(0)

        await server_main.on_cleanup(tasks)

        self.assertTrue(all(task.done() for task in tasks.values()))
        self.assertCountEqual(finished, ["mode", "led"])


class FrontmostAppPlatformTests(unittest.IsolatedAsyncioTestCase):
    async def test_win32_returns_none_without_spawning_osascript(self):
        spawn = mock.AsyncMock(
            side_effect=AssertionError("non-Darwin must not spawn osascript"))

        with mock.patch.object(server_main.sys, "platform", "win32"), \
                mock.patch.object(
                    server_main.asyncio, "create_subprocess_exec", spawn):
            result = await server_main._frontmost_app()

        self.assertIsNone(result)
        spawn.assert_not_awaited()

    async def test_darwin_keeps_the_existing_osascript_contract(self):
        process = mock.Mock()
        process.communicate = mock.AsyncMock(
            return_value=(b"ChatGPT\n", None))
        spawn = mock.AsyncMock(return_value=process)

        with mock.patch.object(server_main.sys, "platform", "darwin"), \
                mock.patch.object(
                    server_main.asyncio, "create_subprocess_exec", spawn):
            result = await server_main._frontmost_app()

        self.assertEqual(result, "ChatGPT")
        spawn.assert_awaited_once_with(
            "osascript", "-e", _FRONTMOST_APP_SCRIPT,
            stdout=server_main.asyncio.subprocess.PIPE,
            stderr=server_main.asyncio.subprocess.DEVNULL,
        )
        process.communicate.assert_awaited_once_with()

    async def test_cancellation_kills_and_reaps_osascript_then_propagates(self):
        process = mock.Mock()
        process.communicate = mock.AsyncMock(
            side_effect=asyncio.CancelledError)
        process.wait = mock.AsyncMock()
        spawn = mock.AsyncMock(return_value=process)

        with mock.patch.object(server_main.sys, "platform", "darwin"), \
                mock.patch.object(
                    server_main.asyncio, "create_subprocess_exec", spawn):
            with self.assertRaises(asyncio.CancelledError):
                await server_main._frontmost_app()

        process.kill.assert_called_once_with()
        process.wait.assert_awaited_once_with()


class FocusSessionPlatformTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _bridge(mode: str):
        bridge = server_main.Bridge.__new__(server_main.Bridge)
        bridge.mode = mode
        bridge.cfg = {
            "cmux_cli": "/opt/cmux/bin/cmux",
            "mode": {"codex_app": "ChatGPT"},
        }
        bridge._run = mock.AsyncMock()
        return bridge

    async def test_win32_app_focus_is_a_noop(self):
        bridge = self._bridge("claude-app")

        with mock.patch.object(server_main.sys, "platform", "win32"):
            await bridge._focus_session({})

        bridge._run.assert_not_awaited()

    async def test_darwin_keeps_the_existing_open_contract(self):
        bridge = self._bridge("codex-app")

        with mock.patch.object(server_main.sys, "platform", "darwin"):
            await bridge._focus_session({})

        bridge._run.assert_awaited_once_with("open", "-a", "ChatGPT")

    async def test_win32_cmux_focus_remains_available(self):
        bridge = self._bridge("cmux-claude")

        with mock.patch.object(server_main.sys, "platform", "win32"):
            await bridge._focus_session({"cmux_workspace_id": "workspace:42"})

        self.assertEqual(
            bridge._run.await_args_list,
            [
                mock.call(
                    "/opt/cmux/bin/cmux",
                    "workspace-action",
                    "--action",
                    "select",
                    "--workspace",
                    "workspace:42",
                ),
                mock.call(
                    "/opt/cmux/bin/cmux",
                    "focus-window",
                    "--window",
                    "window:1",
                ),
            ],
        )


class DevicePlatformTests(unittest.TestCase):
    def test_win32_import_does_not_load_the_darwin_hid_symbol(self):
        """Import device.py in a child so fake platform/modules cannot leak."""
        repository = Path(__file__).resolve().parents[1]
        program = textwrap.dedent(
            """
            import ctypes
            import itertools
            import json
            import sys
            import threading
            import time
            import types

            sys.path.insert(0, sys.argv[1])
            fake_hid = types.ModuleType("hid")
            fake_hid.__file__ = "sentinel-hid-library"
            sys.modules["hid"] = fake_hid

            def forbidden_cdll(*args, **kwargs):
                raise AssertionError(
                    "ctypes.CDLL was called for HID on simulated win32")

            ctypes.CDLL = forbidden_cdll
            sys.platform = "win32"

            from server import device

            assert device.hid is fake_hid
            print("guarded")
            """
        )

        with tempfile.TemporaryDirectory() as fake_home:
            environment = os.environ.copy()
            environment.update({
                "HOME": fake_home,
                "USERPROFILE": fake_home,
                "CLAUDEMICRO_NO_DEVICE": "1",
                "PYTHONNOUSERSITE": "1",
            })
            environment.pop("PYTHONPATH", None)
            completed = subprocess.run(
                [sys.executable, "-I", "-c", program, str(repository)],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(
            completed.returncode, 0,
            f"child stderr:\n{completed.stderr}\nchild stdout:\n{completed.stdout}",
        )
        self.assertEqual(completed.stdout.strip(), "guarded")


class HookLogPlatformTests(unittest.TestCase):
    def test_clients_append_without_fcntl(self):
        clients = (
            (hook_client, "claudecode.log"),
            (codex_hook_client, "codexhook.log"),
        )

        with tempfile.TemporaryDirectory() as directory:
            for client, filename in clients:
                with self.subTest(client=client.__name__):
                    path = os.path.join(directory, filename)
                    with open(path, "w", encoding="utf-8") as log_file:
                        log_file.write("existing\n")

                    with mock.patch.object(client, "LOG", path), \
                            mock.patch.object(client, "fcntl", None):
                        client.log("windows fallback")

                    with open(path, encoding="utf-8") as log_file:
                        self.assertEqual(
                            log_file.read(),
                            "existing\nwindows fallback\n",
                        )


if __name__ == "__main__":
    unittest.main()
