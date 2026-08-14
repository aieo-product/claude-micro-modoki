# vendor プロトコル（HID）

Codex Micro 純正ファームの vendor チャネル（**usage page 0xFF00 / Report ID 6**）で流れる JSON-RPC の解析結果です。ChatGPT.app 内の `@worklouder/device-kit-oai`（Work Louder 製）を解析し、実機 `303A:8360` で動作確認済み（2026-08-12）。

::: tip この解明が意味すること
純正ファームのまま **LED 制御とキー読み取りの両方**ができるため、QMK 等の自前ファームビルド（旧 Phase 4）は不要になりました。
:::

## トランスポート（HID フレーミング）

64byte 固定の双方向レポートに、改行終端の JSON を 61byte ごとに分割して載せます。

<div class="cm-figure">
<svg viewBox="0 0 760 150" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="HIDフレーム構造">
  <rect class="box-accent" x="20" y="40" width="90" height="50" rx="8"/>
  <text x="65" y="62" text-anchor="middle" class="t-mono">0x06</text>
  <text x="65" y="80" text-anchor="middle" class="t-small t-muted">Report ID</text>
  <rect class="box-blue" x="110" y="40" width="90" height="50" rx="8"/>
  <text x="155" y="62" text-anchor="middle" class="t-mono">channel</text>
  <text x="155" y="80" text-anchor="middle" class="t-small t-muted">1=log / 2=RPC</text>
  <rect class="box-blue" x="200" y="40" width="90" height="50" rx="8"/>
  <text x="245" y="62" text-anchor="middle" class="t-mono">chunkLen</text>
  <text x="245" y="80" text-anchor="middle" class="t-small t-muted">payload 長</text>
  <rect class="box" x="290" y="40" width="330" height="50" rx="8"/>
  <text x="455" y="62" text-anchor="middle" class="t-mono">payload（最大 61 byte）</text>
  <text x="455" y="80" text-anchor="middle" class="t-small t-muted">JSON 文字列 + \r\n を分割して格納</text>
  <rect class="box" x="620" y="40" width="120" height="50" rx="8" stroke-dasharray="4 3"/>
  <text x="680" y="62" text-anchor="middle" class="t-mono">0x00 …</text>
  <text x="680" y="80" text-anchor="middle" class="t-small t-muted">padding</text>
  <text x="380" y="125" text-anchor="middle" class="t-mono t-muted t-small">= 64 byte 固定フレーム。受信側は channel ごとにバッファ結合し \n 終端で 1 メッセージ確定</text>
</svg>
</div>

- 非排他 open が必要（公式アプリと同時に開くため）。cython-hidapi では `hid_darwin_set_open_exclusive(0)` を ctypes で呼ぶ
- キーイベントは開いている全ホストにブロードキャストされる。**競合するのは LED のみ**

## 受信メッセージ（device → host）

| method (`m`) | params (`p`) | 意味 |
|---|---|---|
| `v.oai.hid` | `{"k": キー名, "act": 0/1/2, "ag"?: n}` | キーイベント。1=押下 / 0=離す / 2=リピート（エンコーダー回転） |
| `v.oai.rad` | `{"a": 0..1, "d": 0..1}` | ジョイスティック位置（角度・距離） |
| （応答） | `{"result": {…}, "id": n, "method": "…"}` | RPC 応答 |

観測されたキー名: アクションキー `ACT06`〜`ACT12`、エージェントキー **`AG00`〜`AG05`（0始まり・6個）**、エンコーダー `ENC_CW` / `ENC_CC` / `ENC_CLK`。

::: warning 0始まり / 1始まりの罠
物理キー名 `AGnn` と `v.oai.thstatus` の thread `id` は **0始まり**、bridge の SessionRegistry は **1始まり**（`set_agent_led(index)` 内部で `id = index - 1`）。変換を1箇所間違えるとキーが1つズレます（実機で確認済みの事故ポイント）。
:::

## 送信 RPC（host → device）

すべて `{id, m, p}` 形式で `id` 必須です。

