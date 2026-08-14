# 使い方（モードとキー操作）

## 4つのモード

モードは **AI系統（family: claude / codex）** × **文脈（context: app / cmux）** の2軸4通り。パッドの**アンビエントリング**（外周の光）が現在のモードを表します。

<div class="cm-figure">
<svg viewBox="0 0 640 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="4モードのマトリクス">
  <text x="320" y="24" text-anchor="middle" class="t-muted t-small">← tap: claude ⇄ codex →</text>
  <text x="26" y="160" text-anchor="middle" class="t-muted t-small" transform="rotate(-90 26 160)">← double: app ⇄ cmux →</text>

  <rect class="box-accent" x="60" y="40" width="260" height="100" rx="12"/>
  <text x="190" y="76" text-anchor="middle" font-weight="700">claude-app</text>
  <text x="190" y="98" text-anchor="middle" class="t-mono t-muted t-small">リング: コーラル・点灯</text>
  <text x="190" y="116" text-anchor="middle" class="t-small t-muted">Claude アプリへキー送出</text>

  <rect class="box-blue" x="330" y="40" width="260" height="100" rx="12"/>
  <text x="460" y="76" text-anchor="middle" font-weight="700">codex-app</text>
  <text x="460" y="98" text-anchor="middle" class="t-mono t-muted t-small">リング: 青・点灯</text>
  <text x="460" y="116" text-anchor="middle" class="t-small t-muted">実行のみ公式アプリへ委譲</text>

  <rect class="box-accent" x="60" y="160" width="260" height="100" rx="12"/>
  <text x="190" y="196" text-anchor="middle" font-weight="700">cmux-claude</text>
  <text x="190" y="218" text-anchor="middle" class="t-mono t-muted t-small">リング: コーラル・呼吸</text>
  <text x="190" y="236" text-anchor="middle" class="t-small t-muted">cmux タブの CLI へ送出</text>

  <rect class="box-blue" x="330" y="160" width="260" height="100" rx="12"/>
  <text x="460" y="196" text-anchor="middle" font-weight="700">cmux-codex</text>
  <text x="460" y="218" text-anchor="middle" class="t-mono t-muted t-small">リング: 青・呼吸</text>
  <text x="460" y="236" text-anchor="middle" class="t-small t-muted">cmux タブの codex CLI へ送出</text>

  <text x="320" y="290" text-anchor="middle" class="t-mono t-muted t-small">色 = family（claude=コーラル / codex=青）・エフェクト = context（app=点灯 / cmux=呼吸）</text>
</svg>
</div>

### モード切替キー: ACT12（マイク右隣・右下）

| 操作 | 動作 |
|---|---|
| **タップ** | AI系統を切替（claude ⇄ codex）。文脈は維持 |
| **ダブルタップ** | 文脈を切替（app ⇄ cmux）。AI系統は維持 |
| **長押し** | **auto** に復帰（前面アプリを監視して自動切替） |

例: `cmux-claude` → tap → `cmux-codex` → double → `codex-app` → tap → `claude-app`

::: info 全モードで「頭脳」は本アプリ
config 解釈・エージェント選択・表示・LED は**全モードで本アプリが制御**します。モードで変わるのは**アクションの実行先だけ**です。`codex-app` モードでも判定・表示は本アプリが行い、実行だけを公式 Codex アプリへ委譲します。
:::

## エージェントキー（AG00〜AG05）

6個のエージェントキーは、それぞれ1つの AI セッションに対応します（SessionRegistry が LRU で割当）。

- **LED の色** = そのセッションの状態（[LED 状態カラー](/design/event-sources#led-状態機)）
- **タップ** = そのセッションを**選択して前面化**
  - cmux モード: 該当タブを select してウィンドウを前面化
  - app モード: アプリを前面化

## アクションキー

承認はアクションキーで行います（エージェントキーの tap/double/long での承認は競合のため廃止済み）。

| キー | 動作 | Claude Code 側の応答 |
|---|---|---|
| <span class="cm-led" style="--led:#46C077;"></span> 承認 | 保留中のツール実行を許可 | `allow` |
| <span class="cm-led" style="--led:#9C74E8;"></span> 保留 | 標準の許可フローに戻す | `ask` |
| <span class="cm-led" style="--led:#E0584C;"></span> 拒否 | ツール実行を拒否 | `deny` |

キー割当は設定コンソール（<http://127.0.0.1:35703/>）で変更できます。

## 設定コンソール

ブラウザで <http://127.0.0.1:35703/> を開くと、公式アプリの設定画面を踏襲した Claude 配色のコンソールが使えます。

<div class="cm-cards">
  <div class="cm-card">
    <div class="icon">🔌</div>
    <h4>接続カード</h4>
    <p>デバイスの接続状態・入力監視権限の許可状態を表示。</p>
  </div>
  <div class="cm-card">
    <div class="icon">🗺️</div>
    <h4>レイアウト</h4>
    <p>パッドの実物図をクリックしてキーごとの割当を編集。</p>
  </div>
  <div class="cm-card">
    <div class="icon">⚙️</div>
    <h4>オプション</h4>
    <p>モード切替、エージェントキーの追従対象などを設定。</p>
  </div>
</div>
