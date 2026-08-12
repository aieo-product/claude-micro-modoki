"""claude-micro-modoki bridge v2

- POST /decision      : hook_client.py からの承認要求 (upstream 互換: result=accept/fallback/deny/timeout)
- GET  /api/status    : デバイス状態・保留中の承認要求・セッション割当
- GET/PUT /api/config : 設定 (console UI 用)
- POST /api/learn     : キー学習 (次に押された物理キーの key_id を返す)
- POST /api/resolve   : Web からの承認 (Tailscale 経由のリモート承認フォールバック)
- GET  /              : 設定コンソール (console/index.html)

バインドは 127.0.0.1 固定。リモートからは Tailscale の `tailscale serve` 等で到達する。
APPROVAL_BRIDGE_TOKEN 環境変数を設定すると /decision 以外の API にトークン必須。
"""

import asyncio
import itertools
import json
import os
import time

from aiohttp import web

from . import config as config_mod
from .device import HidAdapter

HOST = "127.0.0.1"
PORT = 35703
CONSOLE_PATH = os.path.join(os.path.dirname(__file__), "..", "console", "index.html")
TOKEN = os.environ.get("APPROVAL_BRIDGE_TOKEN", "")

AGENT_KEY_COUNT = 6


class Bridge:
    def __init__(self):
        self.cfg = config_mod.load()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._req_ids = itertools.count(1)
        # 保留中の承認要求: id -> dict(session_id, tool_name, detail, created, future, agent_index)
        self.pending: dict[int, dict] = {}
        # セッション ⇔ エージェントキー割当 (LRU): session_id -> index(1..6)
        self.sessions: dict[str, int] = {}
        self.last_raw_key: dict | None = None   # キー学習・デバッグ表示用
        self._learn_future: asyncio.Future | None = None
        # モード状態 (issue #7): "claude" / "codex"。auto_mode=True なら前面アプリで自動切替
        self.mode = self.cfg["mode"]["current"]
        self.auto_mode = self.cfg["mode"]["auto"]
        self.adapter = HidAdapter(
            vid=int(self.cfg["device"]["vid"], 0),
            pid=int(self.cfg["device"]["pid"], 0),
            timings=self.cfg["timings"],
            on_gesture=self._on_gesture_threadsafe,
            on_raw_key=self._on_raw_key_threadsafe,
        )

    # ---- HID コールバック (リーダースレッドから呼ばれる) ----

    def _on_raw_key_threadsafe(self, key_id: str):
        if self.loop:
            self.loop.call_soon_threadsafe(self._on_raw_key, key_id)

    def _on_gesture_threadsafe(self, key_id: str, gesture: str):
        if self.loop:
            self.loop.call_soon_threadsafe(self._on_gesture, key_id, gesture)

    def _on_raw_key(self, key_id: str):
        self.last_raw_key = {"key_id": key_id, "at": time.time()}
        if self._learn_future and not self._learn_future.done():
            self._learn_future.set_result(key_id)

    def _on_gesture(self, key_id: str, gesture: str):
        if self._learn_future and not self._learn_future.done():
            return  # 学習モード中は承認操作に使わない
        # モード切替キー (issue #7): tap でトグル / long で auto に戻す
        if key_id == self.cfg["mode"]["toggle_key"]:
            if gesture == "tap":
                self.auto_mode = False
                self.set_mode("codex" if self.mode == "claude" else "claude")
            elif gesture == "long":
                self.auto_mode = True  # 前面アプリ自動切替に復帰
            return
        binding = self.cfg["keys"].get(key_id)
        if not binding or binding.get("role") in (None, "none"):
            return
        role = binding["role"]
        if role == "agent":
            result = self.cfg["gestures"].get(gesture)
            if result:
                self._resolve_by_agent_index(binding.get("index"), result)
        elif role in ("accept", "fallback", "deny"):
            # 固定ロールキーはジェスチャーによらず最古の保留要求に作用する
            self._resolve_oldest(role)

    # ---- 承認要求の解決 ----

    def _resolve_by_agent_index(self, index, result: str):
        for req in sorted(self.pending.values(), key=lambda r: r["created"]):
            if req["agent_index"] == index and not req["future"].done():
                req["future"].set_result(result)
                return

    def _resolve_oldest(self, result: str):
        for req in sorted(self.pending.values(), key=lambda r: r["created"]):
            if not req["future"].done():
                req["future"].set_result(result)
                return

    def assign_agent_key(self, session_id: str) -> int:
        if session_id in self.sessions:
            self.sessions[session_id] = self.sessions.pop(session_id)  # LRU 更新
            return self.sessions[session_id]
        used = set(self.sessions.values())
        for i in range(1, AGENT_KEY_COUNT + 1):
            if i not in used:
                self.sessions[session_id] = i
                return i
        # 満杯: 最も古いセッションのキーを奪う (LRU)
        oldest = next(iter(self.sessions))
        idx = self.sessions.pop(oldest)
        self.sessions[session_id] = idx
        return idx

    # ---- モード制御 (issue #7) ----

    def set_mode(self, mode: str):
        """claude/codex を切り替え、アンビエントリング(枠)の色を更新する。"""
        if mode not in ("claude", "codex") or mode == self.mode:
            self.apply_ambient()  # 同一モードでも枠を再アサート
            return
        self.mode = mode
        print(f"[mode] -> {mode}", flush=True)
        self.apply_ambient()

    def apply_ambient(self):
        """現在モードのアンビエント色を枠に反映。claude=オレンジ / codex=青。"""
        m = self.cfg["mode"]
        color = m["ambient_codex"] if self.mode == "codex" else m["ambient_claude"]
        self.adapter.set_ambient_color(color, brightness=m["ambient_brightness"])

    def set_agent_led(self, index: int, state: str):
        """codex モードでは Codex アプリに LED を譲るため、承認 LED は書き込まない。"""
        if self.mode == "codex":
            return
        self.adapter.set_agent_led(index, state)


