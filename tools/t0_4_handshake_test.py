#!/usr/bin/env python3
"""アプリの接続ハンドシェイク+ハートビートを再現してキーイベントが復活するか検証。
ChatGPT アプリは閉じたまま実行すること。30秒。"""
import ctypes, itertools, json, threading, time
import hid

ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(0)
dev = hid.device()
dev.open(0x303A, 0x8360)
print("open 成功", flush=True)

ids = itertools.count(1)
lock = threading.Lock()
rxbuf = bytearray()

def send(method, params=None):
    payload = {"id": next(ids), "m": method}
    if params is not None:
        payload["p"] = params
    msg = json.dumps(payload, separators=(",", ":")).encode() + b"\r\n"
    with lock:
        for off in range(0, len(msg), 61):
            ch = msg[off:off+61]
            dev.write(list((bytes([0x06, 0x02, len(ch)]) + ch).ljust(64, b"\x00")))
    print(f"  -> 送信 {method}", flush=True)

off_side = {"e": 0, "b": 0, "s": 0, "m": 0, "c": 0}
# 1) ハンドシェイク (アプリの接続シーケンス再現)
send("v.oai.rgbcfg", {"ambient": off_side, "keys": off_side})
time.sleep(0.1)
send("v.oai.thstatus", [{"id": i, "c": 0x0A2A6E, "b": 0.3, "e": 1, "s": 0} for i in range(6)])
time.sleep(0.1)
send("device.status")

# 2) ハートビート: device.status を 5 秒ごと
def heartbeat():
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30:
        time.sleep(5)
        send("device.status")
threading.Thread(target=heartbeat, daemon=True).start()

print("30秒間キーを押してください。キーイベントが来るか観察...", flush=True)
seen = {}
t0 = time.monotonic()
while time.monotonic() - t0 < 30:
    with lock:
        data = dev.read(64, timeout_ms=50)
    if not data:
        continue
    rid = data[0]
    seen[rid] = seen.get(rid, 0) + 1
    if rid == 6:
        rxbuf.extend(bytes(data[3:3+data[2]]))
        while b"\n" in rxbuf:
            line, _, rest = rxbuf.partition(b"\n")
            rxbuf[:] = rest
            t = line.strip()
            if not t: continue
            try: obj = json.loads(t)
            except ValueError: continue
            m = obj.get("m") or obj.get("method")
            if m in ("v.oai.hid", "v.oai.rad"):
                print(f"    ★キー: {obj.get('p')}", flush=True)
            elif m == "device.status":
                r = obj.get("result", {})
                print(f"    status: fw={r.get('version')} batt={r.get('battery')}", flush=True)
    else:
        tag = {1:"KBD",2:"CONSUMER",3:"MOUSE",4:"GAMEPAD"}.get(rid, f"rid{rid}")
        print(f"    [{tag}] {' '.join(f'{b:02X}' for b in data[:12])}", flush=True)

print("\n--- Report ID 別 ---", flush=True)
for rid, n in sorted(seen.items()):
    print(f"  rid {rid}: {n}", flush=True)
dev.close()
