# 全体アーキテクチャ

## 設計原則

<div class="cm-cards">
  <div class="cm-card">
    <div class="icon">🪶</div>
    <h4>軽量・低負荷が最優先</h4>
    <p>常時ポーリング・ログ洪水パース・定常サブプロセス生成を避け、イベント駆動に徹する。実測 RSS 約50MB / CPU 約0.1% を維持。</p>
  </div>
  <div class="cm-card">
    <div class="icon">🏷️</div>
    <h4>セッション識別が鍵</h4>
    <p>session_id（claude）/ thread_id + cwd（codex）/ CMUX_WORKSPACE_ID（cmux）で、どのセッションのイベントかを常に区別。</p>
  </div>
  <div class="cm-card">
    <div class="icon">📮</div>
    <h4>push 優先・pull は補完</h4>
    <p>hooks の push を一次ソースに、FSEvents 監視をフォールバックに。ポーリングは最小限。</p>
  </div>
  <div class="cm-card">
    <div class="icon">🤝</div>
    <h4>読み取り専用購読</h4>
    <p>既存の公式連携（config・notify スロット等）を奪わず、壊さず共存する。</p>
  </div>
</div>

## システム構成図

<div class="cm-figure">
<svg viewBox="0 0 880 470" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="システム構成図">
  <defs>
    <marker id="cm-arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" opacity=".6"/></marker>
    <marker id="cm-arr-accent" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#D97757"/></marker>
  </defs>

  <!-- event sources -->
  <rect class="box" x="20" y="20" width="230" height="70" rx="10"/>
  <text x="135" y="45" text-anchor="middle" font-weight="700">Claude Code（全セッション）</text>
  <text x="135" y="64" text-anchor="middle" class="t-mono t-muted t-small">hooks: PermissionRequest / Stop /</text>
  <text x="135" y="79" text-anchor="middle" class="t-mono t-muted t-small">StopFailure / Notification / SessionEnd …</text>

  <rect class="box" x="20" y="110" width="230" height="70" rx="10"/>
  <text x="135" y="135" text-anchor="middle" font-weight="700">codex CLI / Desktop</text>
  <text x="135" y="154" text-anchor="middle" class="t-mono t-muted t-small">hooks (hooks.json): PermissionRequest /</text>
  <text x="135" y="169" text-anchor="middle" class="t-mono t-muted t-small">PreToolUse / Stop / SessionStart …</text>

  <rect class="box" x="20" y="200" width="230" height="64" rx="10"/>
  <text x="135" y="224" text-anchor="middle" font-weight="700">FSEvents（フォールバック）</text>
  <text x="135" y="243" text-anchor="middle" class="t-mono t-muted t-small">~/.claude/sessions ・ ~/.codex/sessions</text>

  <rect class="box" x="20" y="284" width="230" height="56" rx="10"/>
  <text x="135" y="306" text-anchor="middle" font-weight="700">cmux</text>
  <text x="135" y="324" text-anchor="middle" class="t-mono t-muted t-small">CMUX_WORKSPACE_ID / タブ制御 CLI</text>

  <!-- hook clients -->
  <rect class="box" x="310" y="60" width="180" height="56" rx="10"/>
  <text x="400" y="83" text-anchor="middle">hook_client.py</text>
  <text x="400" y="101" text-anchor="middle" class="t-mono t-muted t-small">codex_hook_client.py</text>

  <!-- bridge -->
  <rect class="box-accent" x="550" y="30" width="300" height="250" rx="14"/>
  <text x="700" y="58" text-anchor="middle" font-weight="700" font-size="15">bridge（server/ ・ asyncio）</text>

  <rect class="box" x="570" y="76" width="260" height="40" rx="8"/>
  <text x="700" y="101" text-anchor="middle" class="t-small">aiohttp HTTP サーバ :35703</text>

  <rect class="box" x="570" y="126" width="125" height="40" rx="8"/>
  <text x="632" y="146" text-anchor="middle" class="t-small">SessionRegistry</text>
  <text x="632" y="160" text-anchor="middle" class="t-mono t-muted" font-size="9">LRU 6キー割当</text>

  <rect class="box" x="705" y="126" width="125" height="40" rx="8"/>
  <text x="767" y="146" text-anchor="middle" class="t-small">LED 状態機</text>
  <text x="767" y="160" text-anchor="middle" class="t-mono t-muted" font-size="9">5状態 + off</text>

  <rect class="box" x="570" y="176" width="125" height="40" rx="8"/>
  <text x="632" y="196" text-anchor="middle" class="t-small">HidAdapter</text>
  <text x="632" y="210" text-anchor="middle" class="t-mono t-muted" font-size="9">handshake + 30s HB</text>

  <rect class="box" x="705" y="176" width="125" height="40" rx="8"/>
  <text x="767" y="196" text-anchor="middle" class="t-small">アクション実行</text>
  <text x="767" y="210" text-anchor="middle" class="t-mono t-muted" font-size="9">approve / 前面化 / 委譲</text>

  <rect class="box" x="570" y="226" width="260" height="40" rx="8"/>
  <text x="700" y="246" text-anchor="middle" class="t-small">設定コンソール（console/index.html）</text>
  <text x="700" y="260" text-anchor="middle" class="t-mono t-muted" font-size="9">接続カード / レイアウト / オプション</text>

  <!-- device -->
  <rect class="box-dark" x="590" y="330" width="220" height="90" rx="16"/>
  <text x="700" y="362" text-anchor="middle" class="t-white" font-weight="700">Codex Micro</text>
  <text x="700" y="382" text-anchor="middle" class="t-mono" fill="#8593A8">303A:8360 (ESP32-S3)</text>
  <text x="700" y="400" text-anchor="middle" class="t-mono" fill="#8593A8">Report ID 6 / JSON-RPC</text>

  <!-- arrows -->
  <path class="arrow" d="M252 78 L 306 84"/>
  <path class="arrow" d="M252 132 L 306 100"/>
  <path class="arrow" d="M492 88 H 546"/>
  <path class="arrow-dashed" d="M252 232 C 380 232 470 200 546 160"/>
  <path class="arrow-dashed" d="M252 312 C 400 312 480 280 546 240"/>
  <path class="arrow-accent" d="M700 282 V 326"/>

  <text x="519" y="76" text-anchor="middle" class="t-mono t-muted t-small">HTTP POST</text>
  <text x="519" y="120" text-anchor="middle" class="t-mono t-muted t-small">/api/event ・ /decision</text>
  <text x="740" y="306" class="t-mono t-muted t-small">raw HID（64byte frame）</text>

  <text x="440" y="455" text-anchor="middle" class="t-mono t-muted t-small">実線 = push（一次ソース）／破線 = フォールバック・補完。キーイベントはデバイス → bridge へ逆方向に流れる</text>
