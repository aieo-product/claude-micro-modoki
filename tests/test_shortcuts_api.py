"""codex-app ショートカット (#70): 推奨キーの解決順・/api/shortcuts・PUT 時の spec 検証。"""

import copy
import json
import os
import tempfile
from unittest import mock

from aiohttp.test_utils import make_mocked_request

from server import config as config_mod
from tests.test_events import BridgeApiTestBase, DummyAdapter, server_main


class CodexAppSpecResolutionTests(BridgeApiTestBase):
    """ユーザー上書き > 公式既定 > 有効化済み推奨キー。未有効の推奨キーは None。"""

    def setUp(self):
        super().setUp()
        self.bridge = server_main.bridge

    def test_default_map_wins_without_override(self):
        self.assertEqual(self.bridge._codex_app_spec("new-session"),
                         server_main.CODEX_APP_KEYSTROKE_MAP["new-session"])

    def test_override_beats_default(self):
        self.bridge.cfg["codex_app_shortcuts"] = {"new-session": {"text_key": "q", "modifiers": ["command"]}}
        self.assertEqual(self.bridge._codex_app_spec("new-session")["text_key"], "q")

    def test_recommended_requires_enable(self):
        self.assertIn("fast", server_main.CODEX_APP_RECOMMENDED_SHORTCUTS)
        self.assertIsNone(self.bridge._codex_app_spec("fast"))          # 未有効: 送らない
        self.bridge.cfg["codex_app_shortcuts_enabled"] = ["fast"]
        spec = self.bridge._codex_app_spec("fast")
        self.assertEqual(spec["text_key"], "f")
        self.assertNotIn("official_label", spec)                          # 送出 spec に説明は含めない
        self.assertIsNotNone(self.bridge._sanitize_spec(spec))            # 送出可能な形

    def test_recommended_specs_are_sanitizable_and_target_unassigned_actions(self):
        for aid, rec in server_main.CODEX_APP_RECOMMENDED_SHORTCUTS.items():
            with self.subTest(aid=aid):
                self.assertIn(aid, server_main.actions_mod.ACTION_IDS)
                self.assertNotIn(aid, server_main.CODEX_APP_KEYSTROKE_MAP)  # 既定があるものに推奨は不要
                self.assertIsNotNone(self.bridge._sanitize_spec(
                    {k: v for k, v in rec.items() if k != "official_label"}))
                self.assertIn("official_label", rec)


class ShortcutsApiTests(BridgeApiTestBase):
    async def test_shortcuts_lists_status_per_action(self):
        server_main.bridge.cfg["codex_app_shortcuts"] = {"git": {"text_key": "g", "modifiers": ["control", "option"]}}
        server_main.bridge.cfg["codex_app_shortcuts_enabled"] = ["fast"]
        status, body = await self._request_json("GET", "/api/shortcuts")
        self.assertEqual(status, 200)
        by_id = {r["id"]: r for r in body["codex_app"]}
        self.assertEqual(by_id["new-session"]["status"], "default")
        self.assertEqual(by_id["fast"]["status"], "recommended-enabled")
        self.assertEqual(by_id["plan-mode"]["status"], "recommended")
        self.assertEqual(by_id["git"]["status"], "override")
        self.assertEqual(by_id["approve"]["status"], "bridge")
        self.assertEqual(by_id["debug"]["status"], "unsupported")
        self.assertEqual(by_id["fast"]["official_label"], "高速モードを切り替え")
        self.assertNotIn("official_label", by_id["fast"]["recommended"])
        self.assertEqual(sorted(body["valid_modifiers"]), sorted(server_main.Bridge.VALID_MODIFIERS))


class PutConfigShortcutValidationTests(BridgeApiTestBase):
    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp(prefix="claudemicro-cfg-")
        patcher = mock.patch.object(config_mod, "CONFIG_PATH", os.path.join(self._tmpdir, "config.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _put(self, body):
        return await self._request_json("PUT", "/api/config", body)

    async def test_valid_override_and_enable_are_saved(self):
        body = copy.deepcopy(server_main.bridge.cfg)
        body["codex_app_shortcuts"] = {"git": {"text_key": "g", "modifiers": ["control", "option"]}}
        body["codex_app_shortcuts_enabled"] = ["fast", "merge"]
        status, saved = await self._put(body)
        self.assertEqual(status, 200)
        self.assertEqual(saved["codex_app_shortcuts"]["git"]["text_key"], "g")
        self.assertEqual(saved["codex_app_shortcuts_enabled"], ["fast", "merge"])

    async def test_invalid_specs_are_rejected_with_400(self):
        base = copy.deepcopy(server_main.bridge.cfg)
        cases = {
            "unknown modifier": {"codex_app_shortcuts": {"git": {"text_key": "g", "modifiers": ["hyper"]}}},
            "unknown action": {"codex_app_shortcuts": {"nope": {"text_key": "g", "modifiers": ["command"]}}},
            "not object": {"terminal_shortcuts": ["x"]},
            "enabled unknown": {"codex_app_shortcuts_enabled": ["new-session"]},  # 推奨キーが無い id
            "enabled not list": {"codex_app_shortcuts_enabled": "fast"},
        }
        for name, patch in cases.items():
            with self.subTest(name=name):
                body = copy.deepcopy(base); body.update(patch)
                status, resp = await self._put(body)
                self.assertEqual(status, 400, resp)
                self.assertEqual(resp["error"], "invalid shortcut")
