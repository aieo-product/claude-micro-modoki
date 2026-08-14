"""公式 config.toml 取り込みのテスト (#53)。"""

import os
import tempfile
import unittest

from server import official_config as oc

SAMPLE = '''
[desktop]
codex-micro-lighting-brightness = 80
codex-micro-single-tap-agent-keys = true

[desktop.codex-micro-layout]
version = 1
encoderMode = "reasoning"
voiceButtonMode = "push-to-talk"
separateMicrophoneKeys = true

[desktop.codex-micro-layout.slots.ACT06]
keycapId = "FAST"
[desktop.codex-micro-layout.slots.ACT07]
keycapId = "APPR"
[desktop.codex-micro-layout.slots.ACT09]
keycapId = "SPLIT"

[desktop.codex-micro-layout.analogStick.up]
type = "command"
commandId = "composer.togglePlanMode"
[desktop.codex-micro-layout.analogStick.right]
type = "command"
commandId = "navigateForward"
[desktop.codex-micro-layout.analogStick.down]
type = "command"
commandId = "toggleSidebar"
[desktop.codex-micro-layout.analogStick.left]
type = "command"
commandId = "unknownCommandXyz"
'''


class LoadTests(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(oc.load_official("/nonexistent/codex/config.toml"))

    def test_invalid_toml_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            with open(p, "w") as f:
                f.write("this is [not valid toml")
            self.assertIsNone(oc.load_official(p))

    def test_loads_sample(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            with open(p, "w") as f:
                f.write(SAMPLE)
            self.assertIsNotNone(oc.load_official(p))


class MappingTests(unittest.TestCase):
    def _parsed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            with open(p, "w") as f:
                f.write(SAMPLE)
            return oc.load_official(p)

    def test_maps_scalar_settings(self):
        cfg, _ = oc.to_bridge_config(self._parsed())
        self.assertEqual(cfg["brightness"], 80)
        self.assertTrue(cfg["options"]["single_tap_focus"])
        self.assertEqual(cfg["knob"]["mode"], "inference")      # reasoning → inference
        self.assertEqual(cfg["mic_key"]["mode"], "push-to-talk")
        self.assertTrue(cfg["mic_key"]["separate_switches"])

    def test_maps_known_stick_commands_only(self):
        cfg, notes = oc.to_bridge_config(self._parsed())
        self.assertEqual(cfg["analog_stick"]["up"], "plan-mode")
        self.assertEqual(cfg["analog_stick"]["right"], "forward")
        self.assertEqual(cfg["analog_stick"]["down"], "sidebar-toggle")
        self.assertNotIn("left", cfg["analog_stick"])           # 未知は取り込まない
        self.assertTrue(any("unknownCommandXyz" in n for n in notes))

    def test_slot_actions_known_only(self):
        slots = oc.slot_actions(self._parsed())
        self.assertEqual(slots["ACT06"], "fast-codex")
        self.assertEqual(slots["ACT07"], "approve")
        self.assertNotIn("ACT09", slots)                        # SPLIT は未対応
        _, notes = oc.to_bridge_config(self._parsed())
        self.assertTrue(any("SPLIT" in n for n in notes))

    def test_empty_official_yields_empty_patch(self):
        cfg, notes = oc.to_bridge_config({})
        self.assertEqual(cfg, {})
        self.assertEqual(notes, [])

    def test_mapped_actions_exist_in_catalog(self):
        from server import actions
        for action in list(oc.COMMAND_ID_MAP.values()) + list(oc.KEYCAP_MAP.values()):
            self.assertIn(action, actions.ACTION_IDS, action)

    def test_brightness_clamped(self):
        cfg, _ = oc.to_bridge_config(
            {"desktop": {"codex-micro-lighting-brightness": 500}})
        self.assertEqual(cfg["brightness"], 100)


if __name__ == "__main__":
    unittest.main()