</svg>
</div>

## コンポーネント

| コンポーネント | ファイル | 役割 |
|---|---|---|
| bridge 本体 | `server/main.py` | asyncio イベントループ・aiohttp サーバ（:35703）・各部の配線 |
| デバイス層 | `server/device.py` | vendor JSON-RPC の送受・ジェスチャー判定（tap/double/long）・LED 制御・ハンドシェイク+30秒ハートビート |
| アクション | `server/actions.py` | 承認解決・セッション前面化・codex アプリへの委譲 |
| 設定 | `server/config.py` | モード・キー割当（binding）の永続化 |
| hook クライアント | `hook_client.py` / `codex_hook_client.py` | hooks の stdin JSON を HTTP で bridge へ転送。PreToolUse は `/decision` で応答を待つ |
| 設定コンソール | `console/index.html` | 公式アプリの設定画面を踏襲した Web UI |
| トレイアプリ | `app/` | pystray + pywebview の常駐 GUI 層（bridge を内蔵スレッドで起動） |
| 常駐スクリプト | `scripts/install_service.sh` | launchd LaunchAgent の生成・登録 |

## 承認フロー（シーケンス）

<div class="cm-figure">
<svg viewBox="0 0 860 330" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="承認シーケンス図">
  <!-- lifelines -->
  <text x="110" y="28" text-anchor="middle" font-weight="700">Claude Code</text>
  <text x="330" y="28" text-anchor="middle" font-weight="700">hook_client.py</text>
  <text x="550" y="28" text-anchor="middle" font-weight="700">bridge</text>
  <text x="760" y="28" text-anchor="middle" font-weight="700">Codex Micro</text>
  <line x1="110" y1="38" x2="110" y2="310" stroke="var(--cm-line)" stroke-width="1.5"/>
  <line x1="330" y1="38" x2="330" y2="310" stroke="var(--cm-line)" stroke-width="1.5"/>
  <line x1="550" y1="38" x2="550" y2="310" stroke="var(--cm-line)" stroke-width="1.5"/>
  <line x1="760" y1="38" x2="760" y2="310" stroke="var(--cm-line)" stroke-width="1.5"/>

  <line x1="110" y1="60" x2="326" y2="60" stroke="var(--cm-muted)" stroke-width="1.5" marker-end="url(#cm-arr2)"/>
  <text x="220" y="52" text-anchor="middle" class="t-mono t-small t-muted">PreToolUse hook（stdin JSON）</text>

  <line x1="330" y1="95" x2="546" y2="95" stroke="var(--cm-muted)" stroke-width="1.5" marker-end="url(#cm-arr2)"/>
  <text x="440" y="87" text-anchor="middle" class="t-mono t-small t-muted">POST /decision（応答待ち）</text>

  <line x1="550" y1="130" x2="756" y2="130" stroke="#D97757" stroke-width="1.8" marker-end="url(#cm-arr2a)"/>
  <text x="655" y="122" text-anchor="middle" class="t-mono t-small t-muted">LED: input（アンバー breath）</text>

  <rect x="600" y="150" width="320" height="26" rx="6" fill="none"/>
  <text x="655" y="168" text-anchor="middle" class="t-small t-muted">…ユーザーが承認キーをタップ…</text>

  <line x1="760" y1="200" x2="554" y2="200" stroke="#D97757" stroke-width="1.8" marker-end="url(#cm-arr2a)"/>
  <text x="655" y="192" text-anchor="middle" class="t-mono t-small t-muted">v.oai.hid（key event）</text>

  <line x1="550" y1="235" x2="334" y2="235" stroke="var(--cm-muted)" stroke-width="1.5" marker-end="url(#cm-arr2)"/>
  <text x="440" y="227" text-anchor="middle" class="t-mono t-small t-muted">/decision 応答: allow</text>

  <line x1="330" y1="270" x2="114" y2="270" stroke="var(--cm-muted)" stroke-width="1.5" marker-end="url(#cm-arr2)"/>
  <text x="220" y="262" text-anchor="middle" class="t-mono t-small t-muted">permissionDecision: allow</text>

  <line x1="550" y1="298" x2="756" y2="298" stroke="#D97757" stroke-width="1.8" marker-end="url(#cm-arr2a)"/>
  <text x="655" y="290" text-anchor="middle" class="t-mono t-small t-muted">LED: 緑（accept）</text>

  <defs>
    <marker id="cm-arr2" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" opacity=".6"/></marker>
    <marker id="cm-arr2a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#D97757"/></marker>
  </defs>
</svg>
</div>

::: tip フェイルセーフ設計
bridge が落ちている・応答しない場合、hook クライアントは `ask`（標準の許可フロー）へ倒します。物理パッドが使えなくても Claude Code の通常の承認プロンプトが出るだけで、**作業がブロックされることはありません**。
:::

## 承認ゲート対象ツール

PreToolUse の承認ゲートに送るツールはフィルタされます（読み取り系は標準権限フローへ）。既定は `Bash,Edit,Write,MultiEdit,NotebookEdit`。`CLAUDEMICRO_GATED_TOOLS` で上書きできます（`mcp__*` の前方一致、`*` で全ツール）。

## 出自と経緯

- ベース: [verylowfreq/m5stack_claudecode_approval_console](https://github.com/verylowfreq/m5stack_claudecode_approval_console)（MIT）。M5Stack + WebSocket の承認コンソール
- Phase 0 で Codex Micro の vendor プロトコル（Report ID 6 の JSON-RPC）を解明し、**QMK 自前ビルド不要**でデバイス層を raw HID に置換できることを確認
- 旧 M5Stack 版は `firmware/` と `bridge.py` に残置
