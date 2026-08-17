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

    def test_recommended_chords_do_not_collide(self):
        """推奨キー同士 / 公式既定 (CODEX_APP_KEYSTROKE_MAP) と chord が重複しない。
        ⌃⌥ (VoiceOver の VO キー) を使わない (レビュー指摘)。"""
        def chord(spec):
            return (frozenset(spec.get("modifiers", [])), str(spec.get("text_key", "")).lower())
        seen = {}
        for aid, spec in server_main.CODEX_APP_KEYSTROKE_MAP.items():
            seen.setdefault(chord(spec), aid)
        for aid, rec in server_main.CODEX_APP_RECOMMENDED_SHORTCUTS.items():
            with self.subTest(aid=aid):
                c = chord(rec)
                self.assertNotIn(c, seen, f"{aid} の chord が {seen.get(c)} と重複")
                seen[c] = aid
                mods = set(rec["modifiers"])
                self.assertFalse({"control", "option"} <= mods, f"{aid}: ⌃⌥ は VoiceOver の VO キー")
                self.assertTrue(rec["text_key"].isalpha() and len(rec["text_key"]) == 1,
                                f"{aid}: 配列非依存の英字 1 文字にする")

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

    async def test_partial_put_and_legacy_config_without_enabled_key(self):
        """enabled キーの無い旧 config / 部分 PUT でも 400 にならず既定 ([]) に落ちる。"""
        server_main.bridge.cfg.pop("codex_app_shortcuts_enabled", None)
        status, saved = await self._put({"brightness": 80})
        self.assertEqual(status, 200)
        self.assertEqual(saved["codex_app_shortcuts_enabled"], [])
        self.assertIsNone(server_main.bridge._codex_app_spec("fast"))

    async def test_invalid_specs_are_rejected_with_400(self):
        base = copy.deepcopy(server_main.bridge.cfg)
        cases = {
            "unknown modifier": {"codex_app_shortcuts": {"git": {"text_key": "g", "modifiers": ["hyper"]}}},
            "unknown action": {"codex_app_shortcuts": {"nope": {"text_key": "g", "modifiers": ["command"]}}},
            "not object": {"terminal_shortcuts": ["x"]},
            "explicit null table": {"codex_app_shortcuts": None},
            "enabled unknown": {"codex_app_shortcuts_enabled": ["new-session"]},  # 推奨キーが無い id
            "enabled not list": {"codex_app_shortcuts_enabled": "fast"},
            "enabled null": {"codex_app_shortcuts_enabled": None},
            "enabled non-hashable": {"codex_app_shortcuts_enabled": [{}]},  # 以前は TypeError → 500
        }
        for name, patch in cases.items():
            with self.subTest(name=name):
                body = copy.deepcopy(base); body.update(patch)
                status, resp = await self._put(body)
                self.assertEqual(status, 400, resp)
                self.assertEqual(resp["error"], "invalid shortcut")


class EnabledMigrationTests(BridgeApiTestBase):
    """codex_app_shortcuts_enabled も旧 id → 新 id へ写像される (#70 レビュー指摘)。"""

    def test_legacy_ids_in_enabled_are_migrated(self):
        with mock.patch.dict(server_main.actions_mod.LEGACY_ACTION_IDS, {"old-fast": "fast"}):
            cfg = config_mod._migrate(
                config_mod._deep_merge(config_mod.DEFAULT_CONFIG,
                                       {"codex_app_shortcuts_enabled": ["old-fast", "merge", "fast"]}))
        self.assertEqual(cfg["codex_app_shortcuts_enabled"], ["fast", "merge"])  # 写像 + 重複除去 + 順序維持
