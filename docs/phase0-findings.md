# Phase 0 実機検証 — 調査結果

検証日: 2026-08-12 / 環境: Mac Studio (Darwin 24.3.0), Python 3.14.5, cython-hidapi 0.15.0

## T0-3: HID インターフェース列挙 — 完了

スクリプト: `tools/t0_3_hid_probe.py`（venv: `.venv`、`pip install hidapi`）

### デバイス識別

| 項目 | 値 |
|------|-----|
| VID:PID | `0x303A:0x8360` |
| Manufacturer / Product | Work Louder / Codex Micro |
| VID の所有者 | **Espressif Systems**（= ESP32 系 MCU。AVR/RP2040 の QMK 標準構成ではない可能性が高い） |
| USB | Full Speed (12 Mb/s)、bus power 500mA（Serial は個体固有のため記載省略） |

### HID 構成（単一インターフェース・複合レポートディスクリプタ、全 275 バイト）

| Report ID | Usage Page / Usage | 内容 |
|-----------|--------------------|------|
| 1 | 0x01 / 0x06 | キーボード |
| 2 | 0x0C / 0x01 | Consumer（メディアキー） |
| 3 | 0x01 / 0x02 | マウス（ホイール+水平ホイール付き → ロータリーエンコーダー用途か） |
| 4 | 0x01 / 0x05 | ゲームパッド（X/Y/Z/Rx/Ry/Rz + ハット + 32 ボタン → ジョイスティック） |
| 6 | **0xFF00 / 0x01** | **vendor-defined: Input 63byte + Output 63byte の双方向 raw チャネル** |

vendor チャネルのディスクリプタ抜粋（末尾）:

```
06 00 FF  Usage Page (Vendor 0xFF00)
09 01     Usage (0x01)
A1 01     Collection (Application)
85 06       Report ID (6)
09 02       Usage (0x02)
75 08 95 3F 81 02   Input:  63 bytes
09 03       Usage (0x03)
75 08 95 3F 91 02   Output: 63 bytes
C0        End Collection
```

→ ホスト→デバイス 64 バイト（Report ID 0x06 + 63 バイト payload）の書き込みチャネルが純正ファームに存在する。
設計済みの raw HID プロトコル（SET_LED / CLEAR_ALL / KEY_EVENT）はこの上に載せられる可能性が高い。

### QMK / VIA について

- **usage page 0xFF60（QMK raw HID / VIA 標準）は存在しない** → usevia.app での標準 VIA プロトコルは不可の公算大（T0-2 で要確認だが期待薄）
- 0xFF00 チャネルは Work Louder「Input」アプリの通信路と推定。プロトコルは未公開のため、T0-4 で
  (a) Input アプリの通信を観察（Wireshark + USB キャプチャ等）するか
  (b) Work Louder のファーム/アプリ公開情報を調査する

### ブロッカー: macOS 入力監視権限（TCC）

open テストは **`open failed` で失敗**。原因切り分け済み:

- キーボード usage を含まない HID デバイス（Apple Keyboard Backlight 等）は open 成功 → hidapi・サンドボックスの問題ではない
- Codex Micro は全 usage が単一 HID サービス（同一 path）に同居しており、open にはキーボードデバイス扱いで
  **入力監視（Input Monitoring）権限**が必要
- 対処: システム設定 > プライバシーとセキュリティ > **入力監視** に、Claude Code を動かしているターミナルアプリ
  （Terminal.app / iTerm2 等）を追加 → ターミナル再起動 → `.venv/bin/python tools/t0_3_hid_probe.py --vid 0x303A --open` を再実行

## T0-5 判定への現時点の見立て

- 純正ファームに 64 バイト双方向 raw チャネルあり → **プロトコルさえ判明すれば Phase 4（QMK 自前ビルド）はスキップできる可能性が高い**
- ただし ESP32 ベース（VID 0x303A）のため、仮に自前ファームが必要になった場合は QMK ではなく
  Work Louder 提供のファームウェア基盤（または ESP32 HID スタック）を調べる必要がある → T4-1 の前提を要修正

## 残タスク（Phase 0）

- [ ] 入力監視権限の付与（ユーザー操作）→ open 再テスト
- [ ] T0-1: Work Louder「Input」アプリでの認識確認
- [ ] T0-2: usevia.app での認識確認（期待薄だが確認）
- [ ] T0-4: Report ID 0x06 チャネルのプロトコル解明 + LED 1 色変更検証
