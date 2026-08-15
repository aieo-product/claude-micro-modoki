"""公式 config.toml 取り込みのテスト (#53)。"""

import json
import os
import tempfile
import unittest

from server import official_config as oc

requires_tomllib = unittest.skipUnless(
    oc.tomllib is not None, "tomllib が無い環境 (Python 3.10 以下) では取り込み機能は無効")

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

    @requires_tomllib
    def test_loads_sample(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            with open(p, "w") as f:
                f.write(SAMPLE)
            self.assertIsNotNone(oc.load_official(p))


@requires_tomllib
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
        self.assertEqual(slots["ACT06"], "fast")   # FAST は統合後 id へ (#59)
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



class ImportApiTests(unittest.IsolatedAsyncioTestCase):
    """/api/import-official の API 契約 (GET=非破壊プレビュー / POST=適用)。"""

    SAMPLE_OFFICIAL = {
        "desktop": {
            "codex-micro-lighting-brightness": 55,
            "codex-micro-layout": {
                "encoderMode": "reasoning",
                "analogStick": {"up": {"type": "command",
                                       "commandId": "toggleSidebar"}},
                "slots": {"ACT07": {"keycapId": "APPR"},
                          "ACT08": {"keycapId": "REJ"}},
            },
        }
    }

    def setUp(self):
        from server import main as m
        self.m = m
        self._saved_cfg = m.bridge.cfg
        self._saved_load = m.official_mod.load_official
        self._saved_save = m.config_mod.save
        self._saved_adapter = m.bridge.adapter
        m.bridge.cfg = {
            "brightness": 100, "timings": {"tap_max_ms": 400,
                                           "double_window_ms": 350,
                                           "long_min_ms": 600},
            "knob": {"mode": "scroll"}, "analog_stick": {"up": "plan-mode"},
            # ACT07 は学習済み(pos あり) / ACT08 は未学習(pos なし)
            "keys": {"ACT07": {"pos": "p08", "role": "action", "action": "hold"},
                     "ACT08": {"role": "action", "action": "hold"}},
        }
        self.saved = []
        m.official_mod.load_official = lambda path=None: self.SAMPLE_OFFICIAL
        m.config_mod.save = lambda cfg: (self.saved.append(cfg), cfg)[1]
        m.bridge.adapter = type("A", (), {"update_timings": lambda self, t: None})()

    def tearDown(self):
        self.m.bridge.cfg = self._saved_cfg
        self.m.official_mod.load_official = self._saved_load
        self.m.config_mod.save = self._saved_save
        self.m.bridge.adapter = self._saved_adapter

    async def _call(self, method):
        from aiohttp.test_utils import make_mocked_request
        req = make_mocked_request(method, "/api/import-official")
        return await self.m.handle_import_official(req)

    async def test_get_is_preview_and_does_not_save(self):
        resp = await self._call("GET")
        body = json.loads(resp.body.decode())
        self.assertTrue(body["available"])
        self.assertEqual(body["preview"]["brightness"], 55)
        self.assertEqual(body["preview"]["knob"]["mode"], "inference")
        self.assertEqual(self.saved, [])                       # 保存していない
        self.assertEqual(self.m.bridge.cfg["brightness"], 100)  # 変更なし

    async def test_post_applies_and_merges(self):
        resp = await self._call("POST")
        body = json.loads(resp.body.decode())
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(self.m.bridge.cfg["brightness"], 55)
        self.assertEqual(self.m.bridge.cfg["knob"]["mode"], "inference")
        self.assertEqual(self.m.bridge.cfg["analog_stick"]["up"], "sidebar-toggle")
        self.assertIn("applied", body)

    async def test_post_updates_only_learned_keys(self):
        await self._call("POST")
        keys = self.m.bridge.cfg["keys"]
        self.assertEqual(keys["ACT07"]["action"], "approve")   # 学習済み: 更新
        self.assertEqual(keys["ACT07"]["pos"], "p08")          # pos は保持
        self.assertEqual(keys["ACT08"]["action"], "hold")      # 未学習: 据え置き

    async def test_missing_official_returns_404(self):
        self.m.official_mod.load_official = lambda path=None: None
        resp = await self._call("GET")
        self.assertEqual(resp.status, 404)
        self.assertFalse(json.loads(resp.body.decode())["available"])

if __name__ == "__main__":
    unittest.main()
