#!/usr/bin/env python3
"""T0-4: vendor JSON プロトコルの request/response 探索

フレーム形式 (device→host 観測から推定):
  [0x06(report ID), 0x02(チャネル?), len, ASCII JSON, 0x0D 0x0A, padding]

host→device も同形式と仮定して問い合わせを送り、応答を観測する。
"""

import ctypes
import json
import sys
import time

import hid

ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(0)


def frame(payload: dict, channel: int = 0x02) -> list[int]:
    body = json.dumps(payload, separators=(",", ":")).encode() + b"\r\n"
    assert len(body) <= 61, "1 レポートに収まらない"
    buf = bytes([0x06, channel, len(body) - 2]) + body  # len は \r\n を除く長さ
    return list(buf.ljust(64, b"\x00"))  # 先頭バイト = report ID、総計 64 バイト


def parse(data: list[int]) -> str | None:
    if not data or data[0] != 0x06:
        return None
    ln = data[2]
    try:
        return bytes(data[3:3 + ln]).decode("ascii", errors="replace")
    except Exception:
        return None


def probe(h, payload: dict, wait_sec: float = 2.0, channel: int = 0x02):
    print(f"\n>>> 送信 (ch={channel:#04x}): {json.dumps(payload, separators=(',', ':'))}")
    n = h.write(frame(payload, channel))
    print(f"    write 戻り値: {n}")
    t0 = time.monotonic()
    my_id = payload.get("id")
    while time.monotonic() - t0 < wait_sec:
        data = h.read(64, timeout_ms=100)
        if not data:
            continue
        txt = parse(data)
        if txt is None:
            continue
        # 自分の id への応答を強調表示。それ以外 (アプリ宛て応答やイベント) は参考表示
        try:
            obj = json.loads(txt)
            mark = " <-- 自分の応答!" if obj.get("id") == my_id else ""
        except Exception:
            mark = ""
        print(f"    recv: {txt}{mark}")


def main():
    h = hid.device()
    h.open(0x303A, 0x8360)
    print("open 成功")

    # 1) 観測済みメソッドを id 付きで問い合わせ (アプリが常時送っている status 系 = 安全)
    probe(h, {"id": 90001, "m": "v.oai.thstatus"})
    probe(h, {"id": 90002, "m": "v.oai.thstatus", "p": {}})
    # 2) rgbcfg を引数なしで問い合わせ → 現在設定が返れば書き込み schema がわかる
    probe(h, {"id": 90003, "m": "v.oai.rgbcfg"})
    probe(h, {"id": 90004, "m": "v.oai.rgbcfg", "p": {}})

    h.close()


if __name__ == "__main__":
    main()
