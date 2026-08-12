#!/usr/bin/env python3
"""T0-3/T0-4: Codex Micro のキー入力レポートを一定時間キャプチャして書き出す

Usage: .venv/bin/python tools/t0_capture_keys.py [秒数] [出力ファイル]
キャプチャ中に実機のキー・ノブ・ジョイスティックを操作すること。
"""

import ctypes
import sys
import time

import hid

ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(0)

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 30
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/codex_micro_capture.log"

h = hid.device()
h.open(0x303A, 0x8360)
print(f"open 成功。{DURATION} 秒間キャプチャします。実機を操作してください...")

lines = []
t0 = time.monotonic()
last = None
while time.monotonic() - t0 < DURATION:
    data = h.read(64, timeout_ms=100)
    if not data:
        continue
    hexs = " ".join(f"{b:02X}" for b in data)
    if hexs == last:
        continue  # 同一レポート連続は間引く
    last = hexs
    line = f"{time.monotonic() - t0:7.3f}s rid={data[0]:02X} len={len(data)} | {hexs}"
    lines.append(line)
    print(line, flush=True)

h.close()
with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"完了: {len(lines)} レポートを {OUT} に保存")
