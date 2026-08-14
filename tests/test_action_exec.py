"""#5: アクション実処理(キーストローク送出)のテスト。実際の送出は行わずスクリプトを検証。"""

import asyncio
import unittest

from server import main as main_mod


class KeystrokeSendTests(unittest.TestCase):
    def _bridge(self):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        calls = []

        async def fake_run(*argv):
            calls.append(argv)

        b._run = fake_run
        return b, calls

    def _send(self, spec):
        b, calls = self._bridge()
        # darwin 前提のスクリプト生成を検証（プラットフォーム分岐を一時上書き）
        orig = main_mod.sys.platform
        main_mod.sys.platform = "darwin"
        try:
            asyncio.run(b._send_keystroke(spec))
        finally:
            main_mod.sys.platform = orig
        return calls

    def test_key_code_script(self):
        calls = self._send({"key_code": 53})
        self.assertEqual(len(calls), 1)
        self.assertIn("key code 53", calls[0][2])
        self.assertNotIn("using", calls[0][2])

    def test_key_code_with_modifier(self):
        calls = self._send({"key_code": 48, "modifiers": ["shift"]})
        self.assertIn("key code 48 using {shift down}", calls[0][2])

    def test_text_with_enter(self):
        calls = self._send({"text": "/compact", "enter": True})
        # 1回目=keystroke、2回目=key code 36(Return)
        self.assertIn('keystroke "/compact"', calls[0][2])
        self.assertIn("key code 36", calls[1][2])

    def test_text_quote_escaped(self):
        calls = self._send({"text": 'a"b'})
        self.assertIn('keystroke "a\\"b"', calls[0][2])

    def test_non_darwin_noop(self):
        b, calls = self._bridge()
        orig = main_mod.sys.platform
        main_mod.sys.platform = "win32"
        try:
            asyncio.run(b._send_keystroke({"key_code": 53}))
        finally:
            main_mod.sys.platform = orig
        self.assertEqual(calls, [])


class ExecActionTests(unittest.TestCase):
    def _bridge(self, mode="cmux-claude"):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        b.mode = mode
        scheduled = []

        class _Loop:
            def create_task(self, coro):
                scheduled.append(coro)
                coro.close()  # 実行はしない(スクリプト検証は別テスト)

        b.loop = _Loop()
        return b, scheduled

    def test_mapped_action_schedules_send(self):
        b, scheduled = self._bridge()
        b._exec_action("interrupt")
        self.assertEqual(len(scheduled), 1)

    def test_unmapped_action_no_send(self):
        b, scheduled = self._bridge()
        b._exec_action("archive")  # KEYSTROKE_MAP 未定義
        self.assertEqual(scheduled, [])

    def test_codex_app_no_send(self):
        b, scheduled = self._bridge(mode="codex-app")
        b._exec_action("interrupt")
        self.assertEqual(scheduled, [])  # codex-app は委譲未対応でログのみ

    def test_keystroke_map_targets_exist(self):
        """KEYSTROKE_MAP の全 id はアクションカタログに存在する。"""
        from server import actions
        for aid in main_mod.KEYSTROKE_MAP:
            self.assertIn(aid, actions.ACTION_IDS, aid)


if __name__ == "__main__":
    unittest.main()


class KeystrokeMapExpansionTests(unittest.TestCase):
    """#43: 追加マップの妥当性。"""

    def test_added_actions_mapped(self):
        for aid in ("accept-edits", "resume", "new-session", "input-nav"):
            self.assertIn(aid, main_mod.KEYSTROKE_MAP, aid)

    def test_slash_commands_send_enter(self):
        for aid in ("compact", "resume", "new-session"):
            spec = main_mod.KEYSTROKE_MAP[aid]
            self.assertTrue(spec.get("text", "").startswith("/"), aid)
            self.assertTrue(spec.get("enter"), aid)

    def test_specs_are_wellformed(self):
        for aid, spec in main_mod.KEYSTROKE_MAP.items():
            self.assertTrue("text" in spec or "key_code" in spec, aid)
            if "key_code" in spec:
                self.assertIsInstance(spec["key_code"], int, aid)
            for mod in spec.get("modifiers", []):
                self.assertIn(mod, ("shift", "command", "option", "control"), aid)
