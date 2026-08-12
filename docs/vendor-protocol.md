# Codex Micro Vendor プロトコル解析結果 (T0-4 完了)

解析元: `ChatGPT.app/Contents/Resources/app.asar` 内 `@worklouder/device-kit-oai`
（Work Louder Inc. 製、`rpc_api_oai.js` / `WLDeviceCommImpl` / 型定義 .d.ts）
検証: 実機 `303A:8360` で `v.oai.thstatus` / `v.oai.rgbcfg` に `{"result":{"ok":1}}` 応答確認済み（2026-08-12）

## トランスポート (HID フレーミング)

usage page 0xFF00 / Report ID 6 の 64byte 双方向レポート。

```
フレーム = [0x06, channel, chunkLen, <payload bytes...(最大61)>, 0x00 padding] = 64byte 固定
  channel: 1 = debug ログ / 2 = RPC(JSON)
```

- 送信: JSON文字列 + `\r\n` を **61byte ごとに分割**し、各チャンクを 1 フレームで送る（`sendDataHID`）
- 受信: channel ごとにバッファ結合し、`\n` 終端で 1 メッセージ確定
- 非排他 open が必要（ChatGPT アプリと同時に開くため）。cython-hidapi では
  `hid_darwin_set_open_exclusive(0)` を ctypes で呼ぶ

## 受信メッセージ (device → host)

| method (`m`) | params (`p`) | 意味 |
|---|---|---|
| `v.oai.hid` | `{"k": <keyname>, "act": <0/1/2>, "ag"?: <n>}` | キーイベント。act 1=押下 / 0=離す / 2=リピート(エンコーダー回転) |
| `v.oai.rad` | `{"a": <angle 0..1>, "d": <distance 0..1>}` | ジョイスティック位置 |
| （応答） | `{"result": {...}, "id": <n>, "method": "..."}` | RPC 応答 |

### 観測されたキー名（実機キャプチャ）

- アクションキー: `ACT06`..`ACT12`（下段。ACT01-05 も存在する想定）
- エージェントキー: **`AG00`..`AG05`（0始まり・6個）** ← 重要
- エンコーダー: `ENC_CW`（右回転, act=2）/ `ENC_CC`（左回転, act=2）/ `ENC_CLK`（押し込み, act=1/0）
- ジョイスティック: `v.oai.rad` の angle/distance で通知（押し込みは別途キーイベント）

**⚠ 0始まり/1始まりの注意**: 物理キー名 `AGnn` の nn は 0 始まり。
`v.oai.thstatus` の thread `id` も 0 始まりで、`AGnn` ↔ thread id nn が直接対応する。
一方 bridge の SessionRegistry はエージェントキーを 1..6 で扱う（`set_agent_led(index)` 内部で `id=index-1`）。
したがって物理キー `AG00` = thread id 0 = bridge index 1。変換を1箇所間違えるとキーが1つズレる（実機で確認済み）。

## 送信 RPC (host → device) — すべて `{id, m, p}` 形式・id 必須

### `v.oai.thstatus` — スレッド(エージェントキー)別ライティング
```json
{"id": N, "m": "v.oai.thstatus", "p": [
  {"id": 0, "c": 65280, "b": 1, "e": 1, "s": 0, "sk": 0, "sa": 0}
]}
```
- `id`: スレッド番号（0-origin。エージェントキー1本ずつに対応）
- `c`: packed RGB 整数（例 0x00FF00 = 65280）
- `b`: 輝度 0..1 / `s`: エフェクト速度 0..1
- `e`: エフェクト（下記 enum）
- `sk`: syncKeysLighting（1でキー背面がこのスレッド色に追従）
- `sa`: syncAmbientLighting（1でアンビエントリングが追従）
- 省略したフィールドはデバイス側で「変更なし」

