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
import collections
import itertools
import json
import os
import sys
import time
from contextlib import suppress

from aiohttp import web

from . import actions as actions_mod
from . import config as config_mod
from .device import EFFECT, STATE_BRIGHTNESS, STATE_COLOR, HidAdapter

HOST = "127.0.0.1"
PORT = 35703
CONSOLE_PATH = os.path.join(os.path.dirname(__file__), "..", "console", "index.html")
TOKEN = os.environ.get("APPROVAL_BRIDGE_TOKEN", "")

AGENT_KEY_COUNT = 6
SESSION_INFO_LIMIT = 32
OBSERVED_INPUT_SESSION_LIMIT = 32
OBSERVED_INPUT_ID_LIMIT = 8
OBSERVED_INPUT_DUMMY_ID = "__missing_tool_use_id__"
# family 色 (エージェントキーの色ループ用): claude=コーラル / codex=青。config.mode の枠色と一致
FAMILY_COLOR = {"claude": 0xD97757, "codex": 0x0A84FF}
# これらの状態のキーだけ「状態色⇄family色」でループ (active のみアニメ=軽量)
ANIMATED_STATES = {"thinking", "input"}
ANIM_INTERVAL = 0.8  # 秒
# A stable candidate is suppressed for at most (N - 1) * poll_sec before confirmation.
MODE_HYSTERESIS_OBSERVATIONS = 2


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
        # Codex observe-only 承認の tool_use_id。セッション/ID とも固定上限で保持する。
        self.observed_input: dict[str, set[str]] = {}
        self.selected_agent = None  # 選択中エージェントキー index
        # エージェントキー状態: index -> {"state", "family"}。状態機とアニメータで共有
        self.agent_state: dict[int, dict] = {}
        # フックイベント監視用。常駐メモリを増やさない固定長リングバッファ
        self.events = collections.deque(maxlen=100)
        self._led_last: dict[int, tuple] = {}  # index -> 最後に書いた(color,brightness) 重複書込抑止 #9
        self._anim_phase = False
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
            on_connect=self._on_connect_threadsafe,
        )

    def _on_connect_threadsafe(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self._reassert_display)

    def _reassert_display(self):
        """(再)接続時のみ枠とセッション LED を一度再アサート（常時再送しない=軽量）。
        デバイスは状態を失っているので LED キャッシュをクリアして強制再書き込みする。"""
        self._led_last.clear()
        self.apply_ambient()
        for idx, st in self.agent_state.items():
            self._write_agent_color(idx, STATE_COLOR.get(st["state"], STATE_COLOR["idle"]),
                                    STATE_BRIGHTNESS.get(st["state"], 0.25))

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
        # ノブ(エンコーダ) / アナログスティック(十字) は物理キー割当ではなく専用設定に紐づく (#35)
        if key_id in ("ENC_CW", "ENC_CC", "ENC_CLK"):
            self._on_knob(key_id, gesture)
            return
        if key_id.startswith("STICK_"):
            direction = key_id[len("STICK_"):].lower()
            action = (self.cfg.get("analog_stick") or {}).get(direction)
            if action:
                self.run_action(action, gesture)
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

    def _on_knob(self, key_id: str, gesture: str):
        """ノブ(エンコーダ)操作を config.knob に基づきアクションへディスパッチ (#35)。
        mode: input-nav / inference / scroll(プリセット) / custom(回転/クリック/長押しを個別割当)。"""
        knob = self.cfg.get("knob") or {}
        mode = knob.get("mode", "scroll")
        if key_id == "ENC_CLK":  # クリック / 長押し
            if mode == "custom":
                action = knob.get("long_press") if gesture == "long" else knob.get("click")
            else:
                action = "plan-mode" if gesture == "long" else "interrupt"
            if action:
                self.run_action(action, gesture)
            return
        cw = key_id == "ENC_CW"  # 右回転 / 左回転
        if mode == "custom":
            action = knob.get("rotate_cw") if cw else knob.get("rotate_ccw")
        elif mode == "scroll":
            action = "scroll-down" if cw else "scroll-up"
        elif mode == "inference":
            action = "inference-effort"
        elif mode == "input-nav":
            action = "input-nav"
        else:
            action = None
        if action:
            self.run_action(action, gesture)

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

    def _deny_pending_for_session(self, session_id: str, *, detach: bool = False):
        """セッション単位で保留承認を fail-close し、必要ならキー所有権も外す。"""
        for request in self.pending.values():
            if request.get("session_id") != session_id:
                continue
            if not request["future"].done():
                request["future"].set_result("deny")
            if detach:
                original_index = request.get("agent_index")
                if not isinstance(request.get("public_agent_index"), int):
                    request["public_agent_index"] = (
                        original_index if isinstance(original_index, int) else -1)
                request["agent_index"] = None
                # TODO(follow-up): 再起動/キー再割当を跨ぐ厳密な pending 所有権には世代 ID を追加する。

    @staticmethod
    def _observed_tool_key(tool_use_id) -> str:
        if tool_use_id is None or tool_use_id == "":
            return OBSERVED_INPUT_DUMMY_ID
        return str(tool_use_id)

    def add_observed_input(self, session_id: str, tool_use_id):
        """observe-only 承認を固定長で記録する。古い非アクティブ session を優先して捨てる。"""
        tool_ids = self.observed_input.get(session_id)
        if tool_ids is None:
            while len(self.observed_input) >= OBSERVED_INPUT_SESSION_LIMIT:
                victim = next(
                    (sid for sid in self.observed_input if sid not in self.sessions),
                    next(iter(self.observed_input)),
                )
                self.observed_input.pop(victim, None)
            tool_ids = set()
            self.observed_input[session_id] = tool_ids
        tool_key = self._observed_tool_key(tool_use_id)
        if tool_key not in tool_ids and len(tool_ids) >= OBSERVED_INPUT_ID_LIMIT:
            tool_ids.pop()
        tool_ids.add(tool_key)

    def remove_observed_input(self, session_id: str, tool_use_id):
        """対応する PostToolUse だけを解決し、別ツールの承認表示は維持する。"""
        tool_ids = self.observed_input.get(session_id)
        if tool_ids is None:
            return
        tool_ids.discard(self._observed_tool_key(tool_use_id))
        if not tool_ids:
            self.observed_input.pop(session_id, None)

    def clear_observed_input(self, session_id: str):
        self.observed_input.pop(session_id, None)

    def _trim_session_info(self):
        """直近情報を32件まで残し、キーを持つ active session は削除しない。"""
        while len(self.session_info) > SESSION_INFO_LIMIT:
            victim = next(
                (sid for sid in self.session_info if sid not in self.sessions), None)
            if victim is None:
                break
            self.session_info.pop(victim, None)

    def assign_agent_key(self, session_id: str) -> int:
        if session_id in self.sessions:
            self.sessions[session_id] = self.sessions.pop(session_id)  # LRU 更新
            return self.sessions[session_id]
        used = set(self.sessions.values())
        for i in range(1, AGENT_KEY_COUNT + 1):
            if i not in used:
                self.sessions[session_id] = i
                return i
        # 満杯: 承認保留中/選択中でない最古のセッションを追い出す (#1: 保留中キーを奪わない)
        busy = {r["agent_index"] for r in self.pending.values()
                if r.get("session_id") in self.sessions and not r["future"].done()}
        victim = next((s for s, i in self.sessions.items()
                       if i not in busy and i != self.selected_agent), None)
        if victim is None:
            victim = next(iter(self.sessions))  # 全キーが多忙: やむなく最古
        idx = self.sessions.pop(victim)
        # 多忙キーをやむなく再利用するときも、古い承認を新セッションへ誤帰属させない
        self._deny_pending_for_session(victim, detach=True)
        # session_info はエビクション時に消さない (#7: 再活性化で focus 情報を失わない。SessionEnd で解放)
        if idx == self.selected_agent:
            self.selected_agent = None  # #2: 奪ったキーが選択中なら選択解除
        self.sessions[session_id] = idx
        return idx

    # ---- セッションライフサイクル (issue #4/#6) ----

    def register_session(self, session_id: str, info: dict) -> int:
        """SessionStart: エージェントキー確保 + cmux workspace 等を記録 + idle 点灯。"""
        idx = self.assign_agent_key(session_id)
        family = "codex" if info.get("family") == "codex" else "claude"
        # 再登録も「直近」として扱い、dict の挿入順を更新する。
        self.session_info.pop(session_id, None)
        self.session_info[session_id] = {
            "cmux_workspace_id": (info.get("env") or {}).get("cmux_workspace_id"),
            "is_cmux": bool((info.get("env") or {}).get("is_cmux")),
            "cwd": info.get("cwd"),
        }
        self._trim_session_info()
        self.notify_session(session_id, "idle", family=family)
        print(f"[session] start {session_id} -> AG{idx-1} cmux={self.session_info[session_id]['is_cmux']}", flush=True)
        return idx

    def release_session(self, session_id: str):
        """SessionEnd: キー解放 + LED 消灯 + 選択解除。"""
        idx = self.sessions.pop(session_id, None)
        self.session_info.pop(session_id, None)
        self.clear_observed_input(session_id)
        # 既に eviction 済みで idx が無くても session_id で確実に fail-close する。
        self._deny_pending_for_session(session_id, detach=True)
        if idx is not None:
            if self.selected_agent == idx:
                self.selected_agent = None  # #2: 解放したキーの選択を残さない
            self.set_agent_state(idx, "off")
            print(f"[session] end {session_id} (AG{idx-1} 解放)", flush=True)

    def notify_session(self, session_id: str, state: str, family: str | None = None):
        """フックイベントの状態を LED に反映。SessionStart が無くてもキーを自動割当する。
        承認保留(input)中の良性遷移は抑止するが、error は必ず表示する。"""
        idx = self.sessions.get(session_id)
        if idx is None:
            idx = self.assign_agent_key(session_id)
        has_pending = any(r["session_id"] == session_id and r["agent_index"] == idx
                          and not r["future"].done()
                          for r in self.pending.values())
        has_observed_input = bool(self.observed_input.get(session_id))
        if (has_pending or has_observed_input) and state in ("thinking", "done", "idle"):
            # error 表示中は input 抑止でも赤を消さず、それ以外は input を維持する。
            maintained_state = (
                "error" if self.agent_state.get(idx, {}).get("state") == "error"
                else "input")
            if family is not None:
                self.set_agent_state(idx, maintained_state, family=family)
            return
        self.set_agent_state(idx, state, family=family)

    # ---- モード制御 (issue #7 → #11: 4モード) ----

    def set_mode(self, mode: str):
        """4モードを切り替え。枠(HID書き込み)は**変化時のみ**反映（同一モードでは書き込まない=軽量）。"""
        if mode not in actions_mod.MODE_IDS or mode == self.mode:
            return
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

    def set_agent_state(self, index, state: str, family: str | None = None):
        """エージェントキーの状態を設定 (本家凡例: idle/thinking/done/input/error/off)。
        全モードで本アプリが制御。thinking/input は animator が状態色⇄family色でループ、他は静的。"""
        if index is None:
            return
        if state == "off":
            self.agent_state.pop(index, None)
            self._write_agent_color(index, 0, 0.0, EFFECT["off"])
            return
        current = self.agent_state.get(index)
        fam = family or (current or {}).get("family") or "claude"
        requested = {"state": state, "family": fam}
        if current == requested:
            return  # 論理状態が同一なら animator の表示相を含め一切触らない (#9)
        self.agent_state[index] = requested
        # 初期色を即表示 (animated でも待たずに反映。以降 animator がトグル)
        self._write_agent_color(index, STATE_COLOR.get(state, STATE_COLOR["idle"]),
                                STATE_BRIGHTNESS.get(state, 0.25))

    def _write_agent_color(self, index, color: int, brightness: float, effect=EFFECT["solid"]):
        """実 HID 書き込み。同一(色,輝度)なら省く (#9)。animator も本経路で dedup 共有。"""
        key = (color, round(brightness, 3))
        if self._led_last.get(index) == key:
            return
        self._led_last[index] = key
        self.adapter.set_agent_rgb(index, color, brightness, effect)

    # 旧 API 互換の薄いラッパ (呼び出し側簡略化)
    def set_agent_led(self, index, state: str):
        self.set_agent_state(index, state)

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
            elif sys.platform == "darwin":
                app = "Claude" if actions_mod.mode_family(self.mode) == "claude" else self.cfg["mode"]["codex_app"]
                await self._run("open", "-a", app)
            else:
                # TODO(win32): アプリ前面化
                pass
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
        # scope がモードに合わない専用アクションは無視。common と control(ノブ/十字用の
        # 汎用ナビゲーション, #35) は全モードで有効。
        if scope not in ("common", "control") and scope != family:
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
    if not isinstance(data, dict):
        return web.json_response({"error": "bad request"}, status=400)
    session_id = str(data.get("session_id") or "unknown")
    family = "codex" if data.get("family") == "codex" else "claude"
    tool_name = str(data.get("tool_name") or "?")
    tool_input = json.dumps(data.get("tool_input") or {}, ensure_ascii=False)[:200]

    req_id = next(bridge._req_ids)
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    agent_index = bridge.assign_agent_key(session_id)
    bridge.pending[req_id] = {
        "id": req_id, "session_id": session_id, "tool_name": tool_name,
        "detail": tool_input, "created": time.time(),
        "future": fut, "agent_index": agent_index,
        "public_agent_index": agent_index,
    }
    bridge.set_agent_state(agent_index, "input", family=family)  # 承認待ち = 入力が必要(アンバー)
    bridge.events.append({
        "ts": time.time(), "family": family, "session_id": session_id,
        "session_short": session_id[:8], "event": "PreToolUse", "state": "input",
        "tool_name": tool_name, "detail": tool_input, "agent_index": agent_index,
    })
    result = "timeout"  # キャンセル等で応答不能になった場合もフェイルクローズ相当を維持
    try:
        result = await asyncio.wait_for(fut, timeout=bridge.cfg["approval_timeout_sec"])
    except asyncio.TimeoutError:
        result = "timeout"  # hook_client 側で deny に落ちる (フェイルクローズ)
    finally:
        bridge.pending.pop(req_id, None)
        # 同じキーに別の承認が残る場合は input を維持。終了/再割当済みのキーには触れない
        if bridge.sessions.get(session_id) == agent_index:
            current_state = bridge.agent_state.get(agent_index, {}).get("state")
            if current_state != "error":  # StopFailure の terminal error は消さない
                has_pending = any(
                    r.get("session_id") == session_id
                    and r.get("agent_index") == agent_index
                    and not r["future"].done()
                    for r in bridge.pending.values())
                if has_pending or bridge.observed_input.get(session_id):
                    bridge.set_agent_state(agent_index, "input")
                else:
                    # 承認後はツールが動く=thinking / タイムアウト(拒否)は待機に戻す
                    bridge.set_agent_state(
                        agent_index, "idle" if result == "timeout" else "thinking")
    return web.json_response({"result": result})


