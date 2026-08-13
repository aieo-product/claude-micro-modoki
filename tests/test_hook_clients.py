"""Hook クライアントの軽量・非干渉性テスト。"""

import io
import json
import os
import tempfile
import unittest
from unittest import mock

import codex_hook_client
import hook_client


class _Response:
    def __init__(self, payload=None):
        self.payload = {} if payload is None else payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class HookClientTests(unittest.TestCase):
    def run_claude_main(self, data, env):
        stdin = io.StringIO(json.dumps(data))
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(hook_client.sys, "stdin", stdin), \
                mock.patch.object(hook_client.sys, "stdout", stdout):
            result = hook_client.main()
        return result, stdout.getvalue()

    def test_claude_default_gates_bash_through_decision(self):
        """未設定時のデフォルトには Bash が含まれ、承認ゲートへ送る。"""
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pwd"},
        }
        response = _Response({"result": "accept"})
        with mock.patch.object(hook_client, "post", return_value=response) as post:
            result, stdout = self.run_claude_main(data, {})

        self.assertEqual(result, 0)
        post.assert_called_once_with("/decision", data, hook_client.DECISION_TIMEOUT)
        self.assertIn('"permissionDecision": "allow"', stdout)

    def test_claude_default_skips_read_without_output_or_side_effects(self):
        """未設定時の Read は HTTP・ログ・標準出力のいずれも発生させない。"""
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/example"},
        }
        with mock.patch.object(hook_client, "post") as post, \
                mock.patch.object(hook_client, "log") as log:
            result, stdout = self.run_claude_main(data, {})

        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        post.assert_not_called()
        log.assert_not_called()

    def test_claude_wildcard_env_gates_read(self):
        """'*' を明示すると Read も承認ゲートへ送る。"""
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/example"},
        }
        response = _Response({"result": "accept"})
        env = {"CLAUDEMICRO_GATED_TOOLS": "*"}
        with mock.patch.object(hook_client, "post", return_value=response) as post:
            result, stdout = self.run_claude_main(data, env)

        self.assertEqual(result, 0)
        post.assert_called_once_with("/decision", data, hook_client.DECISION_TIMEOUT)
        self.assertIn('"permissionDecision": "allow"', stdout)

    def test_claude_named_and_prefix_patterns_gate_only_matches(self):
        """カンマ区切りの完全一致・末尾 '*' prefix を解釈する。"""
        env = {"CLAUDEMICRO_GATED_TOOLS": "Bash, mcp__*"}
        gated = {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__foo",
            "tool_input": {},
        }
        response = _Response({"result": "accept"})
        with mock.patch.object(hook_client, "post", return_value=response) as post:
            result, stdout = self.run_claude_main(gated, env)

        self.assertEqual(result, 0)
        post.assert_called_once_with("/decision", gated, hook_client.DECISION_TIMEOUT)
        self.assertIn('"permissionDecision": "allow"', stdout)

        ungated = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/example"},
        }
        with mock.patch.object(hook_client, "post") as post, \
                mock.patch.object(hook_client, "log") as log:
            result, stdout = self.run_claude_main(ungated, env)

        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        post.assert_not_called()
        log.assert_not_called()

    def test_claude_empty_env_uses_default_gating(self):
        """空文字は「無効化」ではなく未設定時と同じデフォルトとして扱う。"""
        env = {"CLAUDEMICRO_GATED_TOOLS": ""}
        bash = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pwd"},
        }
        response = _Response({"result": "accept"})
        with mock.patch.object(hook_client, "post", return_value=response) as post:
            result, stdout = self.run_claude_main(bash, env)

        self.assertEqual(result, 0)
        post.assert_called_once_with("/decision", bash, hook_client.DECISION_TIMEOUT)
        self.assertIn('"permissionDecision": "allow"', stdout)

        read = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/example"},
        }
        with mock.patch.object(hook_client, "post") as post, \
                mock.patch.object(hook_client, "log") as log:
            result, stdout = self.run_claude_main(read, env)

        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        post.assert_not_called()
        log.assert_not_called()

    def test_clients_post_through_proxy_free_openers(self):
        """環境 proxy があっても、各クライアントは専用 opener で loopback へ送る。"""
        proxy_env = {
            "http_proxy": "http://192.0.2.1:9",
            "https_proxy": "http://192.0.2.1:9",
            "HTTP_PROXY": "http://192.0.2.1:9",
            "HTTPS_PROXY": "http://192.0.2.1:9",
        }
        response = _Response()
        with mock.patch.dict(os.environ, proxy_env), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError), \
                mock.patch.object(hook_client.opener, "open", return_value=response) as claude_open:
            self.assertIs(hook_client.post("/api/event", {"ok": True}, 1.25), response)
        request = claude_open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:35703/api/event")
        self.assertEqual(claude_open.call_args.kwargs["timeout"], 1.25)

        with mock.patch.dict(os.environ, proxy_env), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError), \
                mock.patch.object(codex_hook_client.opener, "open", return_value=response) as codex_open:
            self.assertIs(codex_hook_client.post_event({"ok": True}), response)
        request = codex_open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:35703/api/event")
        self.assertEqual(codex_open.call_args.kwargs["timeout"], 0.4)

    def test_codex_correlated_tool_events_forward_tool_use_id(self):
        """Codex の承認相関に必要な 3 イベントで ID を落とさない。"""
        for event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
            with self.subTest(event=event):
                captured = []

                def post(payload):
                    captured.append(payload)
                    return _Response()

                with mock.patch.object(codex_hook_client, "post_event", side_effect=post), \
                        mock.patch.object(codex_hook_client, "log"):
                    result = codex_hook_client.handle_event(event, {
                        "session_id": "session-1",
                        "tool_name": "Bash",
                        "tool_use_id": "tool-123",
                    })

                self.assertEqual(result, 0)
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0]["tool_use_id"], "tool-123")
                # POST で JSON 化可能な payload であることも保証する。
                json.dumps(captured[0])

    @unittest.skipIf(codex_hook_client.fcntl is None, "fcntl is unavailable")
    def test_codex_log_skips_silently_when_lock_is_contended(self):
        """ログロック競合は Codex を待たせず、書き込みもしない。"""
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "codexhook.log")
            with mock.patch.object(codex_hook_client, "LOG", path), \
                    mock.patch.object(
                        codex_hook_client.fcntl, "flock",
                        side_effect=BlockingIOError) as flock:
                codex_hook_client.log("must be skipped")

            self.assertEqual(flock.call_count, 1)
            flags = flock.call_args.args[1]
            self.assertEqual(
                flags,
                codex_hook_client.fcntl.LOCK_EX | codex_hook_client.fcntl.LOCK_NB)
            with open(path, encoding="utf-8") as log_file:
                self.assertEqual(log_file.read(), "")


if __name__ == "__main__":
    unittest.main()