### `v.oai.rgbcfg` — キー背面＋アンビエントリング
```json
{"id": N, "m": "v.oai.rgbcfg", "p": {
  "ambient": {"e": 3, "b": 1, "s": 0.5, "m": 0, "c": 0},
  "keys":    {"e": 1, "b": 1, "s": 0,   "m": 0, "c": 65280}
}}
```
- `ambient` = 外周リング / `keys` = キーキャップ背面
- 各 side: `e`=effect / `b`=brightness 0..1 / `s`=speed 0..1 / `m`=magic(予備) / `c`=packed RGB

### エフェクト enum (OAILightingEffect)
| 値 | 名前 | 説明 |
|---|---|---|
| 0 | off | 消灯 |
| 1 | solid | 単色静止 |
| 2 | snake | 色セグメントが流れる |
| 3 | rainbow | 全色相サイクル |
| 4 | breath | 明滅（ブレス） |
| 5 | gradient | グラデーション |
| 6 | shallowBreath | 明滅（0.5→1、浅い） |

### 純正アプリの状態→色の使い方（参考）
- working 状態: ambient を `snake` + そのステータス色
- selected/pulsing: スレッドを `breath`
- recording: 色 `0x2E8FD7`（3050327）
- idle: off

## ★エージェントモードとハンドシェイク（最重要・実機検証済み）

デバイスは **接続ハンドシェイク＋ハートビートを受けている間だけ「エージェントモード」**になり、
キーイベントを `v.oai.hid` として vendor チャネルに送る。これが途絶えるとキーイベントを送らなくなる
（LED 書き込みだけは常時受け付ける）。

- **接続時**: `device.status`（引数なし）を送る → デバイスがエージェントモードに入る
- **維持**: `device.status` を定期送信（純正アプリは 60s 間隔。本実装は安全側で 30s）
- ハートビートを送らないと、次回開いても既にドーマントで **キーイベントが一切来ない**（実機で確認）
- `device.status` 応答から `version`(FW) / `battery` / `profile_index` / `layer_index` が取れる（FW=v0.4.1 確認）

純正アプリ接続シーケンス（ログ実測）:
```
v.oai.rgbcfg → v.oai.thstatus → device.status → (以後 60s ごと device.status)
```
※ `v.oai.hid`/`v.oai.rad` の "notify handler" 登録はアプリ内部処理であり、デバイスへの RPC ではない。

## Codex(ChatGPT) アプリとの同時利用

- HID は**非排他 open**のため、Codex アプリと bridge は同一デバイスを同時に開ける
- キーイベントは両者にブロードキャストされる（実機確認: アプリ起動中でも bridge で全キー取得できた）
- **競合するのは LED のみ**（両者が thstatus/rgbcfg を送るため取り合いになる）
- モード切替の実装案:
  - 案A: エージェントキーの1つ（例 AG05 長押し）を claude/codex トグルに割当
  - 案B: エージェントキーをゾーン分割（claude 用 / codex 用）
  - 案C: 前面アプリ監視で自動切替（Codex アプリ前面時は bridge の LED 制御を停止）
  - ※ 左下 BLE 切替タッチセンサーは OS/FW レベルの接続切替で、vendor チャネルに通知が来ず制御不可

## 本プロジェクト実装への反映

- `server/device.py` の `HidAdapter` をこのプロトコルで全面実装済み:
  - 受信: vendor JSON をパースして tap/double/long ジェスチャー化（`v.oai.hid`）
  - 送信: `set_agent_led(index, state)` / `set_ambient(state)` で承認状態を LED 反映
  - 状態色: idle=青微灯 / pending=黄breath / accept=緑 / fallback=紫 / deny=赤（設計踏襲）
  - **ハンドシェイク+ハートビート実装済み**: `_handshake()` で接続時に device.status、
    `_read_loop` 内で 30s ごとに device.status を再送してエージェントモードを維持
- **Phase 4（QMK 自前ビルド）は不要** — 純正ファームの vendor チャネルで読み書き両方できる
- 注意: LED は Codex アプリと競合する。上記モード切替（案A/B/C）で住み分ける
```
