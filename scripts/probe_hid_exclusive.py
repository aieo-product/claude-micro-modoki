#!/usr/bin/env python3
"""実機検証: 本家 Codex アプリ共存時の HID 排他/非排他 open 切替を確かめる (#97)。

bridge (server.main) と launchd 常駐を止めてから単独で実行する。各ステップで
open の可否・キー受信の有無を記録し、本家アプリ側の様子は人が観察してメモする。
結果は JSON に書き出す (シリアル等の個体情報は含めない。issue へ貼る用)。

  .venv/bin/python scripts/probe_hid_exclusive.py          # 対話式 (推奨)
  .venv/bin/python scripts/probe_hid_exclusive.py --auto   # 観察なしで open 可否だけ
"""

import argparse
import ctypes
import itertools
import json
import sys
import time

try:
    import hid
except ImportError:
    print("hidapi が必要です: .venv/bin/pip install hidapi", file=sys.stderr)
    sys.exit(1)

VID, PID = 0x303A, 0x8360
CHANNEL_RPC = 0x02
MAX_CHUNK = 61
KEY_WAIT_SEC = 8.0


def set_exclusive(flag: bool) -> bool:
    """macOS 専用: cython-hidapi の C シンボルで排他 (seize) / 非排他を切り替える。"""
    if sys.platform != "darwin":
        return False
    try:
        ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(1 if flag else 0)
        return True
    except (OSError, AttributeError):
        return False


def try_open():
    """open を試み (dev, error) を返す。"""
    if not hid.enumerate(VID, PID):
        return None, "デバイス未検出"
    dev = hid.device()
    try:
        dev.open(VID, PID)
        return dev, None
    except (OSError, ValueError) as e:
        return None, f"open失敗: {e}"


_ids = itertools.count(1)


def rpc(dev, method, params=None):
    payload = {"id": next(_ids), "m": method}
    if params is not None:
        payload["p"] = params
    msg = json.dumps(payload, separators=(",", ":")).encode() + b"\r\n"
    for off in range(0, len(msg), MAX_CHUNK):
        chunk = msg[off:off + MAX_CHUNK]
        report = bytes([0x06, CHANNEL_RPC, len(chunk)]) + chunk
        dev.write(list(report.ljust(64, b"\x00")))


def wait_keys(dev, seconds: float) -> list:
    """seconds の間 vendor チャネルを読み、v.oai.hid のキー名を集める。"""
    buf = bytearray()
    keys = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data = dev.read(64, timeout_ms=50)
        if data and data[0] == 0x06 and data[1] == CHANNEL_RPC:
            buf.extend(bytes(data[3:3 + data[2]]))
            while b"\r\n" in buf:
                line, _, rest = bytes(buf).partition(b"\r\n")
                buf = bytearray(rest)
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("m") == "v.oai.hid":
                    p = obj.get("p") or {}
                    if p.get("act") == 1:
                        keys.append(p.get("k"))
    return keys


def step(results, name, exclusive, interactive, prompt_before=None, key_test=True):
    print(f"\n=== {name} (exclusive={exclusive}) ===")
    if interactive and prompt_before:
        input(prompt_before + " → 準備できたら Enter")
    r = {"step": name, "exclusive": exclusive, "set_exclusive_ok": set_exclusive(exclusive)}
    dev, err = try_open()
    r["open_ok"] = dev is not None
    r["open_error"] = err
    print(f"  open: {'OK' if dev else 'NG'} {err or ''}")
    if dev is not None:
        try:
            rpc(dev, "device.status")  # ハンドシェイク (エージェントモード維持)
            if key_test:
                print(f"  {KEY_WAIT_SEC:.0f} 秒以内にデバイスのキーをいくつか押してください…")
                keys = wait_keys(dev, KEY_WAIT_SEC)
                r["keys_seen"] = keys
                print(f"  受信キー: {keys or 'なし'}")
            if interactive:
                r["official_app_note"] = input("  本家アプリ側の様子 (接続表示/LED/キー反応/エラー) をメモ: ")
        finally:
            dev.close()
            r["closed"] = True
    elif interactive:
        r["official_app_note"] = input("  本家アプリ側の様子をメモ: ")
    results.append(r)
    return r["open_ok"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auto", action="store_true", help="観察入力を求めず open 可否とキー受信だけ記録")
    ap.add_argument("--out", default="probe_hid_exclusive.json")
    args = ap.parse_args()
    interactive = not args.auto
    results = []
    print("前提: bridge (server.main / launchd) は停止済み。本家 Codex(ChatGPT) アプリは起動中。")

    # 1) 非排他 (現行 bridge と同じ) — 本家と同時受信できることの再確認
    step(results, "1_shared_open", False, interactive,
         "本家アプリを起動し、デバイスが本家で「接続済み」になっている状態にする")
    # 2) 本家起動中に排他 open できるか (本命)
    ok = step(results, "2_exclusive_open_while_official_running", True, interactive,
              "本家アプリは起動したまま。この後 bridge 側が排他 open を試みる")
    # 3) 排他 → 非排他へ戻したとき本家が自動復帰するか
    step(results, "3_back_to_shared", False, interactive,
         "本家アプリが復帰する (キー反応・LED が戻る) か観察する")
    if ok and interactive:
        # 4) 排他保持中に本家を再起動したら何が起きるか (30 秒保持)
        print("\n=== 4_hold_exclusive_and_restart_official ===")
        set_exclusive(True)
        dev, err = try_open()
        r = {"step": "4_hold_exclusive_and_restart_official", "open_ok": dev is not None, "open_error": err}
        if dev:
            try:
                rpc(dev, "device.status")
                input("  bridge が排他保持中。本家アプリを再起動して様子を見たら Enter (30 秒以内推奨)")
                r["keys_seen"] = wait_keys(dev, 5.0)
                r["official_app_note"] = input("  本家アプリ側の様子 (エラー/待機/接続済み) をメモ: ")
            finally:
                dev.close()
        results.append(r)
        set_exclusive(False)
    # 5) 非排他で LED を触らずに開いておく — 本家 LED がそのまま出るか
    if interactive:
        print("\n=== 5_shared_open_no_led_write ===")
        set_exclusive(False)
        dev, err = try_open()
        r = {"step": "5_shared_open_no_led_write", "open_ok": dev is not None, "open_error": err}
        if dev:
            try:
                rpc(dev, "device.status")
                input("  bridge は LED を一切書かずに開いています。本家の LED 表示 (エージェント色/枠) がそのまま出ているか、"
                      "また ACT12 (右下) を押して本家側で何か起きるか観察したら Enter")
                r["official_app_note"] = input("  観察メモ: ")
            finally:
                dev.close()
        results.append(r)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"platform": sys.platform, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n結果を {args.out} に保存しました。issue #97 にコメントで貼ってください (コミット禁止)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
