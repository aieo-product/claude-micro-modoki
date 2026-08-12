#!/usr/bin/env python3
"""T0-3: Codex Micro の HID インターフェース列挙・raw HID 検証スクリプト

Usage:
    .venv/bin/python tools/t0_3_hid_probe.py              # 全 HID デバイス列挙 + 判定
    .venv/bin/python tools/t0_3_hid_probe.py --open       # raw HID 候補を open/close して疎通確認
    .venv/bin/python tools/t0_3_hid_probe.py --via-probe  # VIA プロトコルバージョン取得を試行
    .venv/bin/python tools/t0_3_hid_probe.py --vid 0x574C # 特定 VID に絞る

判定基準:
    usage_page 0xFF60 / usage 0x61  -> QMK raw HID (VIA もこの上に乗る) = Phase 4 スキップ濃厚
    usage_page 0xFF31 / usage 0x74  -> QMK console (hid_listen)
    usage_page >= 0xFF00            -> その他ベンダー定義 (要個別調査)

macOS 注意: raw HID の open にはターミナルアプリへの「入力監視」権限が必要な場合がある。
open が権限エラーで失敗したら システム設定 > プライバシーとセキュリティ > 入力監視 を確認。
"""

import argparse
import sys

import hid  # cython-hidapi (pip install hidapi)

# QMK 系ボードでよく使われる識別子
QMK_RAWHID_USAGE_PAGE = 0xFF60
QMK_RAWHID_USAGE = 0x61
QMK_CONSOLE_USAGE_PAGE = 0xFF31
QMK_CONSOLE_USAGE = 0x74
WORK_LOUDER_VID = 0x574C  # QMK 上の work_louder ボード群の vendor ID ("WL")

# VIA プロトコル: コマンド 0x01 = get_protocol_version (読み取りのみ・安全)
VIA_CMD_GET_PROTOCOL_VERSION = 0x01
RAW_REPORT_SIZE = 32  # QMK RAW_EPSIZE のデフォルト。64 の機種もあるため両方試す


def classify(dev: dict) -> str:
    up, us = dev["usage_page"], dev["usage"]
    if up == QMK_RAWHID_USAGE_PAGE and us == QMK_RAWHID_USAGE:
        return "RAW_HID (QMK/VIA)"
    if up == QMK_CONSOLE_USAGE_PAGE and us == QMK_CONSOLE_USAGE:
        return "QMK console"
    if up >= 0xFF00:
        return "vendor-defined"
    if up == 0x01 and us == 0x06:
        return "keyboard"
    if up == 0x01 and us == 0x02:
        return "mouse"
    if up == 0x0C:
        return "consumer"
    return ""


def looks_like_target(dev: dict) -> bool:
    if dev["vendor_id"] == WORK_LOUDER_VID:
        return True
    blob = f"{dev.get('manufacturer_string') or ''} {dev.get('product_string') or ''}".lower()
    return any(k in blob for k in ("work louder", "worklouder", "codex", "creator micro"))


def enumerate_devices(vid_filter: int | None):
    devs = hid.enumerate()
    if vid_filter is not None:
        devs = [d for d in devs if d["vendor_id"] == vid_filter]
    devs.sort(key=lambda d: (d["vendor_id"], d["product_id"], d.get("interface_number", -1)))
    return devs


def print_devices(devs: list[dict]) -> list[dict]:
    """列挙結果を表示し、raw HID インターフェースのリストを返す

    QMK 標準の 0xFF60 に加え、対象デバイス上の vendor-defined ページ (>=0xFF00) も
    独自プロトコルの可能性があるため候補に含める。
    """
    raw_candidates = []
    cur_key = None
    for d in devs:
        key = (d["vendor_id"], d["product_id"])
        if key != cur_key:
            cur_key = key
            mark = "  <-- 対象デバイス候補" if looks_like_target(d) else ""
            print(f"\n[{d['vendor_id']:04X}:{d['product_id']:04X}] "
                  f"{d.get('manufacturer_string') or '?'} / {d.get('product_string') or '?'}{mark}")
        tag = classify(d)
        is_raw = tag.startswith("RAW_HID") or (looks_like_target(d) and d["usage_page"] >= 0xFF00)
        if is_raw:
            raw_candidates.append(d)
        print(f"    if#{d.get('interface_number', -1):>2}  "
              f"usage_page=0x{d['usage_page']:04X} usage=0x{d['usage']:02X}"
              f"  {tag}{'  ***' if is_raw else ''}")
    return raw_candidates


def try_open(dev: dict) -> "hid.device | None":
    h = hid.device()
    try:
        h.open_path(dev["path"])
        return h
    except (OSError, ValueError) as e:
        print(f"    open 失敗: {e}")
        return None


def via_probe(h: "hid.device") -> bool:
    """VIA get_protocol_version を送って応答を確認。成功なら True"""
    for size in (RAW_REPORT_SIZE, 64):
        report = [0x00] + [VIA_CMD_GET_PROTOCOL_VERSION] + [0x00] * (size - 1)
        try:
            n = h.write(report)
            if n <= 0:
                continue
            resp = h.read(size, timeout_ms=1000)
            if resp and resp[0] == VIA_CMD_GET_PROTOCOL_VERSION:
                ver = (resp[1] << 8) | resp[2]
                print(f"    VIA 応答あり (report {size}byte): protocol version = 0x{ver:04X}")
                return True
            print(f"    report {size}byte: 応答なし or 不一致 resp={resp[:4] if resp else resp}")
        except (OSError, ValueError) as e:
            print(f"    report {size}byte: {e}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vid", type=lambda s: int(s, 0), default=None, help="vendor ID で絞り込み (例: 0x574C)")
    ap.add_argument("--open", action="store_true", help="raw HID 候補を open/close して疎通確認")
    ap.add_argument("--via-probe", action="store_true", help="VIA プロトコルバージョン取得を試行 (--open を含む)")
    args = ap.parse_args()

    devs = enumerate_devices(args.vid)
    if not devs:
        print("HID デバイスが見つかりません" + (f" (VID=0x{args.vid:04X})" if args.vid else ""))
        return 1

    print(f"HID インターフェース {len(devs)} 件:")
    raw_candidates = print_devices(devs)

    print("\n" + "=" * 60)
    if not raw_candidates:
        print("判定: raw HID (usage_page 0xFF60) インターフェースなし")
        print("  -> 対象デバイス接続済みでこの結果なら Phase 4 (QMK 自前ビルド) が必要")
        return 0

    print(f"判定: raw HID インターフェース {len(raw_candidates)} 件検出 ***")
    for d in raw_candidates:
        print(f"  [{d['vendor_id']:04X}:{d['product_id']:04X}] if#{d.get('interface_number', -1)} "
              f"{d.get('product_string') or '?'}")

    if args.open or args.via_probe:
        print("\nopen テスト:")
        for d in raw_candidates:
            print(f"  [{d['vendor_id']:04X}:{d['product_id']:04X}] if#{d.get('interface_number', -1)}")
            h = try_open(d)
            if h is None:
                continue
            print("    open 成功")
            if args.via_probe:
                via_probe(h)
            h.close()
    else:
        print("\n次: --open で疎通確認、--via-probe で VIA プロトコル確認 (T0-4 への布石)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
