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

from . import actions as actions_mod
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
        # セッション付随情報: session_id -> {cmux_workspace_id, is_cmux, ...} (SessionStart で登録, #4)
        self.session_info: dict[str, dict] = {}
        self.selected_agent = None  # 選択中エージェントキー index
        self.last_raw_key: dict | None = None   # キー学習・デバッグ表示用
        self._learn_future: asyncio.Future | None = None
        # モード状態 (issue #11): 4モードのいずれか。auto_mode=True なら前面アプリで自動切替
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
        # モード切替キー (ACT12): tap=claude/codex循環 / double=app/cmux(cli)循環 / long=auto (issue #11)
        # このキーだけは codex モードでも常に有効（モードを抜ける手段のため）
        if key_id == self.cfg["mode"]["toggle_key"]:
            if gesture == "tap":
                self.auto_mode = False
                self._toggle_family()
            elif gesture == "double":
                self.auto_mode = False
                self._toggle_context()
            elif gesture == "long":
                self.auto_mode = True  # 前面アプリ自動切替に復帰
            return
        # ★全モードで本アプリが頭脳: config 解釈・エージェント選択/表示・LED は本アプリが行う (issue #11)。
        #   codex-app でも本アプリの設定通りに動作させ、"アクションの実行だけ" 公式 Codex アプリへ委譲する
        #   （run_action / _exec_action 内でモード別にディスパッチ）。エージェント表示を統合するため
        #   codex アプリ側も本アプリが制御する。
        binding = self.cfg["keys"].get(key_id)
        if not binding or binding.get("role") in (None, "none"):
            return
        role = binding["role"]
        if role == "agent":
            # エージェントキー = 選択 + 前面化のみ (承認はしない, issue #4)
            self.select_agent(binding.get("index"))
        elif role == "action":
            self.run_action(binding.get("action"), gesture)

    def _toggle_family(self):
        cur_ctx = actions_mod.mode_context(self.mode)
        new_fam = "codex" if actions_mod.mode_family(self.mode) == "claude" else "claude"
        self.set_mode(actions_mod.mode_for(new_fam, cur_ctx) or self.mode)

    def _toggle_context(self):
        cur_fam = actions_mod.mode_family(self.mode)
        new_ctx = "cmux" if actions_mod.mode_context(self.mode) == "app" else "app"
        self.set_mode(actions_mod.mode_for(cur_fam, new_ctx) or self.mode)

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

    # ---- モード制御 (issue #7 → #11: 4モード) ----

    def set_mode(self, mode: str):
        """4モードを切り替え、枠(アンビエント)を color=family / effect=context で更新。"""
        if mode not in actions_mod.MODE_IDS:
            self.apply_ambient()
            return
        if mode != self.mode:
            self.mode = mode
            print(f"[mode] -> {mode}", flush=True)
        self.apply_ambient()

    def apply_ambient(self):
        """枠色=family(claude=コーラル/codex=青)、エフェクト=context(app=solid/cmux=breath)。"""
        m = self.cfg["mode"]
        family = actions_mod.mode_family(self.mode)
        context = actions_mod.mode_context(self.mode)
        color = m["ambient_codex"] if family == "codex" else m["ambient_claude"]
        # 4=breath(cmux) / 1=solid(app)。device.EFFECT と一致
        effect = 4 if context == "cmux" else 1
        speed = 0.35 if context == "cmux" else 0.0
        self.adapter.set_ambient_color(color, brightness=m["ambient_brightness"],
                                       effect=effect, speed=speed)

    def set_agent_led(self, index: int, state: str):
        """LED/エージェント表示は全モードで本アプリが制御（表示統合）。codex-app 含む。"""
        self.adapter.set_agent_led(index, state)

    # ---- エージェントキー: 選択 + 前面化 (issue #4) ----

    def select_agent(self, index):
        """エージェントキー押下: セッションを選択し、そのウィンドウ/タブを前面化。"""
        self.selected_agent = index
        sid = next((s for s, i in self.sessions.items() if i == index), None)
        info = self.session_info.get(sid, {}) if sid else {}
        print(f"[agent] select index={index} session={sid} ws={info.get('cmux_workspace_id')}", flush=True)
        if self.loop:
            self.loop.create_task(self._focus_session(info))

    async def _focus_session(self, info: dict):
        """cmux モードは CLI でタブ選択、app モードはアプリ前面化。"""
        context = actions_mod.mode_context(self.mode)
        try:
            if context == "cmux" and info.get("cmux_workspace_id"):
                cli = self.cfg.get("cmux_cli")
                ws = info["cmux_workspace_id"]
                await self._run(cli, "workspace-action", "--action", "select", "--workspace", ws)
                await self._run(cli, "focus-window", "--window", "window:1")
            else:
                app = "Claude" if actions_mod.mode_family(self.mode) == "claude" else self.cfg["mode"]["codex_app"]
                await self._run("open", "-a", app)
        except Exception as e:
            print(f"[agent] focus 失敗: {e}", flush=True)

    async def _run(self, *argv):
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.communicate()

    # ---- アクションキー実行 (issue #5, 実処理は順次実装) ----

    def run_action(self, action_id, gesture):
        """本アプリの設定に基づきアクションを決定。実行先はモードで異なる:
        claude系=直接 / codex-app=公式Codexアプリへ委譲(実行のみパススルー) / cmux-codex=codex CLI。"""
        scope = actions_mod.action_scope(action_id)
        if scope is None:
            return
        family = actions_mod.mode_family(self.mode)
        # scope がモードに合わない専用アクションは無視 (共通は常に可)
        if scope != "common" and scope != family:
            print(f"[action] {action_id} はモード({self.mode})対象外", flush=True)
            return
        # 承認系(共通)は本アプリが直接解決 (Claude Code hook 由来の保留要求)
        if action_id in ("approve", "reject", "hold"):
            self._resolve_selected_or_oldest(
                {"approve": "accept", "reject": "deny", "hold": "fallback"}[action_id])
            return
        # それ以外は実行先へディスパッチ (決定は本アプリ、実行のみ委譲)
        self._exec_action(action_id)

    def _exec_action(self, action_id):
        """アクション実行のディスパッチ (実処理は #5 で順次実装)。"""
        ctx = actions_mod.mode_context(self.mode)
        fam = actions_mod.mode_family(self.mode)
        if fam == "codex" and ctx == "app":
            # TODO(#5): 公式 Codex アプリへ実行を委譲 (AppleScript/アプリ操作)。決定は本アプリ設定
            print(f"[action] {action_id} -> codex-app へ委譲 (未実装)", flush=True)
        elif ctx == "cmux":
            # TODO(#5): 対象 cmux タブの CLI へキーストローク送出
            print(f"[action] {action_id} -> cmux CLI 送出 (未実装)", flush=True)
        else:
            # TODO(#5): claude-app へキーストローク送出
            print(f"[action] {action_id} -> claude-app 送出 (未実装)", flush=True)

    def _resolve_selected_or_oldest(self, result: str):
        """選択中エージェントの保留を優先、なければ最古の保留を解決。"""
        if self.selected_agent is not None:
            for req in sorted(self.pending.values(), key=lambda r: r["created"]):
                if req["agent_index"] == self.selected_agent and not req["future"].done():
                    req["future"].set_result(result)
                    return
        self._resolve_oldest(result)


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
        "selected_agent": bridge.selected_agent,
    })


