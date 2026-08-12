#!/usr/bin/env python3
"""T0-4: LED 制御の実証

解明済みプロトコル (ChatGPT.app app.asar / @worklouder/device-kit-oai より):
  フレーム: [0x06, 0x02, len, <ASCII JSON>, 0x0D, 0x0A, 0x00...] = 64byte
  - v.oai.thstatus (ThreadsLighting): エージェントキー(スレッド)別ライティング
      params = [{id, c, b, e, s, sk, sa}, ...]
      id=スレッド番号 / c=packed RGB int / b=輝度0..1 / e=effect / s=speed0..1
      sk=syncKeysLighting(0/1) / sa=syncAmbientLighting(0/1)
  - v.oai.rgbcfg (RgbConfig): キー背面＋アンビエントリング
      params = {ambient:{e,b,s,m,c}, keys:{e,b,s,m,c}}
  effect enum: 0=off 1=solid 2=snake 3=rainbow 4=breath 5=gradient 6=shallowBreath

Usage:
  .venv/bin/python tools/t0_4_led_test.py threads   # 6スレッドを色付け
  .venv/bin/python tools/t0_4_led_test.py rainbow    # アンビエント虹
  .venv/bin/python tools/t0_4_led_test.py off        # 消灯
"""
import ctypes
import itertools
import json
import sys
import time

import hid

ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(0)
_ids = itertools.count(50000)


CHANNEL_RPC = 0x02
MAX_CHUNK = 61


def send(h, payload: dict):
    """JSON + CRLF を 61byte ごとに分割し、各 64byte レポートで送信 (app.asar sendDataHID 準拠)"""
    msg = json.dumps(payload, separators=(",", ":")).encode() + b"\r\n"
    for off in range(0, len(msg), MAX_CHUNK):
        chunk = msg[off:off + MAX_CHUNK]
        report = bytes([0x06, CHANNEL_RPC, len(chunk)]) + chunk
        h.write(list(report.ljust(64, b"\x00")))


def rpc(h, method: str, params, wait=0.4):
    pid = next(_ids)
    send(h, {"id": pid, "m": method, "p": params})
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        d = h.read(64, timeout_ms=80)
        if d and d[0] == 0x06:
            txt = bytes(d[3:3 + d[2]]).decode("ascii", "replace")
            if f'"id":{pid}' in txt:
                return txt
    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "threads"
    h = hid.device()
    h.open(0x303A, 0x8360)
    print(f"open 成功 / mode={mode}")

    COLORS = [0xFF0000, 0xFF7F00, 0x00FF00, 0x00FFFF, 0x0000FF, 0xB000FF]
    if mode == "threads":
        # 6 エージェントキーを個別色で solid 点灯 (id を 0..5 で試す)
        threads = [{"id": i, "c": COLORS[i], "b": 1, "e": 1, "s": 0} for i in range(6)]
        print("送信:", rpc(h, "v.oai.thstatus", threads))
    elif mode == "rainbow":
        cfg = {"ambient": {"e": 3, "b": 1, "s": 0.5, "m": 0, "c": 0},
               "keys": {"e": 4, "b": 1, "s": 0.4, "m": 0, "c": 0x00FF00}}
        print("送信:", rpc(h, "v.oai.rgbcfg", cfg))
    elif mode == "off":
        off = {"e": 0, "b": 0, "s": 0, "m": 0, "c": 0}
        print("送信:", rpc(h, "v.oai.rgbcfg", {"ambient": off, "keys": off}))
        print("送信:", rpc(h, "v.oai.thstatus",
                          [{"id": i, "c": 0, "b": 0, "e": 0, "s": 0} for i in range(6)]))
    print("完了。5 秒間保持します（アプリが上書きする場合あり）")
    time.sleep(5)
    h.close()


if __name__ == "__main__":
    main()
