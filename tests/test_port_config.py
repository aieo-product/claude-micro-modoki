"""CLAUDEMICRO_PORT の尊重 (#74) のテスト。"""

import importlib
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request
from unittest import mock

import codex_hook_client
import hook_client
# server.main は config 読込をパッチ済みの test_events 経由で import する
from tests.test_events import _can_bind_loopback, server_main

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BridgeUrlTests(unittest.TestCase):
    """hook クライアント側: 不正値は既定へ落とし、フックを止めない。"""

    def _assert_follows_env(self, module):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(module._bridge_url(), "http://127.0.0.1:35703")
        for valid in ("45703", "1", "65535"):
            with self.subTest(valid=valid), \
                    mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": valid}):
                self.assertEqual(
                    module._bridge_url(), f"http://127.0.0.1:{valid}")
        # 空白のみは未設定扱い (ログも出さない)
        with mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": "  "}), \
                mock.patch.object(module, "log") as log_fn:
            self.assertEqual(module._bridge_url(), "http://127.0.0.1:35703")
        log_fn.assert_not_called()
        # 不正値は既定へ落とし、ログで可視化する (0 は listen 専用なので client では不正)
        for bad in ("abc", "-1", "0", "65536"):
            with self.subTest(bad=bad), \
                    mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": bad}), \
                    mock.patch.object(module, "log") as log_fn:
                self.assertEqual(module._bridge_url(), "http://127.0.0.1:35703")
                log_fn.assert_called_once()

    def test_claude_client_follows_port_env(self):
        self._assert_follows_env(hook_client)

    def test_codex_client_follows_port_env(self):
        self._assert_follows_env(codex_hook_client)

    def test_bridge_constant_reflects_env_at_import(self):
        """モジュール定数 BRIDGE 自体が import 時の環境変数を反映する。"""
        try:
            with mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": "45703"}):
                importlib.reload(hook_client)
                importlib.reload(codex_hook_client)
                self.assertEqual(hook_client.BRIDGE, "http://127.0.0.1:45703")
                self.assertEqual(
                    codex_hook_client.BRIDGE, "http://127.0.0.1:45703")
        finally:
            # patch.dict 解除後の素の環境で再読込し、元の状態へ戻す
            importlib.reload(hook_client)
            importlib.reload(codex_hook_client)


class ServePortTests(unittest.TestCase):
    """ヘッドレス bridge 側: 不正値は起動エラーで気づかせる。"""

    def test_default_without_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server_main._serve_port(), 35703)

    def test_follows_env(self):
        with mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": "45703"}):
            self.assertEqual(server_main._serve_port(), 45703)

    def test_zero_is_allowed_like_tray_app(self):
        # トレイアプリの --port と同じく 0 (OS 割当) を許容する
        with mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": "0"}):
            self.assertEqual(server_main._serve_port(), 0)

    def test_blank_is_treated_as_unset_like_tray_app(self):
        # app/__main__.py の _requested_port と同じく、空白のみは未設定扱い
        for blank in ("", "  "):
            with self.subTest(blank=blank), \
                    mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": blank}):
                self.assertEqual(server_main._serve_port(), 35703)

    def test_invalid_raises_system_exit(self):
        for bad in ("abc", "-1", "65536"):
            with self.subTest(bad=bad), \
                    mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": bad}):
                with self.assertRaises(SystemExit):
                    server_main._serve_port()


class HeadlessWiringTests(unittest.TestCase):
    """python -m server.main の __main__ 配線が _serve_port を実際に使うことの検証。"""

    def _subprocess_env(self, port_value: str) -> dict:
        env = dict(os.environ)
        env.pop("APPROVAL_BRIDGE_TOKEN", None)  # /api/status を素の 200 で確認する
        env["CLAUDEMICRO_PORT"] = port_value
        env["CLAUDEMICRO_NO_DEVICE"] = "1"
        return env

    def test_invalid_env_fails_startup(self):
        proc = subprocess.run(
            [sys.executable, "-m", "server.main"],
            capture_output=True, text=True, timeout=60,
            env=self._subprocess_env("bogus"), cwd=REPO_DIR)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("invalid CLAUDEMICRO_PORT", proc.stderr)

    def test_env_port_is_actually_bound(self):
        if not _can_bind_loopback():
            self.skipTest("loopback bind が許可されていない環境")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        proc = subprocess.Popen(
            [sys.executable, "-m", "server.main"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=self._subprocess_env(str(port)), cwd=REPO_DIR)
        try:
            status = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with opener.open(
                            f"http://127.0.0.1:{port}/api/status",
                            timeout=1) as response:
                        status = response.status
                        break
                except OSError:
                    time.sleep(0.1)
            self.assertEqual(status, 200)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
