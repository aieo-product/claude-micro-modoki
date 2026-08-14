"""#5: アクション実処理(キーストローク送出)のテスト。実際の送出は行わずスクリプトを検証。"""

import asyncio
import unittest


async def _noop():
    return None

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
        self.assertEqual(scheduled, [])  # interrupt は codex-app マップ未定義のため送出しない

    def test_keystroke_map_targets_exist(self):
        """KEYSTROKE_MAP の全 id はアクションカタログに存在する。"""
        from server import actions
        for aid in main_mod.KEYSTROKE_MAP:
            self.assertIn(aid, actions.ACTION_IDS, aid)



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


class ClaudeOnlyGuardTests(unittest.TestCase):
    """#43 レビュー指摘: claude 固有コマンドを codex 端末へ送らない。"""

    def _bridge(self, mode):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        b.mode = mode
        scheduled = []

        class _Loop:
            def create_task(self, coro):
                scheduled.append(coro)
                coro.close()

        b.loop = _Loop()
        return b, scheduled

    def test_claude_only_without_codex_equivalent_not_sent(self):
        """codex CLI に確認済みの代替が無い claude 固有コマンドは送出しない。"""
        b, scheduled = self._bridge("cmux-codex")
        targets = [a for a in main_mod.CLAUDE_ONLY_KEYSTROKES
                   if a not in main_mod.CODEX_CLI_KEYSTROKE_MAP]
        for aid in targets:
            b._exec_action(aid)
        self.assertEqual(scheduled, [])

    def test_codex_equivalents_reachable_via_run_action(self):
        """scope ゲート(run_action)を通って codex CLI 用の割当が実際に使われる (#57)。"""
        b, _ = self._bridge("cmux-codex")
        sent = []
        b._send_keystroke = lambda spec: sent.append(spec) or _noop()
        b._resolve_selected_or_oldest = lambda r: None
        for aid in ("compact", "resume", "accept-edits", "plan-mode"):
            b.run_action(aid, "tap")      # 本番経路
        self.assertEqual(len(sent), 4, "scope ゲートで弾かれている")
        self.assertEqual(sent[0]["text"], "/compact")
        self.assertEqual(sent[2]["text"], "/permissions")

    def test_claude_only_sent_on_claude_terminal(self):
        b, scheduled = self._bridge("cmux-claude")
        b._exec_action("new-session")
        self.assertEqual(len(scheduled), 1)

    def test_generic_actions_still_sent_to_codex_terminal(self):
        b, scheduled = self._bridge("cmux-codex")
        b._exec_action("interrupt")   # 汎用キーは送出される
        b._exec_action("scroll-down")
        self.assertEqual(len(scheduled), 2)


class CodexAppExecTests(unittest.TestCase):
    """#42: codex-app への公式アプリショートカット委譲。"""

    def _bridge(self, mode="codex-app"):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        b.mode = mode
        scheduled = []

        class _Loop:
            def create_task(self, coro):
                scheduled.append(coro)
                coro.close()

        b.loop = _Loop()
        return b, scheduled

    def test_mapped_codex_app_action_sends(self):
        b, scheduled = self._bridge()
        b._exec_action("new-session")      # ⌘N 新しいチャット
        b._exec_action("sidebar-toggle")   # ⌘B
        self.assertEqual(len(scheduled), 2)

    def test_unmapped_codex_app_action_no_send(self):
        b, scheduled = self._bridge()
        b._exec_action("fork")             # ショートカット未確認
        self.assertEqual(scheduled, [])

    def test_codex_app_map_targets_exist(self):
        from server import actions
        for aid in main_mod.CODEX_APP_KEYSTROKE_MAP:
            self.assertIn(aid, actions.ACTION_IDS, aid)

    def test_codex_app_specs_wellformed(self):
        for aid, spec in main_mod.CODEX_APP_KEYSTROKE_MAP.items():
            self.assertIn("text_key", spec, aid)
            self.assertTrue(spec.get("modifiers"), aid)
            for mod in spec["modifiers"]:
                self.assertIn(mod, ("command", "shift", "option", "control"), aid)


