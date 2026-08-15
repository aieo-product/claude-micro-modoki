"""#59: 廃止アクション id (fast-opus/fast-codex → fast) の設定移行テスト。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from server import config


def _legacy_config():
    return {
        "keys": {
            "k6:10": {"pos": "act06", "role": "action", "action": "fast-opus"},
            "k6:11": {"pos": "act07", "role": "action", "action": "approve"},
        },
        "analog_stick": {"up": "fast-codex"},
        "knob": {"mode": "custom", "click": "fast-opus"},
        "terminal_shortcuts": {"fast-codex": {"key_code": 53}},
        "codex_app_shortcuts": {"fast-opus": {"text_key": "f", "modifiers": ["command"]}},
    }


class ActionIdMigrationTests(unittest.TestCase):
    def _load_with(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            with mock.patch.object(config, "CONFIG_PATH", path):
                return config.load()

    def test_load_rewrites_legacy_ids(self):
        cfg = self._load_with(_legacy_config())
        self.assertEqual(cfg["keys"]["k6:10"]["action"], "fast")
        self.assertEqual(cfg["keys"]["k6:11"]["action"], "approve")  # 無関係は不変
        self.assertEqual(cfg["analog_stick"]["up"], "fast")
        self.assertEqual(cfg["knob"]["click"], "fast")

    def test_load_rewrites_shortcut_table_keys(self):
        cfg = self._load_with(_legacy_config())
        self.assertIn("fast", cfg["terminal_shortcuts"])
        self.assertNotIn("fast-codex", cfg["terminal_shortcuts"])
        self.assertEqual(cfg["codex_app_shortcuts"]["fast"]["text_key"], "f")
        self.assertNotIn("fast-opus", cfg["codex_app_shortcuts"])

    def test_existing_new_id_is_not_overwritten(self):
        """新旧 id が併存する場合は既存 (新 id) の spec を優先する。"""
        data = _legacy_config()
        data["terminal_shortcuts"]["fast"] = {"key_code": 36}
        cfg = self._load_with(data)
        self.assertEqual(cfg["terminal_shortcuts"]["fast"], {"key_code": 36})

    def test_two_legacy_ids_first_wins_deterministically(self):
        """旧 id 同士が併存する場合は記載順の先勝ちで、負けた側は残さない (レビュー指摘)。"""
        data = _legacy_config()
        data["terminal_shortcuts"] = {
            "fast-opus": {"key_code": 1},
            "fast-codex": {"key_code": 2},
        }
        cfg = self._load_with(data)
        self.assertEqual(cfg["terminal_shortcuts"]["fast"], {"key_code": 1})
        self.assertNotIn("fast-opus", cfg["terminal_shortcuts"])
        self.assertNotIn("fast-codex", cfg["terminal_shortcuts"])

    def test_save_persists_migrated_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with mock.patch.object(config, "CONFIG_PATH", path):
                config.save(_legacy_config())
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
        self.assertEqual(saved["keys"]["k6:10"]["action"], "fast")
        self.assertEqual(saved["analog_stick"]["up"], "fast")
        self.assertIn("fast", saved["terminal_shortcuts"])

    def test_defaults_untouched(self):
        """既定設定 (廃止 id なし) はそのまま。"""
        cfg = self._load_with({})
        self.assertEqual(cfg["analog_stick"], config.DEFAULT_CONFIG["analog_stick"])


if __name__ == "__main__":
    unittest.main()
