"""CLAUDEMICRO_PORT の尊重 (#74) のテスト。"""

import importlib
import os
import unittest
from unittest import mock

import codex_hook_client
import hook_client
# server.main は config 読込をパッチ済みの test_events 経由で import する
from tests.test_events import server_main


class BridgeUrlTests(unittest.TestCase):
    """hook クライアント側: 不正値は既定へ落とし、フックを止めない。"""

    def _assert_follows_env(self, module):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(module._bridge_url(), "http://127.0.0.1:35703")
        with mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": "45703"}):
            self.assertEqual(module._bridge_url(), "http://127.0.0.1:45703")
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

    def test_invalid_raises_system_exit(self):
        for bad in ("abc", "-1", "65536"):
            with self.subTest(bad=bad), \
                    mock.patch.dict(os.environ, {"CLAUDEMICRO_PORT": bad}):
                with self.assertRaises(SystemExit):
                    server_main._serve_port()
