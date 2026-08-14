"""段階2(#35): ノブ/ジョイスティックの検出→ディスパッチのテスト。"""

import unittest
from unittest import mock

from server import device as device_mod
from server import main as main_mod


class StickQuantizeTests(unittest.TestCase):
    """v.oai.rad のアナログ値 → 4方向ジェスチャの量子化/デバウンス。"""

    def _adapter(self):
        events = []
        a = device_mod.HidAdapter(
            0x303A, 0x8360,
            {"tap_max_ms": 400, "double_window_ms": 350, "long_min_ms": 600},
            on_gesture=lambda k, g: events.append((k, g)),
        )
        return a, events

    def test_direction_mapping(self):
        # 実測: 右≈0.0 / 下≈0.25 / 左≈0.5 / 上≈0.75
        cases = {0.0: "STICK_RIGHT", 0.25: "STICK_DOWN", 0.5: "STICK_LEFT", 0.75: "STICK_UP"}
        for angle, expected in cases.items():
            a, events = self._adapter()
            a._handle_stick(angle, 1.0)
            self.assertEqual(events, [(expected, "tap")], f"angle={angle}")

    def test_debounce_fires_once_until_release(self):
        a, events = self._adapter()
        a._handle_stick(0.75, 1.0)   # 上: 発火
        a._handle_stick(0.75, 0.9)   # まだ傾倒中: 再発火しない
        a._handle_stick(0.75, 0.7)
        self.assertEqual(len(events), 1)
        a._handle_stick(0.0, 0.1)    # 中央付近: 再アーム (方向なし)
        a._handle_stick(0.75, 1.0)   # 再び上: 発火
        self.assertEqual([e[0] for e in events], ["STICK_UP", "STICK_UP"])

    def test_deadzone_no_fire(self):
        a, events = self._adapter()
        a._handle_stick(0.75, 0.5)   # ACTIVE(0.6)未満: 発火しない
        self.assertEqual(events, [])

    def test_invalid_payload_ignored(self):
        a, events = self._adapter()
        a._handle_stick(None, 1.0)
        a._handle_stick(0.5, None)
        self.assertEqual(events, [])


class KnobStickDispatchTests(unittest.TestCase):
    """_on_gesture が ENC_*/STICK_* を config へディスパッチする。"""

    def _bridge(self):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        b._learn_future = None
        b.cfg = {
            "mode": {"toggle_key": "ACT12", "current": "cmux-claude"},
            "keys": {},
            "analog_stick": {"up": "plan-mode", "right": "forward",
                             "down": "sidebar-toggle", "left": "back"},
            "knob": {"mode": "scroll", "rotate_cw": "diff", "rotate_ccw": "git",
                     "click": "approve", "long_press": "reject"},
        }
        b.mode = "cmux-claude"
        calls = []
        b.run_action = lambda action, gesture: calls.append((action, gesture))
        return b, calls

    def test_stick_direction_dispatch(self):
        b, calls = self._bridge()
        b._on_gesture("STICK_UP", "tap")
        b._on_gesture("STICK_RIGHT", "tap")
        self.assertEqual(calls, [("plan-mode", "tap"), ("forward", "tap")])

    def test_knob_scroll_preset(self):
        b, calls = self._bridge()
        b._on_gesture("ENC_CW", "tap")
        b._on_gesture("ENC_CC", "tap")
        self.assertEqual(calls, [("scroll-down", "tap"), ("scroll-up", "tap")])

    def test_knob_custom_rotation_and_click(self):
        b, calls = self._bridge()
        b.cfg["knob"]["mode"] = "custom"
        b._on_gesture("ENC_CW", "tap")
        b._on_gesture("ENC_CLK", "tap")
        b._on_gesture("ENC_CLK", "long")
        self.assertEqual(calls, [("diff", "tap"), ("approve", "tap"), ("reject", "long")])

    def test_knob_inference_and_inputnav_presets(self):
        b, calls = self._bridge()
        b.cfg["knob"]["mode"] = "inference"
        b._on_gesture("ENC_CW", "tap")
        b.cfg["knob"]["mode"] = "input-nav"
        b._on_gesture("ENC_CC", "tap")
        self.assertEqual(calls, [("inference-effort", "tap"), ("input-nav", "tap")])


class ControlScopeActionTests(unittest.TestCase):
    """run_action が control scope を全モードで許可する (#35)。"""

    def _bridge(self):
        b = main_mod.Bridge.__new__(main_mod.Bridge)
        b.mode = "cmux-claude"
        execed = []
        b._exec_action = lambda a: execed.append(a)
        b._resolve_selected_or_oldest = lambda r: None
        return b, execed

    def test_control_action_executes_in_any_family(self):
        b, execed = self._bridge()
        b.run_action("forward", "tap")       # control scope
        b.run_action("sidebar-toggle", "tap")
        self.assertEqual(execed, ["forward", "sidebar-toggle"])


if __name__ == "__main__":
    unittest.main()