def _public_pending_agent_index(request: dict) -> int:
    value = request.get("public_agent_index", request.get("agent_index"))
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


async def handle_status(request: web.Request):
    now = time.time()
    return web.json_response({
        "device": bridge.adapter.status,
        "brightness": bridge.cfg["brightness"],
        "led_control": True,  # T0-4 解明済み: vendor JSON-RPC で LED 制御可能
        "pending": [
            {"id": r["id"], "session_id": r["session_id"], "tool_name": r["tool_name"],
             "detail": r["detail"], "age_sec": round(now - r["created"], 1),
             "agent_index": _public_pending_agent_index(r)}
            for r in sorted(bridge.pending.values(), key=lambda r: r["created"])
        ],
        "sessions": bridge.sessions,
        "session_info": bridge.session_info,
        "agent_state": {str(i): st for i, st in bridge.agent_state.items()},
        "events": list(reversed(bridge.events))[:50],
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


async def handle_event(request: web.Request):
    """Claude/Codex の観測イベントを状態機と監視リングバッファへ反映する。"""
    body = await request.json()
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    event = body.get("event")
    sid = str(body.get("session_id") or "")
    if not sid:
        return web.json_response({"ok": False, "error": "no session_id"}, status=400)

    family = "codex" if body.get("family") == "codex" else "claude"
    state = None
    agent_index = bridge.sessions.get(sid)
    if event == "SessionStart":
        state = "idle"
        agent_index = bridge.register_session(sid, body)
    elif event == "SessionEnd":
        state = "off"
        bridge.release_session(sid)
    elif event in ("UserPromptSubmit", "PreToolUse"):
        state = "thinking"
        bridge.notify_session(sid, state, family=family)
        agent_index = bridge.sessions.get(sid)
    elif event == "PostToolUse":
        if family == "codex":
            bridge.remove_observed_input(sid, body.get("tool_use_id"))
        state = "thinking"
        bridge.notify_session(sid, state, family=family)
        agent_index = bridge.sessions.get(sid)
    elif event == "PermissionRequest":
        if family == "codex":
            bridge.add_observed_input(sid, body.get("tool_use_id"))
        state = "input"
        bridge.notify_session(sid, state, family=family)
        agent_index = bridge.sessions.get(sid)
    elif event == "StopFailure":
        # ターン異常終了時は宙吊りの同一セッション承認を先に fail-close する。
        bridge._deny_pending_for_session(sid)
        state = "error"
        bridge.notify_session(sid, state, family=family)
        agent_index = bridge.sessions.get(sid)
    elif event == "PostToolUseFailure":
        state = "error"
        bridge.notify_session(sid, state, family=family)
        agent_index = bridge.sessions.get(sid)
    elif event == "Notification":
        state = "done" if body.get("notification_type") == "agent_completed" else "input"
        bridge.notify_session(sid, state, family=family)
        agent_index = bridge.sessions.get(sid)
    elif event == "Stop":
        bridge.clear_observed_input(sid)
        state = "done"
        bridge.notify_session(sid, state, family=family)
        agent_index = bridge.sessions.get(sid)

    # 承認保留中の上書き抑止が働いた場合は、実際に維持された状態を記録する
    if state is not None and agent_index is not None and event != "SessionEnd":
        state = bridge.agent_state.get(agent_index, {}).get("state", state)
    if event == "StopFailure":
        detail = body.get("error_type") or body.get("message")
    elif event == "PostToolUseFailure":
        detail = body.get("message") or body.get("error_type")
    elif body.get("tool_input") is not None:
        detail = json.dumps(body.get("tool_input"), ensure_ascii=False)[:200]
    else:
        detail = body.get("message") or body.get("error_type")
    if detail is not None:
        detail = str(detail)[:200]
    bridge.events.append({
        "ts": time.time(), "family": family, "session_id": sid,
        "session_short": sid[:8], "event": event, "state": state,
        "tool_name": body.get("tool_name"), "detail": detail,
        "agent_index": agent_index,
    })
    return web.json_response({"ok": True})


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
    if sys.platform != "darwin":
        # TODO(win32): 前面アプリ検知
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e",
            'tell application "System Events" to name of first application process whose frontmost is true',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except OSError:
        return None
    try:
        out, _ = await proc.communicate()
    except asyncio.CancelledError:
        # asyncio does not terminate subprocesses when their waiter is cancelled.
        # Reap osascript here so loop shutdown cannot leave an orphan behind.
        with suppress(ProcessLookupError):
            proc.kill()
        with suppress(OSError, ProcessLookupError):
            await proc.wait()
        raise
    except OSError:
        return None
    return out.decode().strip() or None


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


def _confirm_mode_candidate(
        candidate: str,
        last_candidate: str | None,
        consecutive_observations: int) -> tuple[str | None, int, str | None]:
    """同じモード候補が連続したときに一度だけ確定する。"""
    if candidate == last_candidate:
        consecutive_observations += 1
    else:
        last_candidate = candidate
        consecutive_observations = 1
    if consecutive_observations >= MODE_HYSTERESIS_OBSERVATIONS:
        # A later manual -> auto transition must begin with a fresh streak even
        # when it occurs entirely between two daemon polls.
        return None, 0, candidate
    return last_candidate, consecutive_observations, None


async def mode_daemon(app):
    """auto モード時のみ前面アプリを監視してモード自動切替（軽量: auto オフなら osascript を叩かない）。
    枠/LED の再アサートは接続時 on_connect に移譲したので、ここでは HID 書き込みをしない。"""
    await asyncio.sleep(2)  # デバイス接続待ち（枠は on_connect で反映）
    poll_sec = bridge.cfg["mode"].get("poll_sec", 3)
    last_candidate = None
    candidate_observations = 0
    while True:
        try:
            if bridge.auto_mode:
                front = await _frontmost_app()
                if front:
                    cand = _mode_from_frontmost(front)
                    if cand in bridge.cfg["mode"].get("enabled", actions_mod.MODE_IDS):
                        if cand == bridge.mode:
                            last_candidate = None
                            candidate_observations = 0
                        else:
                            (last_candidate,
                             candidate_observations,
                             confirmed) = _confirm_mode_candidate(
                                cand, last_candidate, candidate_observations)
                            if confirmed is not None:
                                # 変化時のみ apply_ambient（set_mode 内）
                                bridge.set_mode(confirmed)
                    else:
                        last_candidate = None
                        candidate_observations = 0
                else:
                    last_candidate = None
                    candidate_observations = 0
                await asyncio.sleep(poll_sec)
            else:
                # 手動モード時は前面監視不要 → osascript を叩かず長めに待機（負荷ゼロ）
                last_candidate = None
                candidate_observations = 0
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            break


async def led_animator(app):
    """active(thinking/input)なエージェントキーを 状態色⇄family色 でループ (#6)。
    軽量: アニメ対象が無い時は休止し HID 書き込みをしない。1トグルを1 RPC(複数キー一括)で送る。"""
    while True:
        try:
            active = [(i, s) for i, s in list(bridge.agent_state.items())
                      if s["state"] in ANIMATED_STATES]
            if not active:
                await asyncio.sleep(ANIM_INTERVAL)  # HID 書き込みはしない(メモリ中チェックのみ=軽量)
                continue
            bridge._anim_phase = not bridge._anim_phase
            items = []
            for i, s in active:
                if bridge._anim_phase:
                    color = STATE_COLOR[s["state"]]; b = STATE_BRIGHTNESS[s["state"]]
                else:
                    color = FAMILY_COLOR.get(s["family"], FAMILY_COLOR["claude"]); b = 1.0
                bridge._led_last[i] = (color, round(b, 3))  # dedup と整合
                items.append({"index": i, "color": color, "brightness": b})
            bridge.adapter.set_agents_rgb(items)
            await asyncio.sleep(ANIM_INTERVAL)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(ANIM_INTERVAL)


async def on_startup(app):
    if os.environ.get("CLAUDEMICRO_NO_DEVICE"):
        return
    bridge.loop = asyncio.get_event_loop()
    bridge.adapter.start()
    app["mode_task"] = asyncio.create_task(mode_daemon(app))
    app["led_task"] = asyncio.create_task(led_animator(app))


def cancel_background_tasks(app) -> list[asyncio.Task]:
    """バックグラウンドタスクのキャンセルを先に発行する。"""
    tasks = [
        task
        for key in ("mode_task", "led_task")
        if (task := app.get(key)) is not None
    ]
    for task in tasks:
        if not task.done():
            task.cancel()
    return tasks


async def on_cleanup(app):
    tasks = cancel_background_tasks(app)
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


def create_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_post("/decision", handle_decision)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/config", handle_get_config)
    app.router.add_put("/api/config", handle_put_config)
    app.router.add_post("/api/learn", handle_learn)
    app.router.add_post("/api/resolve", handle_resolve)
    app.router.add_post("/api/mode", handle_mode)
    app.router.add_post("/api/event", handle_event)
    app.router.add_get("/api/actions", handle_actions)
    app.router.add_get("/", handle_index)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)
