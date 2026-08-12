#!/usr/bin/env python3
"""LED 目視確認デモ: 6 エージェントキーを承認状態色で順に点灯。"""
import sys
import time

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from server.device import HidAdapter  # noqa: E402

a = HidAdapter(0x303A, 0x8360, {"tap_max_ms": 400, "double_window_ms": 350, "long_min_ms": 600})
a.start()
time.sleep(0.6)
print("状態:", a.status)

for state in ["accept", "fallback", "deny", "pending", "idle"]:
    print(f"全キー -> {state}")
    a.set_all_agent_leds({i: state for i in range(1, 7)})
    time.sleep(1.5)

print("1本ずつ虹色 (thread id 0-5)")
colors = ["deny", "pending", "accept", "fallback", "idle", "deny"]
a.set_all_agent_leds({i + 1: colors[i] for i in range(6)})
time.sleep(3)

print("消灯")
a.set_all_agent_leds({i: "off" for i in range(1, 7)})
time.sleep(1)
a.stop()