async def handle_actions(request: web.Request):
    """アクションカタログとモード定義を返す (console のキー設定 UI 用, #5/#12)。"""
    return web.json_response({
        "actions": actions_mod.ACTIONS,
        "modes": actions_mod.MODES,
        "icon_choices": actions_mod.ICON_CHOICES,
    })


async def handle_mode(request: web.Request):
    """コンソールからのモード操作。body: {mode: <4モードid>} または {auto: true}"""
    body = await request.json()
    if body.get("auto") is True:
        bridge.auto_mode = True
    elif body.get("mode") in actions_mod.MODE_IDS:
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


def _mode_from_frontmost(front: str) -> str:
    """前面アプリ名から4モードを推定 (issue #11)。
    cmux 前面時は context のみ cmux にし family は現状維持 (cmux内のAI種別は前面名で判別不可)。"""
    m = bridge.cfg["mode"]
    if front == m.get("cmux_app"):
        fam = actions_mod.mode_family(bridge.mode)
        return f"cmux-{fam}"
    if front == m.get("codex_app"):
        return "codex-app"
    if "Claude" in front:
        return "claude-app"
    return bridge.mode  # 不明な前面アプリでは維持


async def mode_daemon(app):
    """auto モード時に前面アプリでモード自動切替 + 枠の色を定期再アサート。"""
    await asyncio.sleep(2)  # デバイス接続待ち
    bridge.apply_ambient()
    while True:
        try:
            if bridge.auto_mode:
                front = await _frontmost_app()
                if front:
                    cand = _mode_from_frontmost(front)
                    if cand in bridge.cfg["mode"].get("enabled", actions_mod.MODE_IDS):
                        bridge.set_mode(cand)
            # 全モードで枠を維持・再アサート (表示は本アプリが統合管理。codex-app の公式上書きにも対抗)
            bridge.apply_ambient()
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
    app.router.add_get("/api/actions", handle_actions)
    app.router.add_get("/", handle_index)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)