bridge = Bridge()


def _auth_ok(request: web.Request) -> bool:
    if not TOKEN:
        return True
    supplied = request.headers.get("X-Bridge-Token") or request.query.get("token", "")
    return supplied == TOKEN


@web.middleware
async def auth_middleware(request, handler):
    # /decision は localhost の hook_client 専用なのでトークン不要 (バインドが 127.0.0.1 のため)
    if request.path.startswith("/api/") and not _auth_ok(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def handle_decision(request: web.Request):
    data = await request.json()
    session_id = str(data.get("session_id") or "unknown")
    tool_name = str(data.get("tool_name") or "?")
    tool_input = json.dumps(data.get("tool_input") or {}, ensure_ascii=False)[:200]

    req_id = next(bridge._req_ids)
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    agent_index = bridge.assign_agent_key(session_id)
    bridge.pending[req_id] = {
        "id": req_id, "session_id": session_id, "tool_name": tool_name,
        "detail": tool_input, "created": time.time(),
        "future": fut, "agent_index": agent_index,
    }
    bridge.set_agent_led(agent_index, "pending")  # codex モードでは no-op
    try:
        result = await asyncio.wait_for(fut, timeout=bridge.cfg["approval_timeout_sec"])
    except asyncio.TimeoutError:
        result = "timeout"  # hook_client 側で deny に落ちる (フェイルクローズ)
    finally:
        bridge.pending.pop(req_id, None)
        bridge.set_agent_led(agent_index, result if result != "timeout" else "idle")
    return web.json_response({"result": result})


async def handle_status(request: web.Request):
    now = time.time()
    return web.json_response({
        "device": bridge.adapter.status,
        "brightness": bridge.cfg["brightness"],
        "led_control": True,  # T0-4 解明済み: vendor JSON-RPC で LED 制御可能
        "pending": [
            {"id": r["id"], "session_id": r["session_id"], "tool_name": r["tool_name"],
             "detail": r["detail"], "age_sec": round(now - r["created"], 1),
             "agent_index": r["agent_index"]}
            for r in sorted(bridge.pending.values(), key=lambda r: r["created"])
        ],
        "sessions": bridge.sessions,
        "last_raw_key": bridge.last_raw_key,
        "mode": bridge.mode,
        "auto_mode": bridge.auto_mode,
    })


async def handle_mode(request: web.Request):
    """コンソールからのモード操作。body: {mode: "claude"|"codex"} または {auto: true}"""
    body = await request.json()
    if body.get("auto") is True:
        bridge.auto_mode = True
    elif body.get("mode") in ("claude", "codex"):
        bridge.auto_mode = False
        bridge.set_mode(body["mode"])
    return web.json_response({"mode": bridge.mode, "auto_mode": bridge.auto_mode})


async def handle_get_config(request: web.Request):
    return web.json_response(bridge.cfg)


async def handle_put_config(request: web.Request):
    body = await request.json()
    bridge.cfg = config_mod.save(body)
    bridge.adapter.update_timings(bridge.cfg["timings"])
    return web.json_response(bridge.cfg)


async def handle_learn(request: web.Request):
    if bridge._learn_future and not bridge._learn_future.done():
        bridge._learn_future.cancel()
    bridge._learn_future = asyncio.get_event_loop().create_future()
    try:
        key_id = await asyncio.wait_for(bridge._learn_future, timeout=15)
        return web.json_response({"key_id": key_id})
    except asyncio.TimeoutError:
        return web.json_response({"error": "timeout"}, status=408)
    finally:
        bridge._learn_future = None


async def handle_resolve(request: web.Request):
    body = await request.json()
    req = bridge.pending.get(int(body.get("id", -1)))
    result = body.get("result")
    if req is None or result not in ("accept", "fallback", "deny"):
        return web.json_response({"error": "bad request"}, status=400)
    if not req["future"].done():
        req["future"].set_result(result)
    return web.json_response({"ok": True})


async def handle_index(request: web.Request):
    return web.FileResponse(CONSOLE_PATH)


async def _frontmost_app() -> str | None:
    """最前面アプリ名を取得 (macOS)。失敗時 None。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e",
            'tell application "System Events" to name of first application process whose frontmost is true',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        return out.decode().strip() or None
    except (OSError, asyncio.CancelledError):
        return None


async def mode_daemon(app):
    """auto モード時に前面アプリでモード自動切替 + 枠の色を定期再アサート。"""
    codex_app = bridge.cfg["mode"]["codex_app"]
    # 起動時に一度枠を反映（デバイス接続を少し待つ）
    await asyncio.sleep(2)
    bridge.apply_ambient()
    while True:
        try:
            if bridge.auto_mode:
                front = await _frontmost_app()
                if front is not None:
                    bridge.set_mode("codex" if front == codex_app else "claude")
            if bridge.mode == "claude":
                bridge.apply_ambient()  # Codexアプリ等の上書きに対し claude 時は枠を維持
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            break


async def on_startup(app):
    bridge.loop = asyncio.get_event_loop()
    bridge.adapter.start()
    app["mode_task"] = asyncio.create_task(mode_daemon(app))


async def on_cleanup(app):
    task = app.get("mode_task")
    if task:
        task.cancel()


def create_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_post("/decision", handle_decision)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/config", handle_get_config)
    app.router.add_put("/api/config", handle_put_config)
    app.router.add_post("/api/learn", handle_learn)
    app.router.add_post("/api/resolve", handle_resolve)
    app.router.add_post("/api/mode", handle_mode)
    app.router.add_get("/", handle_index)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)