### `v.oai.thstatus` — エージェントキー別ライティング

```json
{"id": 1, "m": "v.oai.thstatus", "p": [
  {"id": 0, "c": 65280, "b": 1, "e": 1, "s": 0, "sk": 0, "sa": 0}
]}
```

| フィールド | 意味 |
|---|---|
| `id` | スレッド番号（0始まり。エージェントキー1本ずつに対応） |
| `c` | packed RGB 整数（例 `0x00FF00` = 65280） |
| `b` / `s` | 輝度 0..1 / エフェクト速度 0..1 |
| `e` | エフェクト（下表） |
| `sk` / `sa` | キー背面 / アンビエントリングの追従（1で ON） |

### `v.oai.rgbcfg` — キー背面 + アンビエントリング

```json
{"id": 2, "m": "v.oai.rgbcfg", "p": {
  "ambient": {"e": 3, "b": 1, "s": 0.5, "m": 0, "c": 0},
  "keys":    {"e": 1, "b": 1, "s": 0,   "m": 0, "c": 65280}
}}
```

### エフェクト enum（OAILightingEffect）

| 値 | 名前 | 見え方 |
|---|---|---|
| 0 | off | 消灯 |
| 1 | solid | 単色静止 |
| 2 | snake | 色セグメントが流れる |
| 3 | rainbow | 全色相サイクル |
| 4 | breath | 明滅 |
| 5 | gradient | グラデーション |
| 6 | shallowBreath | 浅い明滅（0.5→1） |

## ★エージェントモードとハンドシェイク（最重要）

デバイスは**接続ハンドシェイク + ハートビートを受けている間だけ「エージェントモード」**になり、キーイベントを vendor チャネルへ送ります。これを怠ると、LED 書き込みはできるのに**キーイベントが一切来ない**状態になります（実機で確認）。

<div class="cm-figure">
<svg viewBox="0 0 700 170" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ハンドシェイクシーケンス">
  <defs>
    <marker id="cm-arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" opacity=".6"/></marker>
  </defs>
  <text x="140" y="26" text-anchor="middle" font-weight="700">bridge</text>
  <text x="560" y="26" text-anchor="middle" font-weight="700">Codex Micro</text>
  <line x1="140" y1="36" x2="140" y2="155" stroke="var(--cm-line)" stroke-width="1.5"/>
  <line x1="560" y1="36" x2="560" y2="155" stroke="var(--cm-line)" stroke-width="1.5"/>
  <path class="arrow" d="M144 55 H 552"/>
  <text x="350" y="47" text-anchor="middle" class="t-mono t-small t-muted">接続時: device.status → エージェントモード ON</text>
  <path class="arrow" d="M556 90 H 148"/>
  <text x="350" y="82" text-anchor="middle" class="t-mono t-small t-muted">応答: version / battery / profile_index / layer_index</text>
  <path class="arrow" d="M144 130 H 552"/>
  <text x="350" y="122" text-anchor="middle" class="t-mono t-small t-muted">以後 30秒ごとに device.status 再送（純正アプリは 60秒）</text>
</svg>
</div>

純正アプリの接続シーケンス（ログ実測）: `v.oai.rgbcfg` → `v.oai.thstatus` → `device.status` →（以後 60秒ごと `device.status`）

## 公式アプリとの同時利用

- HID は非排他 open のため、公式アプリと bridge は同一デバイスを同時に開ける
- キーイベントは両者にブロードキャスト。**競合するのは LED のみ**（両者が thstatus / rgbcfg を送り合う）
- 対策: [セットアップ手順](/guide/setup) のとおり公式アプリの入力監視を OFF にして、デバイス制御を bridge に一本化する

## 実装への反映

`server/device.py` の `HidAdapter` が本プロトコルを全面実装しています: 受信 JSON の tap/double/long ジェスチャー化、`set_agent_led(index, state)` / `set_ambient(state)` による LED 反映、`_handshake()` + 30秒ハートビートによるエージェントモード維持。
