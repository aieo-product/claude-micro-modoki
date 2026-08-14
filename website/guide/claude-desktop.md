# Claude Desktop 対応

<p><span class="cm-badge plan">開発中・予定</span></p>

Codex Micro の**ファームウェアを書き換える**ことで、Claude Desktop の公式機能 **「ハードウェアバディ」(BLE)** と直接つながる構想を進めています。実現すると、bridge や hooks の設定なしに **Claude Desktop 単体で状態通知・承認**ができるようになります。

::: warning このページは開発中の機能の予告です
手順・仕様は変わる可能性があります。進行状況は
[issue #25（バディプロトコル調査）](https://github.com/aieo-product/claude-micro-modoki/issues/25) /
[#27（ファーム書換の前提調査）](https://github.com/aieo-product/claude-micro-modoki/issues/27) /
[#29（統合ファーム設計）](https://github.com/aieo-product/claude-micro-modoki/issues/29) を参照してください。
:::

## なにが変わるのか

<div class="cm-figure">
<svg viewBox="0 0 860 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="現在と将来の構成比較">
  <defs>
    <marker id="cm-arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" opacity=".6"/></marker>
    <marker id="cm-arr-accent" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#D97757"/></marker>
  </defs>
  <text x="20" y="30" font-weight="700">現在（純正ファーム）</text>
  <rect class="box" x="20" y="45" width="180" height="52" rx="10"/>
  <text x="110" y="66" text-anchor="middle">Claude Code (CLI)</text>
  <text x="110" y="84" text-anchor="middle" class="t-mono t-muted t-small">hooks</text>
  <rect class="box" x="260" y="45" width="140" height="52" rx="10"/>
  <text x="330" y="66" text-anchor="middle">bridge</text>
  <text x="330" y="84" text-anchor="middle" class="t-mono t-muted t-small">常駐が必要</text>
  <rect class="box-dark" x="460" y="45" width="150" height="52" rx="12"/>
  <text x="535" y="66" text-anchor="middle" class="t-white">Codex Micro</text>
  <text x="535" y="84" text-anchor="middle" class="t-mono" fill="#8593A8">USB HID</text>
  <path class="arrow" d="M202 71 H 256"/>
  <path class="arrow" d="M402 71 H 456"/>

  <text x="20" y="150" font-weight="700">将来（統合ファーム）</text>
  <rect class="box-accent" x="20" y="165" width="180" height="52" rx="10"/>
  <text x="110" y="186" text-anchor="middle">Claude Desktop</text>
  <text x="110" y="204" text-anchor="middle" class="t-mono t-muted t-small">ハードウェアバディ機能</text>
  <rect class="box-dark" x="460" y="165" width="180" height="52" rx="12"/>
  <text x="550" y="186" text-anchor="middle" class="t-white">Codex Micro（書換後）</text>
  <text x="550" y="204" text-anchor="middle" class="t-mono" fill="#8593A8">BLE + USB HID 両立</text>
  <path class="arrow-accent" d="M202 191 H 456"/>
  <text x="330" y="184" text-anchor="middle" class="t-mono t-muted t-small">BLE 直結（bridge 不要）</text>
  <text x="330" y="240" text-anchor="middle" class="t-mono t-muted t-small">従来の bridge 経由（USB HID）も同じファームで併用可能にする設計（issue #29）</text>
</svg>
</div>

**ハードウェアバディ**は Claude Desktop に組み込まれている公式機能です（ヘルプ → トラブルシューティング → 開発者ツール → ハードウェアバディ）。BLE でデバイスとペアリングし、状態通知や承認をやり取りします。Anthropic 公式の M5Stack Cardputer 連携（`cwc-makers` プラグイン / [moremas/build-with-claude](https://github.com/moremas/build-with-claude)）と同じ仕組みです。

Codex Micro は ESP32-S3（Wi-Fi + BT5 LE 内蔵）なので、**ハードウェアはそのままでファームウェアだけ**でバディ化できます。Cardputer 用の公式ファームは MicroPython 製で流用できないため、Codex Micro 用のバディファームを新規開発します。

## 技術的な前提（確認済み）

| 項目 | 結果 |
|---|---|
| ブートローダ移行 | <span class="cm-badge done">確認済み</span> vendor RPC `sys.bootloader` で**分解不要**で書込モードへ（底面ボタンでも可） |
| Secure Boot / Flash 暗号化 | <span class="cm-badge done">無効</span> カスタムファームの書込・起動が可能 |
| フルバックアップ | <span class="cm-badge done">取得手順確立</span> 16MB フラッシュを平文ダンプ→書き戻しで**完全復元可能** |
| バディプロトコル | <span class="cm-badge wip">調査中</span> BLE の advertise / hello / heartbeat / permission 応答（issue #25） |
| 統合ファーム設計 | <span class="cm-badge wip">設計中</span> USB HID キーパッド + BLE バディの両立（issue #29） |

## セットアップ手順（予定プレビュー）

リリース時にはこの流れを想定しています。**今はまだ実行しないでください**（ファーム未配布）。

<div class="cm-steps">

<div class="cm-step">

#### 純正ファームをバックアップする
<p class="goal">ゴール: 16MB のフルバックアップファイルが手元にある</p>

書き換えの前に、必ず純正ファームの完全バックアップを取ります。これがあれば**いつでも工場出荷状態に戻せます**。バックアップ取得ツールは本リポジトリで提供予定です。

</div>

<div class="cm-step">

#### 書き込みモード（ブートローダ）へ移行する
<p class="goal">ゴール: デバイスが書込モード（USB 303A:1001）で認識される</p>

デバイスを**分解する必要はありません**。ツールが vendor RPC でブートローダへ移行させます（失敗時は底面ボタンでも移行可能）。

</div>

<div class="cm-step">

#### 統合ファームを書き込む
<p class="goal">ゴール: 書込完了後、再起動して LED が点灯する</p>

`esptool` ベースの書込スクリプトを実行します。統合ファームは **USB HID（従来の bridge 連携）と BLE バディの両立**を目指しています。

</div>

<div class="cm-step">

#### Claude Desktop とペアリングする
<p class="goal">ゴール: 画面に <b>LINKED</b> と表示される</p>

Claude Desktop の **ヘルプ → トラブルシューティング → 開発者ツール → ハードウェアバディ** を開き、デバイスをペアリングします。以降は Claude Desktop の状態がデバイスに通知され、承認もキーからできるようになる想定です。

</div>

<div class="cm-step">

#### （戻したくなったら）純正ファームを復元する
<p class="goal">ゴール: 工場出荷状態に完全復帰</p>

ステップ1のバックアップを書き戻せば、純正ファーム・公式アプリ連携も含めて元通りになります。

</div>

</div>

::: info 従来方式はそのまま使えます
バディ化は**追加の選択肢**です。現行の bridge + hooks 構成（[セットアップ](/guide/setup)）は純正ファームのまま動作し、今後もメンテナンスされます。
:::
