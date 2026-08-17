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


class KeycapCatalogTests(unittest.TestCase):
    """本家キーキャップ刻印ギャラリー (#93)。既定アクションは採取ベース (KEYCAP_MAP) のみ。"""

    def test_ids_unique_and_fields(self):
        ids = [k["id"] for k in actions.KEYCAPS]
        self.assertEqual(len(ids), len(set(ids)))
        for k in actions.KEYCAPS:
            self.assertIn("glyph", k)
            self.assertIn("default", k)

    def test_defaults_are_valid_actions(self):
        for k in actions.KEYCAPS:
            if k["default"] is not None:
                self.assertIn(k["default"], actions.ACTION_IDS, k["id"])

    def test_defaults_match_official_keycap_map(self):
        """刻印の既定 = 公式取込 KEYCAP_MAP と一致 (採取ベースのみ。推測追加を防ぐ)。
        UNDO/REDO は公式ギャラリーで未確認のためギャラリーには載せない。"""
        from server import official_config as oc
        gallery_defaults = {k["id"]: k["default"] for k in actions.KEYCAPS if k["default"]}
        expected = {kc: aid for kc, aid in oc.KEYCAP_MAP.items() if kc not in ("UNDO", "REDO")}
        self.assertEqual(gallery_defaults, expected)
        self.assertNotIn("UNDO", actions.KEYCAP_IDS)
        self.assertNotIn("REDO", actions.KEYCAP_IDS)

    def test_gallery_covers_captured_engravings(self):
        """docs/codex-micro-official-ui.md 採取の 33 種 + EMPT1–4 を網羅する。"""
        captured = {
            "FAST", "APPR", "REJ", "FORK", "MIC1", "CODEX", "BUG", "OAI", "TERM", "DWN",
            "DEL", "NEW", "NAV", "MAGIC", "DIFF", "PLAY", "GIT", "DRAFT", "BRANCH", "MRG",
            "PR", "PAINT", "LAB", "PARTY", "TIME", "MIND+", "MIND-", "SETUP", "FOLD",
            "UPL", "APPS", ":yolo:", ":yeet:", "EMPT1", "EMPT2", "EMPT3", "EMPT4",
        }
        self.assertEqual(actions.KEYCAP_IDS, captured)

    def test_keycap_default_lookup(self):
        self.assertEqual(actions.keycap_default("APPR"), "approve")
        self.assertIsNone(actions.keycap_default("FORK"))
        self.assertIsNone(actions.keycap_default("does-not-exist"))