class TextKeyScriptTests(unittest.TestCase):
    """text_key(修飾付き文字ショートカット) のスクリプト生成。"""

    def test_script_has_keystroke_and_modifiers(self):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        calls = []

        async def fake_run(*argv):
            calls.append(argv)

        b._run = fake_run
        orig = main_mod.sys.platform
        main_mod.sys.platform = "darwin"
        try:
            asyncio.run(b._send_keystroke({"text_key": "n", "modifiers": ["command"]}))
        finally:
            main_mod.sys.platform = orig
        self.assertIn('keystroke "n" using {command down}', calls[0][2])


class CodexAppMapCorrectnessTests(unittest.TestCase):
    """#51: 実機採取に基づくマップの正しさ（回帰防止）。"""

    def test_focus_term_is_control_only(self):
        """メニューの mod=12 は ⌃ のみ(⌘なし)。⌥ を含めない (バグ回帰防止)。"""
        spec = main_mod.CODEX_APP_KEYSTROKE_MAP["focus-term"]
        self.assertEqual(spec["modifiers"], ["control"])

    # 採取元: ChatGPT.app 26.803.81509 の 設定 > キーボードショートカット 既定値。
    # 期待値を表で固定し、キー/修飾キーの取り違えを検出する。
    EXPECTED_CODEX_APP = {
        "new-session":    ("n", ["command"]),                 # ⌘N
        "temp-chat":      ("n", ["command", "shift"]),        # ⇧⌘N
        "archive":        ("a", ["command", "shift"]),        # ⇧⌘A
        "side-chat":      ("s", ["command", "option"]),       # ⌥⌘S
        "pin":            ("p", ["command", "option"]),       # ⌥⌘P
        "codex-focus":    ("3", ["control"]),                 # ⌃3
        "sidebar-toggle": ("b", ["command"]),                 # ⌘B
        "focus-term":     ("@", ["control"]),                 # ⌃@
        "diff":           ("b", ["command", "option"]),       # ⌥⌘B
        "prev-session":   ("[", ["command", "shift"]),        # ⇧⌘[
        "next-session":   ("]", ["command", "shift"]),        # ⇧⌘]
        "back":           ("[", ["command"]),                 # ⌘[
        "forward":        ("]", ["command"]),                 # ⌘]
    }

    def test_exact_key_and_modifiers(self):
        """全エントリのキー・修飾キーを期待値と突き合わせる (取り違え検出)。"""
        self.assertEqual(set(main_mod.CODEX_APP_KEYSTROKE_MAP), set(self.EXPECTED_CODEX_APP))
        for aid, (key, mods) in self.EXPECTED_CODEX_APP.items():
            spec = main_mod.CODEX_APP_KEYSTROKE_MAP[aid]
            self.assertEqual(spec["text_key"], key, aid)
            self.assertEqual(sorted(spec["modifiers"]), sorted(mods), aid)

    def test_no_unassigned_actions_mapped(self):
        """既定が未割り当てのアクションは送出対象にしない(誤送出回避)。
        採取元 ChatGPT.app 26.803.81509 基準。アプリ更新で既定が付いたら意図的に更新する。"""
        for aid in ("git", "pr", "branch", "merge", "fast-codex", "new-window"):
            self.assertNotIn(aid, main_mod.CODEX_APP_KEYSTROKE_MAP, aid)


class CrossModeActionTests(unittest.TestCase):
    """#55: 本家同様、同じ割当が claude/codex どちらでも動く。"""

    def _bridge(self, mode, overrides=None):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        b.mode = mode
        b.cfg = {"codex_app_shortcuts": overrides or {}}
        scheduled = []

        class _Loop:
            def create_task(self, coro):
                scheduled.append(coro)
                coro.close()

        b.loop = _Loop()
        return b, scheduled

    def test_plan_mode_is_not_family_gated(self):
        """plan-mode は common scope になり codex モードでも弾かれない。"""
        from server import actions
        self.assertEqual(actions.action_scope("plan-mode"), "common")

    def test_plan_mode_runs_on_claude_terminal(self):
        b, scheduled = self._bridge("cmux-claude")
        b._exec_action("plan-mode")
        self.assertEqual(len(scheduled), 1)      # Shift+Tab を送出

    def test_codex_app_user_override_enables_unassigned_action(self):
        """公式側で割り当てたショートカットを config に登録すると送出できる。"""
        override = {"plan-mode": {"text_key": "y", "modifiers": ["command", "option"]}}
        b, scheduled = self._bridge("codex-app", override)
        b._exec_action("plan-mode")
        self.assertEqual(len(scheduled), 1)

    def test_codex_app_without_override_does_not_send(self):
        b, scheduled = self._bridge("codex-app")
        b._exec_action("plan-mode")              # 既定マップに無い
        self.assertEqual(scheduled, [])

    def test_user_override_takes_precedence(self):
        """既定マップより config の上書きを優先する(実際に送出される spec を検証)。"""
        override = {"sidebar-toggle": {"text_key": "z", "modifiers": ["command"]}}
        b, _ = self._bridge("codex-app", override)
        sent = []
        b._send_keystroke = lambda spec: sent.append(spec) or _noop()
        b._exec_action("sidebar-toggle")
        self.assertEqual(sent[0]["text_key"], "z")   # 既定は "b"


