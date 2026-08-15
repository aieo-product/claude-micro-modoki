"""mode.enabled の尊重と「効かない設定」の整合 (#77) のテスト。"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from aiohttp.test_utils import make_mocked_request

from server import config as config_mod
from tests.test_events import DummyAdapter, server_main


def _default_cfg() -> dict:
    return config_mod._deep_merge(config_mod.DEFAULT_CONFIG, {})


class BridgeModeTestBase(unittest.IsolatedAsyncioTestCase):
    """共有 Bridge のモード関連状態だけを退避して検証する。"""

    def setUp(self):
        bridge = server_main.bridge
        self._saved = (bridge.cfg, bridge.mode, bridge.auto_mode, bridge.adapter)
        bridge.adapter = DummyAdapter()
        bridge.cfg = _default_cfg()
        bridge.mode = "cmux-claude"
        bridge.auto_mode = False
        self.bridge = bridge
        self.addCleanup(self._restore)

    def _restore(self):
        bridge = server_main.bridge
        (bridge.cfg, bridge.mode,
         bridge.auto_mode, bridge.adapter) = self._saved

    @staticmethod
    def _request(payload: dict):
        request = make_mocked_request(
            "POST", "/api/mode",
            headers={"Content-Type": "application/json"})
        request._read_bytes = json.dumps(payload).encode("utf-8")
        return request


class ModeEnabledGateTests(BridgeModeTestBase):
    def test_set_mode_blocked_for_disabled_mode(self):
        self.bridge.cfg["mode"]["enabled"] = ["cmux-claude", "cmux-codex"]
        with mock.patch("builtins.print"):
            self.bridge.set_mode("codex-app")
        self.assertEqual(self.bridge.mode, "cmux-claude")
        with mock.patch("builtins.print"):
            self.bridge.set_mode("cmux-codex")
        self.assertEqual(self.bridge.mode, "cmux-codex")

    def test_manual_toggles_respect_enabled(self):
        """ACT12 tap/double 相当の切替も除外モードに入らない。"""
        self.bridge.cfg["mode"]["enabled"] = ["cmux-claude"]
        with mock.patch("builtins.print"):
            self.bridge._toggle_family()   # -> cmux-codex は除外中
            self.assertEqual(self.bridge.mode, "cmux-claude")
            self.bridge._toggle_context()  # -> claude-app は除外中
            self.assertEqual(self.bridge.mode, "cmux-claude")

        self.bridge.cfg["mode"]["enabled"] = list(
            server_main.actions_mod.MODE_IDS)
        with mock.patch("builtins.print"):
            self.bridge._toggle_family()
        self.assertEqual(self.bridge.mode, "cmux-codex")

    def test_missing_enabled_key_allows_all_modes(self):
        """enabled キーの無い旧 config では全モード許可 (後方互換)。"""
        self.bridge.cfg["mode"].pop("enabled", None)
        with mock.patch("builtins.print"):
            self.bridge.set_mode("codex-app")
        self.assertEqual(self.bridge.mode, "codex-app")

    def test_enabled_is_normalized_when_invalid(self):
        """null・空・未知 id のみの enabled は全モード扱いへ正規化される。"""
        for broken in (None, [], ["bogus"]):
            with self.subTest(broken=broken):
                self.bridge.cfg["mode"]["enabled"] = broken
                self.bridge.mode = "cmux-claude"
                with mock.patch("builtins.print"):
                    self.bridge.set_mode("codex-app")
                self.assertEqual(self.bridge.mode, "codex-app")

    def test_unknown_ids_in_enabled_are_ignored(self):
        """有効 id と未知 id の混在では、有効 id だけが許可対象。"""
        self.bridge.cfg["mode"]["enabled"] = ["cmux-codex", "bogus"]
        with mock.patch("builtins.print"):
            self.bridge.set_mode("codex-app")   # 除外扱い
            self.assertEqual(self.bridge.mode, "cmux-claude")
            self.bridge.set_mode("cmux-codex")  # 許可
        self.assertEqual(self.bridge.mode, "cmux-codex")


class StartupModeTests(unittest.TestCase):
    """起動時に除外モードで立ち上がらない (#77 レビュー対応)。"""

    def test_current_in_enabled_is_kept(self):
        cfg = _default_cfg()
        cfg["mode"]["current"] = "codex-app"
        self.assertEqual(server_main._startup_mode(cfg), "codex-app")

    def test_excluded_current_falls_back_to_first_enabled(self):
        cfg = _default_cfg()
        cfg["mode"]["current"] = "codex-app"
        cfg["mode"]["enabled"] = ["cmux-claude", "cmux-codex"]
        with mock.patch("builtins.print"):
            self.assertEqual(server_main._startup_mode(cfg), "cmux-claude")

    def test_invalid_enabled_keeps_current(self):
        cfg = _default_cfg()
        cfg["mode"]["current"] = "codex-app"
        cfg["mode"]["enabled"] = None
        self.assertEqual(server_main._startup_mode(cfg), "codex-app")


class ModeApiTests(BridgeModeTestBase):
    async def test_api_rejects_disabled_mode_with_400(self):
        self.bridge.cfg["mode"]["enabled"] = ["cmux-claude", "cmux-codex"]
        self.bridge.auto_mode = True
        response = await server_main.handle_mode(self._request({"mode": "codex-app"}))
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.text)["error"], "mode disabled")
        self.assertEqual(self.bridge.mode, "cmux-claude")
        # 拒否時は auto も倒さない
        self.assertTrue(self.bridge.auto_mode)

    async def test_api_switches_enabled_mode(self):
        self.bridge.cfg["mode"]["enabled"] = ["cmux-claude", "cmux-codex"]
        self.bridge.auto_mode = True
        with mock.patch("builtins.print"):
            response = await server_main.handle_mode(
                self._request({"mode": "cmux-codex"}))
        self.assertEqual(response.status, 200)
        body = json.loads(response.text)
        self.assertEqual(body["mode"], "cmux-codex")
        self.assertFalse(body["auto_mode"])


