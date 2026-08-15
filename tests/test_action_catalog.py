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

    def test_undo_redo_present(self):
        """本家 UNDO/REDO キーキャップ相当を追加 (#58)。"""
        self.assertIn("undo", actions.ACTION_IDS)
        self.assertIn("redo", actions.ACTION_IDS)

    def test_fast_merged(self):
        """FAST は本家同様 1 つに統合し、旧 id は廃止 (#59)。"""
        self.assertIn("fast", actions.ACTION_IDS)
        self.assertEqual(actions.action_scope("fast"), "common")
        self.assertNotIn("fast-opus", actions.ACTION_IDS)
        self.assertNotIn("fast-codex", actions.ACTION_IDS)
        for legacy, new in actions.LEGACY_ACTION_IDS.items():
            self.assertNotIn(legacy, actions.ACTION_IDS)
            self.assertIn(new, actions.ACTION_IDS)

    def test_official_classification(self):
        """本アプリ固有 (official: False) の集合を固定する (#59。削除せず分類のみ)。"""
        custom = {a["id"] for a in actions.ACTIONS if a.get("official") is False}
        self.assertEqual(custom, {"hold", "compact", "accept-edits", "resume"})
        for a in actions.ACTIONS:
            if "official" in a:
                self.assertIsInstance(a["official"], bool, a["id"])


if __name__ == "__main__":
    unittest.main()
