"""エージェント状態イベント取込 API のテスト。"""

import asyncio
import errno
import itertools
import json
import os
import socket
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from server import config as config_mod

# import 時に実 config.json を読まず、テスト用の既定設定で Bridge を生成する。
with mock.patch.object(
        config_mod, "load",
        return_value=config_mod._deep_merge(config_mod.DEFAULT_CONFIG, {})):
    from server import main as server_main


def _can_bind_loopback() -> bool:
    """管理環境が一時ループバックソケットを許可するか一度だけ確認する。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM):
            raise
        return False
    finally:
        probe.close()
    return True


def _make_test_socket(host, port, family):
    """TestServer の bind 失敗時にもソケットを確実に閉じる。"""
    test_socket = socket.socket(family, socket.SOCK_STREAM)
    try:
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        test_socket.bind((host, port))
        return test_socket
    except BaseException:
        test_socket.close()
        raise


class DummyAdapter:
    """HID デバイスへ一切アクセスしないテスト用アダプター。"""

    def __init__(self):
        self.status = {"found": False, "open": False, "error": None, "fw": None}
        self.start_count = 0
        self.agent_rgb_calls = []

    def start(self):
        self.start_count += 1

    def set_ambient_color(self, *args, **kwargs):
        pass

    def set_agent_rgb(self, *args, **kwargs):
        self.agent_rgb_calls.append((args, kwargs))

    def set_agents_rgb(self, *args, **kwargs):
        pass

    def update_timings(self, *args, **kwargs):
        pass


class EventApiTests(unittest.IsolatedAsyncioTestCase):
    """デバイスなしでイベントから状態への遷移を検証する。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 利用可能な通常環境では TestServer/TestClient を常に優先する。
        cls._loopback_available = _can_bind_loopback()

    def setUp(self):
        # aiohttp の startup より前に、デバイスを起動しない環境を確定する。
        self._env_patch = mock.patch.dict(
            os.environ, {"CLAUDEMICRO_NO_DEVICE": "1"})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

        # TOKEN は import 時に確定するため、実行元の環境に左右されないようにする。
        self._token_patch = mock.patch.object(server_main, "TOKEN", "")
        self._token_patch.start()
        self.addCleanup(self._token_patch.stop)

        self._old_adapter = server_main.bridge.adapter
        self.adapter = DummyAdapter()
        server_main.bridge.adapter = self.adapter
        self.addCleanup(self._restore_adapter)

        # gitignore の実設定に依存せず、既定の短いテスト可能な設定へ戻す。
        self._old_cfg = server_main.bridge.cfg
        self._old_mode = server_main.bridge.mode
        self._old_auto_mode = server_main.bridge.auto_mode
        server_main.bridge.cfg = config_mod._deep_merge(
            config_mod.DEFAULT_CONFIG, {"approval_timeout_sec": 2})
        server_main.bridge.mode = server_main.bridge.cfg["mode"]["current"]
        server_main.bridge.auto_mode = server_main.bridge.cfg["mode"]["auto"]
        self.addCleanup(self._restore_config)

        self._reset_bridge()
        self.addCleanup(self._reset_bridge)

    async def asyncSetUp(self):
        self.app = server_main.create_app()
        self.server = None
        self.client = None
        self._in_process_started = False
        self.addAsyncCleanup(self._close_test_transport)

        if self._loopback_available:
            self.server = TestServer(
                self.app, socket_factory=_make_test_socket)
            self.client = TestClient(self.server)
            await self.client.start_server()
        else:
            # bind 禁止環境でも、実アプリのルート・middleware・startup を通す。
            self.app.freeze()
            # startup が途中で失敗しても cleanup シグナルまで到達させる。
            self._in_process_started = True
            await self.app.startup()

        # テスト用フックが有効なら、ダミーであっても start は呼ばれない。
        self.assertEqual(self.adapter.start_count, 0)

    async def _close_test_transport(self):
        """ネットワーク経路とインプロセス経路を対称に終了する。"""
        if self.client is not None:
            await self.client.close()
            self.client = None
        elif self._in_process_started:
            await self.app.shutdown()
            await self.app.cleanup()
            self._in_process_started = False

    def _restore_adapter(self):
        server_main.bridge.adapter = self._old_adapter

    def _restore_config(self):
        server_main.bridge.cfg = self._old_cfg
        server_main.bridge.mode = self._old_mode
        server_main.bridge.auto_mode = self._old_auto_mode

    def _reset_bridge(self):
        """テスト間で共有 Bridge の状態を残さない。"""
        for request in server_main.bridge.pending.values():
            future = request.get("future")
            if isinstance(future, asyncio.Future) and not future.done():
                future.cancel()
        server_main.bridge.pending.clear()
        server_main.bridge.sessions.clear()
        server_main.bridge.session_info.clear()
        server_main.bridge.observed_input.clear()
        server_main.bridge.agent_state.clear()
        server_main.bridge.events.clear()
        server_main.bridge._led_last.clear()
        server_main.bridge.selected_agent = None
        server_main.bridge._anim_phase = False
        server_main.bridge.last_raw_key = None
        server_main.bridge._req_ids = itertools.count(1)
        learn_future = server_main.bridge._learn_future
        if isinstance(learn_future, asyncio.Future) and not learn_future.done():
            learn_future.cancel()
        server_main.bridge._learn_future = None
        server_main.bridge.loop = None

    async def _request_json(self, method, path, payload=None):
        """同じ HTTP 契約を TestClient または app._handle で実行する。"""
        if self.client is not None:
            async with self.client.request(method, path, json=payload) as response:
                return response.status, await response.json()

        headers = {}
        body = b""
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = make_mocked_request(
            method, path, headers=headers, app=self.app)
        request._read_bytes = body
        response = await self.app._handle(request)
        return response.status, json.loads(response.text)

    async def _post_event(self, **payload):
        status, body = await self._request_json("POST", "/api/event", payload)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        return body

    async def _get_status(self):
        status, body = await self._request_json("GET", "/api/status")
        self.assertEqual(status, 200, body)
        return body

    async def test_session_start_claude_registers_idle_state(self):
        """1. Claude の SessionStart は登録して idle にする。"""
        sid = "claude-session-01"

        await self._post_event(
            event="SessionStart", family="claude", session_id=sid,
            cwd="/tmp/project")

        self.assertIn(sid, server_main.bridge.sessions)
        index = server_main.bridge.sessions[sid]
        self.assertEqual(
            server_main.bridge.agent_state[index],
            {"state": "idle", "family": "claude"})

    async def test_session_info_is_bounded_during_session_churn(self):
        """FIX-4: SessionEnd 欠落が続いても status 用メタ情報を固定上限に保つ。"""
        with mock.patch("builtins.print"):
            for number in range(100):
                await self._post_event(
                    event="SessionStart", family="claude",
                    session_id=f"churn-{number}", cwd=f"/tmp/{number}")

        self.assertLessEqual(
            len(server_main.bridge.sessions), server_main.AGENT_KEY_COUNT)
        self.assertLessEqual(
            len(server_main.bridge.session_info), server_main.SESSION_INFO_LIMIT)
        self.assertTrue(
            set(server_main.bridge.sessions).issubset(server_main.bridge.session_info))
        self.assertNotIn("churn-0", server_main.bridge.session_info)
        self.assertIn("churn-99", server_main.bridge.session_info)

    async def test_user_prompt_submit_changes_state_to_thinking(self):
        """2. UserPromptSubmit は thinking に遷移する。"""
        sid = "claude-session-02"
        await self._post_event(
            event="SessionStart", family="claude", session_id=sid)

        await self._post_event(
            event="UserPromptSubmit", family="claude", session_id=sid)

        index = server_main.bridge.sessions[sid]
        self.assertEqual(
            server_main.bridge.agent_state[index]["state"], "thinking")

    async def test_codex_permission_request_records_tool_event(self):
        """3. Codex の承認要求は input とツール情報を記録する。"""
        sid = "codex-session-03"
        await self._post_event(
            event="SessionStart", family="codex", session_id=sid)

        await self._post_event(
            event="PermissionRequest", family="codex", session_id=sid,
            tool_name="Bash", tool_input={"command": "pwd"},
            tool_use_id="tool-03")

        index = server_main.bridge.sessions[sid]
        self.assertEqual(
            server_main.bridge.agent_state[index],
            {"state": "input", "family": "codex"})
        self.assertFalse(server_main.bridge.pending)  # 観測専用で承認をブロックしない
        self.assertEqual(
            server_main.bridge.observed_input[sid], {"tool-03"})
        event = server_main.bridge.events[-1]
        self.assertEqual(event["event"], "PermissionRequest")
        self.assertEqual(event["family"], "codex")
        self.assertEqual(event["tool_name"], "Bash")

    async def test_codex_permission_request_correlates_tool_use_id(self):
        """FIX-6: 別ツール B の完了では承認 A を解除せず、A の完了だけで解除する。"""
        sid = "codex-correlation"
        await self._post_event(
            event="SessionStart", family="codex", session_id=sid)
        index = server_main.bridge.sessions[sid]

        await self._post_event(
            event="PermissionRequest", family="codex", session_id=sid,
            tool_name="Bash", tool_use_id="A")
        await self._post_event(
            event="PostToolUse", family="codex", session_id=sid,
            tool_name="Bash", tool_use_id="B")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "input")
        self.assertEqual(server_main.bridge.events[-1]["state"], "input")
        self.assertEqual(server_main.bridge.observed_input[sid], {"A"})

        await self._post_event(
            event="PostToolUse", family="codex", session_id=sid,
            tool_name="Bash", tool_use_id="A")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "thinking")
        self.assertEqual(server_main.bridge.events[-1]["state"], "thinking")
        self.assertNotIn(sid, server_main.bridge.observed_input)

    async def test_observed_input_dummy_and_lifecycle_cleanup(self):
        """FIX-6: ID 欠落時はダミー相関を使い、Stop/SessionEnd で必ず解放する。"""
        sid = "codex-dummy"
        await self._post_event(
            event="PermissionRequest", family="codex", session_id=sid)
        await self._post_event(
            event="PermissionRequest", family="codex", session_id=sid)
        self.assertEqual(
            server_main.bridge.observed_input[sid],
            {server_main.OBSERVED_INPUT_DUMMY_ID})

        await self._post_event(
            event="Notification", family="codex", session_id=sid,
            notification_type="agent_completed")
        index = server_main.bridge.sessions[sid]
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "input")

        await self._post_event(
            event="PostToolUse", family="codex", session_id=sid,
            tool_use_id="unrelated")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "input")
        await self._post_event(
            event="PostToolUse", family="codex", session_id=sid)
        self.assertNotIn(sid, server_main.bridge.observed_input)
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "thinking")

        await self._post_event(
            event="PermissionRequest", family="codex", session_id=sid)
        await self._post_event(event="Stop", family="codex", session_id=sid)
        self.assertNotIn(sid, server_main.bridge.observed_input)
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "done")

        await self._post_event(
            event="PermissionRequest", family="codex", session_id=sid,
            tool_use_id="last")
        await self._post_event(
            event="PostToolUseFailure", family="codex", session_id=sid,
            tool_use_id="last", message="failed")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "error")
        await self._post_event(
            event="SessionEnd", family="codex", session_id=sid)
        self.assertNotIn(sid, server_main.bridge.observed_input)

    async def test_observed_input_tracker_is_bounded(self):
        """FIX-6: 観測承認は session と tool ID の両方で常駐量を制限する。"""
        self.assertEqual(server_main.OBSERVED_INPUT_SESSION_LIMIT, 32)
        self.assertEqual(server_main.OBSERVED_INPUT_ID_LIMIT, 8)
        for number in range(server_main.OBSERVED_INPUT_SESSION_LIMIT + 5):
            await self._post_event(
                event="PermissionRequest", family="codex",
                session_id=f"observed-{number}", tool_use_id="initial")
        self.assertEqual(
            len(server_main.bridge.observed_input),
            server_main.OBSERVED_INPUT_SESSION_LIMIT)

        sid = f"observed-{server_main.OBSERVED_INPUT_SESSION_LIMIT + 4}"
        for number in range(server_main.OBSERVED_INPUT_ID_LIMIT + 5):
            await self._post_event(
                event="PermissionRequest", family="codex", session_id=sid,
                tool_use_id=f"tool-{number}")
        self.assertEqual(
            len(server_main.bridge.observed_input[sid]),
            server_main.OBSERVED_INPUT_ID_LIMIT)
        self.assertIn("tool-12", server_main.bridge.observed_input[sid])

    async def test_stop_failure_changes_state_to_error(self):
        """4. StopFailure は error に遷移する。"""
        sid = "claude-session-04"
        await self._post_event(
            event="SessionStart", family="claude", session_id=sid)

        await self._post_event(
            event="StopFailure", family="claude", session_id=sid,
            error_type="runtime_error", message="agent failed")

        index = server_main.bridge.sessions[sid]
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "error")

    async def test_stop_changes_state_to_done(self):
        """5. Stop は done に遷移する。"""
        sid = "claude-session-05"
        await self._post_event(
            event="SessionStart", family="claude", session_id=sid)

        await self._post_event(
            event="Stop", family="claude", session_id=sid)

        index = server_main.bridge.sessions[sid]
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "done")

    async def test_notification_type_selects_input_or_done(self):
        """6. Notification は種別に応じて input/done を選ぶ。"""
        sid = "claude-session-06"
        await self._post_event(
            event="SessionStart", family="claude", session_id=sid)
        index = server_main.bridge.sessions[sid]

        await self._post_event(
            event="Notification", family="claude", session_id=sid,
            notification_type="idle_prompt")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "input")

        await self._post_event(
            event="Notification", family="claude", session_id=sid,
            notification_type="agent_completed")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "done")

    async def test_session_end_releases_agent_state(self):
        """7. SessionEnd は割当と agent_state を解放する。"""
        sid = "claude-session-07"
        await self._post_event(
            event="SessionStart", family="claude", session_id=sid)
        index = server_main.bridge.sessions[sid]

        await self._post_event(
            event="SessionEnd", family="claude", session_id=sid)

        self.assertNotIn(sid, server_main.bridge.sessions)
        self.assertNotIn(sid, server_main.bridge.session_info)
        self.assertNotIn(index, server_main.bridge.agent_state)
        self.assertEqual(server_main.bridge.events[-1]["agent_index"], index)
        self.assertEqual(server_main.bridge.events[-1]["state"], "off")

    async def test_unknown_session_is_registered_automatically(self):
        """8. 未知セッションのイベントも自動登録する。"""
        sid = "unknown-session-08"

        await self._post_event(
            event="UserPromptSubmit", family="codex", session_id=sid)

        self.assertIn(sid, server_main.bridge.sessions)
        index = server_main.bridge.sessions[sid]
        self.assertEqual(
            server_main.bridge.agent_state[index],
            {"state": "thinking", "family": "codex"})

    async def test_status_returns_newest_events_and_agent_family(self):
        """9. status は新しい順の events と family 付き状態を返す。"""
        sid = "codex-session-09"
        await self._post_event(
            event="SessionStart", family="codex", session_id=sid)
        await self._post_event(
            event="UserPromptSubmit", family="codex", session_id=sid)

        status = await self._get_status()

        self.assertEqual(server_main.bridge.events.maxlen, 100)
        self.assertGreaterEqual(len(status["events"]), 2)
        self.assertEqual(
            [event["event"] for event in status["events"][:2]],
            ["UserPromptSubmit", "SessionStart"])
        index = server_main.bridge.sessions[sid]
        self.assertEqual(status["agent_state"][str(index)]["state"], "thinking")
        self.assertEqual(status["agent_state"][str(index)]["family"], "codex")

    async def test_family_omission_keeps_notification_and_stop_compatible(self):
        """10. family 省略時も従来の Notification/Stop を維持する。"""
        sid = "legacy-session-10"
        await self._post_event(event="SessionStart", session_id=sid)
        index = server_main.bridge.sessions[sid]

        await self._post_event(event="Notification", session_id=sid)
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "input")
        self.assertEqual(server_main.bridge.agent_state[index]["family"], "claude")

        await self._post_event(event="Stop", session_id=sid)
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "done")
        self.assertEqual(server_main.bridge.agent_state[index]["family"], "claude")

    async def test_tool_events_and_unknown_event_keep_expected_states(self):
        """補足: ツールイベント全種と未知イベントの監視状態を検証する。"""
        sid = "codex-tool-events"

        await self._post_event(
            event="PreToolUse", family="codex", session_id=sid,
            tool_name="Bash", tool_input={"command": "pwd"})
        index = server_main.bridge.sessions[sid]
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "thinking")

        await self._post_event(
            event="PostToolUse", family="codex", session_id=sid,
            tool_name="Bash", tool_input={"command": "pwd"})
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "thinking")

        await self._post_event(
            event="PostToolUseFailure", family="codex", session_id=sid,
            tool_name="Bash", message="command failed")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "error")

        await self._post_event(
            event="UnknownEvent", family="codex", session_id=sid)
        self.assertIsNone(server_main.bridge.events[-1]["state"])

    async def test_pending_approval_suppresses_only_benign_events(self):
        """補足: 承認待ちは良性遷移だけを抑止し、error は優先する。"""
        sid = "pending-priority"
        await self._post_event(
            event="SessionStart", family="claude", session_id=sid)
        index = server_main.bridge.sessions[sid]
        future = asyncio.get_running_loop().create_future()
        server_main.bridge.pending[99] = {
            "id": 99, "session_id": sid, "tool_name": "Bash", "detail": "{}",
            "created": 0.0, "future": future, "agent_index": index,
        }
        server_main.bridge.set_agent_state(index, "input", family="claude")

        await self._post_event(
            event="PostToolUse", family="codex", session_id=sid)
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "input")
        self.assertEqual(server_main.bridge.agent_state[index]["family"], "codex")
        self.assertEqual(server_main.bridge.events[-1]["state"], "input")

        await self._post_event(
            event="Stop", family="claude", session_id=sid)
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "input")
        self.assertEqual(server_main.bridge.events[-1]["state"], "input")

        await self._post_event(
            event="StopFailure", family="claude", session_id=sid,
            error_type="overloaded")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "error")
        self.assertEqual(server_main.bridge.events[-1]["state"], "error")
        self.assertEqual(server_main.bridge.events[-1]["detail"], "overloaded")
        self.assertEqual(future.result(), "deny")

    async def test_post_tool_use_failure_overrides_pending_input(self):
        """FIX-5: ツール失敗の error も未解決承認の input より優先する。"""
        sid = "pending-tool-failure"
        await self._post_event(
            event="SessionStart", family="claude", session_id=sid)
        index = server_main.bridge.sessions[sid]
        future = asyncio.get_running_loop().create_future()
        server_main.bridge.pending[98] = {
            "id": 98, "session_id": sid, "tool_name": "Bash", "detail": "{}",
            "created": 0.0, "future": future, "agent_index": index,
            "public_agent_index": index,
        }
        server_main.bridge.set_agent_state(index, "input", family="claude")

        await self._post_event(
            event="PostToolUseFailure", family="claude", session_id=sid,
            tool_name="Bash", message="command failed")

        self.assertEqual(server_main.bridge.agent_state[index]["state"], "error")
        self.assertEqual(server_main.bridge.events[-1]["state"], "error")
        self.assertFalse(future.done())  # StopFailure と違い、個別ツール失敗は承認を解決しない

        await self._post_event(
            event="PostToolUse", family="claude", session_id=sid,
            tool_name="Read")
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "error")
        self.assertEqual(server_main.bridge.events[-1]["state"], "error")

    async def test_codex_error_events_reach_error_state(self):
        """#75: bridge は family=codex のエラー系イベントでも error LED に遷移できる。
        codex hooks は 0.144.1/0.147.0 実測でエラー系未発火のため現状は将来互換の担保
        (発火し次第 client が素通しし、この経路で赤が点く)。"""
        for event in ("PostToolUseFailure", "StopFailure"):
            with self.subTest(event=event):
                sid = f"codex-error-{event}"
                await self._post_event(
                    event="SessionStart", family="codex", session_id=sid)
                index = server_main.bridge.sessions[sid]

                await self._post_event(
                    event=event, family="codex", session_id=sid,
                    tool_name="Bash", message="tool failed")

                self.assertEqual(
                    server_main.bridge.agent_state[index],
                    {"state": "error", "family": "codex"})

    async def test_decision_records_event_and_preserves_approval_flow(self):
        """補足: /decision は監視記録を追加し、既存の承認結果を維持する。"""
        sid = "decision-session"
        request_task = asyncio.create_task(self._request_json(
            "POST", "/decision", {
                "hook_event_name": "PreToolUse", "session_id": sid,
                "tool_name": "Bash", "tool_input": {"command": "pwd"},
            }))
        for _ in range(20):
            if server_main.bridge.pending:
                break
            await asyncio.sleep(0)
        self.assertTrue(server_main.bridge.pending)
        request_id = next(iter(server_main.bridge.pending))
        event = server_main.bridge.events[-1]
        self.assertEqual(event["event"], "PreToolUse")
        self.assertEqual(event["state"], "input")
        self.assertEqual(event["tool_name"], "Bash")

        status, resolved = await self._request_json(
            "POST", "/api/resolve", {"id": request_id, "result": "accept"})
        self.assertEqual(status, 200, resolved)
        self.assertTrue(resolved["ok"])
        status, result = await request_task
        self.assertEqual(status, 200, result)
        self.assertEqual(result["result"], "accept")
        self.assertFalse(server_main.bridge.pending)
        index = server_main.bridge.sessions[sid]
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "thinking")

    async def test_decision_cleanup_preserves_terminal_error(self):
        """FIX-5: StopFailure の deny 後に /decision finally が error を消さない。"""
        sid = "decision-stop-failure"
        request_task = asyncio.create_task(self._request_json(
            "POST", "/decision", {
                "hook_event_name": "PreToolUse", "session_id": sid,
                "tool_name": "Bash", "tool_input": {"command": "false"},
            }))
        for _ in range(20):
            if server_main.bridge.pending:
                break
            await asyncio.sleep(0)
        self.assertTrue(server_main.bridge.pending)
        index = server_main.bridge.sessions[sid]

        await self._post_event(
            event="StopFailure", family="claude", session_id=sid,
            error_type="runtime_error")
        status, result = await request_task

        self.assertEqual(status, 200, result)
        self.assertEqual(result["result"], "deny")
        self.assertFalse(server_main.bridge.pending)
        self.assertEqual(server_main.bridge.agent_state[index]["state"], "error")

    async def test_event_ring_and_status_limits(self):
        """補足: 監視リングは100件、status は新着50件に制限する。"""
        sid = "ring-session"
        for number in range(105):
            await self._post_event(
                event="UserPromptSubmit", family="codex", session_id=sid,
                message=str(number))

        self.assertEqual(len(server_main.bridge.events), 100)
        status = await self._get_status()
        self.assertEqual(len(status["events"]), 50)
        self.assertEqual(status["events"][0]["detail"], "104")
        self.assertEqual(status["events"][-1]["detail"], "55")

    async def test_identical_thinking_does_not_write_during_family_phase(self):
        """FIX-8: 同一論理状態の再送は animator の現在相を上書きしない。"""
        sid = "logical-dedup"
        await self._post_event(
            event="PreToolUse", family="codex", session_id=sid,
            tool_name="Bash", tool_use_id="dedup-tool")
        index = server_main.bridge.sessions[sid]
        family_phase = (server_main.FAMILY_COLOR["codex"], 1.0)
        server_main.bridge._led_last[index] = family_phase
        self.adapter.agent_rgb_calls.clear()

        await self._post_event(
            event="PostToolUse", family="codex", session_id=sid,
            tool_name="Bash", tool_use_id="dedup-tool")

        self.assertEqual(self.adapter.agent_rgb_calls, [])
        self.assertEqual(server_main.bridge._led_last[index], family_phase)
        self.assertEqual(
            server_main.bridge.agent_state[index],
            {"state": "thinking", "family": "codex"})

    async def test_ended_session_pending_does_not_block_reused_key(self):
        """補足: 終了済みセッションの保留は再利用キーの状態を妨げない。"""
        old_sid = "ended-pending"
        await self._post_event(
            event="SessionStart", family="claude", session_id=old_sid)
        index = server_main.bridge.sessions[old_sid]
        future = asyncio.get_running_loop().create_future()
        server_main.bridge.pending[88] = {
            "id": 88, "session_id": old_sid, "tool_name": "Bash", "detail": "{}",
            "created": 0.0, "future": future, "agent_index": index,
        }
        server_main.bridge.set_agent_state(index, "input", family="claude")

        await self._post_event(
            event="SessionEnd", family="claude", session_id=old_sid)
        self.assertIsNone(server_main.bridge.pending[88]["agent_index"])
        self.assertEqual(future.result(), "deny")
        status = await self._get_status()
        public_request = next(
            request for request in status["pending"] if request["id"] == 88)
        self.assertIsInstance(public_request["agent_index"], int)
        self.assertEqual(public_request["agent_index"], index)
        await self._post_event(
            event="UserPromptSubmit", family="codex", session_id="new-session")

        self.assertEqual(server_main.bridge.sessions["new-session"], index)
        self.assertEqual(
            server_main.bridge.agent_state[index],
            {"state": "thinking", "family": "codex"})

    async def test_full_busy_lru_detaches_evicted_pending_owner(self):
        """補足: 全キー多忙時の強制再利用でも古い承認を新セッションへ紐付けない。"""
        pending_by_session = {}
        for number in range(server_main.AGENT_KEY_COUNT):
            sid = f"busy-{number}"
            await self._post_event(
                event="SessionStart", family="claude", session_id=sid)
            index = server_main.bridge.sessions[sid]
            future = asyncio.get_running_loop().create_future()
            request_id = 200 + number
            server_main.bridge.pending[request_id] = {
                "id": request_id, "session_id": sid, "tool_name": "Bash",
                "detail": "{}", "created": float(number), "future": future,
                "agent_index": index,
            }
            pending_by_session[sid] = server_main.bridge.pending[request_id]

        await self._post_event(
            event="UserPromptSubmit", family="codex", session_id="seventh-session")

        reused_index = server_main.bridge.sessions["seventh-session"]
        self.assertIsNone(pending_by_session["busy-0"]["agent_index"])
        self.assertEqual(
            pending_by_session["busy-0"]["future"].result(), "deny")
        self.assertFalse(pending_by_session["busy-1"]["future"].done())
        status = await self._get_status()
        public_request = next(
            request for request in status["pending"] if request["id"] == 200)
        self.assertIsInstance(public_request["agent_index"], int)
        self.assertEqual(public_request["agent_index"], reused_index)
        self.assertEqual(
            server_main.bridge.agent_state[reused_index],
            {"state": "thinking", "family": "codex"})

    async def test_session_end_denies_already_detached_pending_by_session_id(self):
        """FIX-7: mapping/index が消えた後でも SessionEnd は session_id で deny する。"""
        sid = "already-detached"
        future = asyncio.get_running_loop().create_future()
        server_main.bridge.pending[300] = {
            "id": 300, "session_id": sid, "tool_name": "Bash", "detail": "{}",
            "created": 0.0, "future": future, "agent_index": None,
            "public_agent_index": 3,
        }

        await self._post_event(
            event="SessionEnd", family="claude", session_id=sid)

        self.assertEqual(future.result(), "deny")
        self.assertIsNone(server_main.bridge.pending[300]["agent_index"])
        status = await self._get_status()
        public_request = next(
            request for request in status["pending"] if request["id"] == 300)
        self.assertEqual(public_request["agent_index"], 3)


if __name__ == "__main__":
    unittest.main()
