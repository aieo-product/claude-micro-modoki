#!/usr/bin/env python3
"""HidAdapter の統合テスト: キーイベント(ジェスチャー)受信と LED 反映を実機で確認。

30 秒間、押されたキーに応じて:
  tap    -> そのキーが AGxx なら該当エージェント LED を緑
  long   -> 赤
  double -> 紫
コンソールにジェスチャーを出力する。
"""
import re
import sys
import time

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from server.device import HidAdapter  # noqa: E402

TIMINGS = {"tap_max_ms": 400, "double_window_ms": 350, "long_min_ms": 600}


def agent_index(key: str):
    """物理キー AGnn (0始まり) -> bridge の 1始まりエージェント番号。AG00=1, AG05=6"""
    m = re.match(r"AG0?(\d+)", key)
    return int(m.group(1)) + 1 if m else None


def main():
    def on_gesture(key, gesture):
        print(f"  [{time.strftime('%H:%M:%S')}] {key:8s} -> {gesture}")
        idx = agent_index(key)
        if idx and 1 <= idx <= 6:
            adapter.set_agent_led(idx, {"tap": "accept", "long": "deny",
                                        "double": "fallback"}[gesture])

    adapter = HidAdapter(0x303A, 0x8360, TIMINGS,
                         on_gesture=on_gesture,
                         on_raw_key=lambda k: print(f"    (press {k})", flush=True))
    # 生の受信メッセージも表示して切り分ける
    _orig = adapter._handle_message
    def _traced(obj, now):
        m = obj.get("m") or obj.get("method")
        if m == "v.oai.hid":
            print(f"    raw hid: {obj.get('p')}", flush=True)
        _orig(obj, now)
    adapter._handle_message = _traced
    adapter.start()
    time.sleep(0.5)
    print("状態:", adapter.status)
    print("30 秒間、キーを操作してください (tap/長押し/ダブルタップ)...")
    time.sleep(30)
    adapter.stop()


if __name__ == "__main__":
    main()
