"""入力コントロール設定モデルの round-trip / 整合テスト (#34)。"""

import copy
import os
import tempfile
import unittest
from unittest import mock

from server import actions, config


class InputControlsConfigTests(unittest.TestCase):
    def test_defaults_present(self):
        d = config.DEFAULT_CONFIG
        self.assertIn("analog_stick", d)
        self.assertEqual(set(d["analog_stick"]), {"up", "right", "down", "left"})
        self.assertIn("knob", d)
        self.assertEqual(
            set(d["knob"]),
            {"mode", "rotate_cw", "rotate_ccw", "click", "long_press"},
        )
        self.assertIn("mic_key", d)
        self.assertIn("options", d)

    def test_default_referenced_actions_exist(self):
        """既定の割当アクションはすべてカタログに存在する。"""
        refs = set(config.DEFAULT_CONFIG["analog_stick"].values())
        k = config.DEFAULT_CONFIG["knob"]
        refs |= {k["rotate_cw"], k["rotate_ccw"], k["click"], k["long_press"]}
        self.assertTrue(refs <= actions.ACTION_IDS, refs - actions.ACTION_IDS)

    def test_control_scope_actions_added(self):
        control = {a["id"] for a in actions.ACTIONS if a["scope"] == "control"}
        for expected in ("forward", "back", "sidebar-toggle", "push-to-talk"):
            self.assertIn(expected, control)

    def test_round_trip_preserves_input_controls(self):
        """PUT 相当(save)→load で入力コントロール設定が保持される。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with mock.patch.object(config, "CONFIG_PATH", path):
                override = {
                    "analog_stick": {"up": "compact", "right": "back",
                                     "down": "scroll-convo", "left": "forward"},
                    "knob": {"mode": "custom", "rotate_cw": "scroll-down",
                             "rotate_ccw": "scroll-up", "click": "approve",
                             "long_press": "reject"},
                    "mic_key": {"mode": "toggle", "separate_switches": True},
                    "options": {"single_tap_focus": True},
                }
                saved = config.save(copy.deepcopy(override))
                self.assertEqual(saved["analog_stick"]["up"], "compact")
                self.assertTrue(saved["mic_key"]["separate_switches"])
                loaded = config.load()
                self.assertEqual(loaded["knob"]["mode"], "custom")
                self.assertEqual(loaded["knob"]["click"], "approve")
                self.assertTrue(loaded["options"]["single_tap_focus"])
                # 未指定キー(既存モデル)は既定を維持する
                self.assertIn("mode", loaded)
                self.assertEqual(loaded["agent_keys"]["mode"], "recent")


if __name__ == "__main__":
    unittest.main()