class PutConfigModeTests(BridgeModeTestBase):
    """PUT /api/config での mode.current/auto 編集は再起動なしで反映される。"""

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp(prefix="claudemicro-cfg-")
        self.addCleanup(self._rmtree)
        patcher = mock.patch.object(
            config_mod, "CONFIG_PATH",
            os.path.join(self._tmpdir, "config.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rmtree(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def _put(self, body: dict):
        request = make_mocked_request(
            "PUT", "/api/config",
            headers={"Content-Type": "application/json"})
        request._read_bytes = json.dumps(body).encode("utf-8")
        with mock.patch("builtins.print"):
            return await server_main.handle_put_config(request)

    async def test_mode_current_edit_applies_without_restart(self):
        body = copy.deepcopy(self.bridge.cfg)
        body["mode"]["current"] = "cmux-codex"
        response = await self._put(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.bridge.mode, "cmux-codex")

    async def test_unchanged_roundtrip_does_not_revert_live_mode(self):
        """console の「取得値をそのまま保存」で物理切替済みモードを戻さない。"""
        with mock.patch("builtins.print"):
            self.bridge.set_mode("codex-app")  # 物理キーでの切替を模擬
        body = copy.deepcopy(self.bridge.cfg)  # mode.current は起動値のまま
        await self._put(body)
        self.assertEqual(self.bridge.mode, "codex-app")

    async def test_mode_auto_edit_applies_without_restart(self):
        # 差分検知なので「値を実際に変える」保存だけが live 状態へ反映される
        self.bridge.cfg["mode"]["auto"] = False
        self.assertFalse(self.bridge.auto_mode)
        body = copy.deepcopy(self.bridge.cfg)
        body["mode"]["auto"] = True
        await self._put(body)
        self.assertTrue(self.bridge.auto_mode)

    async def test_disabled_mode_current_edit_saves_but_keeps_live_mode(self):
        """除外 current の保存は許す (console の全文 PUT を壊さない) が live は不変。
        次回起動は _startup_mode が enabled の先頭へフォールバックし、除外モードでは起動しない。"""
        body = copy.deepcopy(self.bridge.cfg)
        body["mode"]["enabled"] = ["cmux-claude"]
        body["mode"]["current"] = "codex-app"
        await self._put(body)
        self.assertEqual(self.bridge.cfg["mode"]["current"], "codex-app")
        self.assertEqual(self.bridge.mode, "cmux-claude")
        with mock.patch("builtins.print"):
            self.assertEqual(
                server_main._startup_mode(self.bridge.cfg), "cmux-claude")

    async def test_partial_put_without_mode_key_keeps_live_mode(self):
        """部分 PUT (mode キーなし) は merge で current が既定へ戻っても live を動かさない。"""
        self.bridge.cfg["mode"]["current"] = "codex-app"
        with mock.patch("builtins.print"):
            self.bridge.set_mode("codex-app")
        await self._put({"brightness": 80})
        # 保存側は従来仕様どおり deep merge で既定へ戻るが、live モードは不変
        self.assertEqual(self.bridge.cfg["mode"]["current"], "cmux-claude")
        self.assertEqual(self.bridge.mode, "codex-app")

    async def test_nested_partial_put_without_current_keeps_live_mode(self):
        """mode 内の別キーだけの部分 PUT でも current は適用されない。"""
        self.bridge.cfg["mode"]["current"] = "codex-app"
        with mock.patch("builtins.print"):
            self.bridge.set_mode("codex-app")
        await self._put(
            {"mode": {"enabled": list(server_main.actions_mod.MODE_IDS)}})
        self.assertEqual(self.bridge.mode, "codex-app")

    async def test_roundtrip_keeps_diverged_live_auto(self):
        """cfg.auto=True のまま live だけ手動 (False) の乖離状態でも、無編集往復で戻さない。"""
        self.assertTrue(self.bridge.cfg["mode"]["auto"])
        self.bridge.auto_mode = False  # ACT12 tap 相当で手動化した状態
        await self._put(copy.deepcopy(self.bridge.cfg))
        self.assertFalse(self.bridge.auto_mode)


class TimingsMigrationTests(unittest.TestCase):
    """廃止キー tap_max_ms は既定から消え、旧 config からも除去される。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="claudemicro-cfg-")
        self.addCleanup(self._rmtree)
        self.path = os.path.join(self._tmpdir, "config.json")
        patcher = mock.patch.object(config_mod, "CONFIG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rmtree(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_default_config_has_no_tap_max(self):
        self.assertNotIn("tap_max_ms", config_mod.DEFAULT_CONFIG["timings"])

    def test_load_strips_legacy_tap_max(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"timings": {"tap_max_ms": 400}}, f)
        cfg = config_mod.load()
        self.assertNotIn("tap_max_ms", cfg["timings"])
        self.assertEqual(cfg["timings"]["double_window_ms"], 350)
        self.assertEqual(cfg["timings"]["long_min_ms"], 600)

    def test_save_strips_legacy_tap_max(self):
        merged = config_mod.save({"timings": {"tap_max_ms": 123}})
        self.assertNotIn("tap_max_ms", merged["timings"])
        with open(self.path, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertNotIn("tap_max_ms", on_disk["timings"])

    def test_load_with_null_enabled_normalizes_to_all_modes(self):
        """実ファイル経由の null enabled も全モード扱い (TypeError にしない)。"""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"mode": {"enabled": None}}, f)
        cfg = config_mod.load()
        self.assertIsNone(cfg["mode"]["enabled"])  # 保存値はそのまま
        self.assertEqual(
            server_main._enabled_modes(cfg), server_main.actions_mod.MODE_IDS)