class CodexCliMapTests(unittest.TestCase):
    """#57: codex CLI 調査結果に基づくマップ (codex-cli 0.147.0)。"""

    def test_confirmed_bindings(self):
        m = main_mod.CODEX_CLI_KEYSTROKE_MAP
        self.assertEqual(m["plan-mode"], {"key_code": 48, "modifiers": ["shift"]})
        self.assertEqual(m["inference-effort"], {"key_code": 47, "modifiers": ["option"]})
        self.assertEqual(m["interrupt"], {"key_code": 53})
        self.assertEqual(m["compact"]["text"], "/compact")
        self.assertTrue(m["compact"]["enter"])

    def test_unknown_actions_not_mapped(self):
        """調査で unknown だったものは誤送出を避けるため非マップ。"""
        for aid in ("git", "pr", "branch", "next-session", "prev-session"):
            self.assertNotIn(aid, main_mod.CODEX_CLI_KEYSTROKE_MAP, aid)

    def test_all_targets_exist_in_catalog(self):
        from server import actions
        for aid in main_mod.CODEX_CLI_KEYSTROKE_MAP:
            self.assertIn(aid, actions.ACTION_IDS, aid)


class SpecSanitizeTests(unittest.TestCase):
    """#55 レビュー指摘: ユーザー設定由来の spec を AppleScript に渡す前に検証する。"""

    def test_rejects_injected_modifier(self):
        evil = {"key_code": 53,
                "modifiers": ['command down}\ndo shell script "touch /tmp/pwned"\n--']}
        self.assertIsNone(main_mod.Bridge._sanitize_spec(evil))

    def test_rejects_unknown_modifier_and_bad_types(self):
        self.assertIsNone(main_mod.Bridge._sanitize_spec({"key_code": 1, "modifiers": ["hyper"]}))
        self.assertIsNone(main_mod.Bridge._sanitize_spec({"key_code": "53"}))
        self.assertIsNone(main_mod.Bridge._sanitize_spec({"key_code": True}))
        self.assertIsNone(main_mod.Bridge._sanitize_spec({"key_code": 999}))
        self.assertIsNone(main_mod.Bridge._sanitize_spec({"text": ""}))
        self.assertIsNone(main_mod.Bridge._sanitize_spec("not a dict"))

    def test_accepts_valid_specs(self):
        ok = main_mod.Bridge._sanitize_spec({"key_code": 48, "modifiers": ["shift"]})
        self.assertEqual(ok, {"modifiers": ["shift"], "key_code": 48})
        ok2 = main_mod.Bridge._sanitize_spec({"text": "/compact", "enter": True})
        self.assertEqual(ok2, {"text": "/compact", "enter": True})

    def test_builtin_maps_all_pass_validation(self):
        for name in ("KEYSTROKE_MAP", "CODEX_APP_KEYSTROKE_MAP", "CODEX_CLI_KEYSTROKE_MAP"):
            for aid, spec in getattr(main_mod, name).items():
                self.assertIsNotNone(main_mod.Bridge._sanitize_spec(spec), f"{name}:{aid}")


class KnobDirectionTests(unittest.TestCase):
    """#55 レビュー指摘: ノブの左右回転でエフォートの上下が分かれること。"""

    def test_inference_mode_uses_direction(self):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        b.cfg = {"knob": {"mode": "inference"}}
        b.mode = "cmux-codex"
        calls = []
        b.run_action = lambda a, g: calls.append(a)
        b._on_knob("ENC_CW", "tap")
        b._on_knob("ENC_CC", "tap")
        self.assertEqual(calls, ["inference-effort", "inference-effort-down"])

if __name__ == "__main__":
    unittest.main()
