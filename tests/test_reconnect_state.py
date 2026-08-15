"""#71: 再接続時にジェスチャー途中状態・受信バッファを持ち越さない。"""

import unittest

from server.device import HidAdapter

TIMINGS = {"double_window_ms": 350, "long_min_ms": 600}


def _adapter(events):
    return HidAdapter(0x303A, 0x8360, TIMINGS,
                      on_gesture=lambda k, g: events.append((k, g)))


class ReconnectStateTests(unittest.TestCase):
    def test_reset_clears_gesture_state_and_buffers(self):
        events = []
        a = _adapter(events)
        a._keys["AG01"] = {"pressed_at": 90.0, "long_fired": False}
        a._rxbuf.extend(b"partial-json-fragment")
        a._stick_dir = "up"
        a._reset_input_state()
        self.assertEqual(a._keys, {})
        self.assertEqual(bytes(a._rxbuf), b"")
        self.assertIsNone(a._stick_dir)

    def test_stale_press_fires_spurious_long_without_reset(self):
        """(回帰の前提固定) リセットしなければ残留 pressed_at が偽 long になる。"""
        events = []
        a = _adapter(events)
        a._keys["AG01"] = {"pressed_at": 90.0, "long_fired": False}
        a._tick(100.0)   # 10 秒経過扱い >= long_min 0.6 秒
        self.assertEqual(events, [("AG01", "long")])

    def test_no_spurious_long_after_reset(self):
        events = []
        a = _adapter(events)
        a._keys["AG01"] = {"pressed_at": 90.0, "long_fired": False}
        a._reset_input_state()
        a._tick(100.0)
        self.assertEqual(events, [])

    def test_pending_tap_also_cleared(self):
        """double 待ちで保留中の tap も再接続では発火させない。"""
        events = []
        a = _adapter(events)
        a._keys["ACT01"] = {"pressed_at": None, "pending_tap_at": 95.0,
                            "last_tap": 95.0, "long_fired": False}
        a._reset_input_state()
        a._tick(100.0)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
