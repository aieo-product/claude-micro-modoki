"""frozen (.app/.exe) 実行時のパス解決と設定コンソール配信のテスト (#37)。

PyInstaller ではモジュールが PYZ 内に入り、__file__ 相対の
console/index.html・config.json を解決できない。console は sys._MEIPASS、
config はユーザー設定ディレクトリへ切り替わることを検証する。
"""

import errno
import json
import os
import socket
import sys
import tempfile
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

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


def _frozen(meipass="/nonexistent/meipass"):
    """sys を PyInstaller 実行相当に見せるパッチ群。"""
    return (
        mock.patch.object(sys, "frozen", True, create=True),
        mock.patch.object(sys, "_MEIPASS", meipass, create=True),
    )


class ConsolePathTests(unittest.TestCase):
    """CONSOLE_PATH の frozen / ソース実行それぞれの解決先。"""

    def test_source_path_resolves_to_repo_console(self):
        # ソース実行では実在する console/index.html を指す (#37 回帰の直接検知)
        path = server_main._console_path()
        self.assertTrue(path.endswith(os.path.join("console", "index.html")))
        self.assertTrue(os.path.isfile(path), f"console が見つからない: {path}")

    def test_frozen_path_uses_meipass(self):
        p1, p2 = _frozen("/tmp/meipass-test")
        with p1, p2:
            self.assertEqual(
                server_main._console_path(),
                os.path.join("/tmp/meipass-test", "console", "index.html"))


class ConfigPathTests(unittest.TestCase):
    """CONFIG_PATH: ソース実行はリポジトリ直下、frozen はユーザー設定ディレクトリ。"""

    def test_source_path_is_repo_root(self):
        expected = os.path.join(
            os.path.dirname(config_mod.__file__), "..", "config.json")
        self.assertEqual(config_mod._default_config_path(), expected)

    def test_frozen_darwin(self):
        p1, p2 = _frozen()
        with p1, p2, mock.patch.object(sys, "platform", "darwin"):
            expected = os.path.join(
                os.path.expanduser("~/Library/Application Support"),
                "ClaudeMicro", "config.json")
            self.assertEqual(config_mod._default_config_path(), expected)

    def test_frozen_win32_uses_appdata(self):
        p1, p2 = _frozen()
        with p1, p2, mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {"APPDATA": "/tmp/appdata"}):
            self.assertEqual(
                config_mod._default_config_path(),
                os.path.join("/tmp/appdata", "ClaudeMicro", "config.json"))

    def test_frozen_linux_uses_xdg(self):
        p1, p2 = _frozen()
        with p1, p2, mock.patch.object(sys, "platform", "linux"), \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg"}):
            self.assertEqual(
                config_mod._default_config_path(),
                os.path.join("/tmp/xdg", "ClaudeMicro", "config.json"))

    def test_save_creates_missing_parent_dir(self):
        # frozen 初回保存相当: 親ディレクトリが無くても保存できる
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ClaudeMicro", "config.json")
            with mock.patch.object(config_mod, "CONFIG_PATH", path):
                config_mod.save({"brightness": 55})
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["brightness"], 55)


class ConsoleRouteTests(unittest.IsolatedAsyncioTestCase):
    """GET / が設定コンソールを配信する (#37 が流出した経路の常設テスト)。"""

    @unittest.skipUnless(
        _can_bind_loopback(), "loopback bind 不可環境では HTTP 経由の検証を行えない")
    async def test_get_root_serves_console(self):
        env_patch = mock.patch.dict(os.environ, {"CLAUDEMICRO_NO_DEVICE": "1"})
        token_patch = mock.patch.object(server_main, "TOKEN", "")
        with env_patch, token_patch:
            app = server_main.create_app()
            server = TestServer(app, socket_factory=_make_test_socket)
            client = TestClient(server)
            await client.start_server()
            try:
                resp = await client.get("/")
                self.assertEqual(resp.status, 200)
                body = await resp.text()
                self.assertIn("Claude Micro 設定", body)
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
