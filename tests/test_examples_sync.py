"""examples/ の hook 設定が installer と乖離しないことの検証 (#76)。

登録イベントの正は scripts/install_hooks.py の定数。installer 側に
イベントを足したら、このテストが example の追随を強制する。
"""

import json
import sys
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts import install_hooks  # noqa: E402


def _example_hooks(name: str) -> dict:
    path = REPO_DIR / "examples" / name
    return json.loads(path.read_text(encoding="utf-8"))["hooks"]


class ClaudeExampleSyncTests(unittest.TestCase):
    def setUp(self):
        self.hooks = _example_hooks("settings.local.json")

    def test_events_match_installer(self):
        expected = set(install_hooks.CLAUDE_EVENTS) | {"PreToolUse"}
        self.assertEqual(set(self.hooks), expected)

    def test_groups_match_installer_shape(self):
        for event, groups in self.hooks.items():
            with self.subTest(event=event):
                self.assertEqual(len(groups), 1)
                group = groups[0]
                (hook,) = group["hooks"]
                self.assertEqual(hook["type"], "command")
                self.assertIn("hook_client.py", hook["command"])
                self.assertNotIn("codex_hook_client.py", hook["command"])
                if event == "PreToolUse":
                    # installer: add_group(..., matcher="*", timeout=300)
                    self.assertEqual(group["matcher"], "*")
                    self.assertEqual(hook["timeout"], 300)
                else:
                    self.assertNotIn("matcher", group)
                    self.assertEqual(hook["timeout"], 10)


class CodexExampleSyncTests(unittest.TestCase):
    def setUp(self):
        self.hooks = _example_hooks("codex-hooks.json")

    def test_events_match_installer(self):
        expected = set(install_hooks.CODEX_EVENTS) | set(
            install_hooks.CODEX_TOOL_EVENTS)
        self.assertEqual(set(self.hooks), expected)

    def test_groups_match_installer_shape(self):
        tool_events = set(install_hooks.CODEX_TOOL_EVENTS)
        for event, groups in self.hooks.items():
            with self.subTest(event=event):
                self.assertEqual(len(groups), 1)
                group = groups[0]
                (hook,) = group["hooks"]
                self.assertEqual(hook["type"], "command")
                self.assertIn("codex_hook_client.py", hook["command"])
                self.assertEqual(hook["timeout"], 10)
                if event in tool_events:
                    # installer: add_group(..., matcher=".*")
                    self.assertEqual(group["matcher"], ".*")
                else:
                    self.assertNotIn("matcher", group)
