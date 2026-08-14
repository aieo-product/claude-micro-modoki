"""段階3(#36): アクションカタログ拡充のテスト。"""

import unittest

from server import actions


class ActionCatalogTests(unittest.TestCase):
    def test_ids_unique(self):
        ids = [a["id"] for a in actions.ACTIONS]
        self.assertEqual(len(ids), len(set(ids)), "重複 id あり")

    def test_all_have_required_fields(self):
        for a in actions.ACTIONS:
            self.assertIn("id", a)
            self.assertIn("label", a)
            self.assertIn("icon", a)
            self.assertIn(a["scope"], ("common", "control", "claude", "codex"))

    def test_stock_keycap_equivalents_present(self):
        """本家キーキャップ相当のアクションがカタログに存在する (#36)。"""
        expected = {
            "merge", "codex-focus", "debug", "download", "navigate",
            "magic", "play", "draft", "history", "thinking", "setup",
        }
        self.assertTrue(expected <= actions.ACTION_IDS, expected - actions.ACTION_IDS)

    def test_scope_lookup_consistent(self):
        for a in actions.ACTIONS:
            self.assertEqual(actions.action_scope(a["id"]), a["scope"])
        self.assertIsNone(actions.action_scope("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
