# イベント源と LED 状態機

claude / codex 各セッションの状態（thinking 開始・ツール承認待ち・ターン完了・エラー）を bridge が取得し、6個のエージェントキー LED へ反映するための設計です（issue #18）。調査は 2026-08-12〜13 に実機で実施（Claude Code 2.1.228 / codex-cli 0.147.0 / cmux 0.61.0）。

## LED 状態機

イベント源はすべてこの 5状態 + off へマップされます。

| 状態 | LED | 発生条件 |
|---|---|---|
| `idle` | <span class="cm-led" style="--led:#ffffff;"></span> 白 | 待機中（セッション開始・ターン完了後の静止） |
| `thinking` | <span class="cm-led" style="--led:#5585E0;"></span> 青 | 推論中・ツール実行中 |
| `input` | <span class="cm-led breath" style="--led:#E8B24A;"></span> アンバー | ユーザー入力・**ツール承認待ち** |
| `done` | <span class="cm-led" style="--led:#46C077;"></span> 緑 | ターン正常完了 |
| `error` | <span class="cm-led" style="--led:#E0584C;"></span> 赤 | API エラー・ツール失敗 |
| `off` | <span class="cm-led" style="--led:#2a3040;"></span> 消灯 | セッション終了 |

<div class="cm-figure">
<svg viewBox="0 0 760 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="LED状態遷移図">
  <defs>
    <marker id="cm-arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" opacity=".6"/></marker>
  </defs>
  <circle cx="90" cy="120" r="38" fill="none" stroke="#9aa5b5" stroke-width="2"/>
  <text x="90" y="125" text-anchor="middle">idle</text>
  <circle cx="280" cy="60" r="38" fill="none" stroke="#5585E0" stroke-width="2.5"/>
  <text x="280" y="65" text-anchor="middle">thinking</text>
  <circle cx="470" cy="60" r="38" fill="none" stroke="#E8B24A" stroke-width="2.5"/>
  <text x="470" y="65" text-anchor="middle">input</text>
  <circle cx="470" cy="185" r="38" fill="none" stroke="#46C077" stroke-width="2.5"/>
  <text x="470" y="190" text-anchor="middle">done</text>
  <circle cx="280" cy="185" r="38" fill="none" stroke="#E0584C" stroke-width="2.5"/>
  <text x="280" y="190" text-anchor="middle">error</text>
  <circle cx="660" cy="120" r="38" fill="none" stroke="#5a6478" stroke-width="2" stroke-dasharray="5 4"/>
  <text x="660" y="125" text-anchor="middle">off</text>

  <path class="arrow" d="M122 100 Q 180 70 240 62"/>
  <text x="170" y="66" class="t-mono t-small t-muted">UserPromptSubmit</text>
  <path class="arrow" d="M320 55 L 428 55"/>
  <text x="374" y="47" text-anchor="middle" class="t-mono t-small t-muted">PermissionRequest</text>
  <path class="arrow" d="M470 100 L 470 143"/>
  <text x="480" y="126" class="t-mono t-small t-muted">承認→実行→Stop</text>
  <path class="arrow" d="M312 82 Q 370 130 434 168"/>
  <text x="392" y="140" class="t-mono t-small t-muted">Stop</text>
  <path class="arrow" d="M300 92 Q 300 140 292 148"/>
  <text x="308" y="128" class="t-mono t-small t-muted">StopFailure</text>
  <path class="arrow" d="M506 165 Q 580 150 624 132"/>
  <text x="580" y="160" class="t-mono t-small t-muted">SessionEnd</text>
</svg>
<p class="cap">代表的な遷移のみ表示（実際は全状態からの遷移がある）</p>
</div>

## 結論: 二系統 hooks 中核 + FSEvents フォールバック

**claude / codex の同型 lifecycle hooks を中核**に、FSEvents をフォールバックに置きます。codex の `notify` は使いません（単一イベント・単一スロットで、しかもそのスロットは ChatGPT の Computer Use 常駐サービスが占有しているため）。

### Claude Code 側の採用イベント（v2.1.228 / 全31イベントから）

| hook イベント | LED 状態 | 備考 |
|---|---|---|
| `SessionStart` | `idle` | source (startup/resume/clear/compact) 付き |
| `UserPromptSubmit` | `thinking` | プロンプト受理 |
| `PreToolUse` | `thinking` | 承認ゲートは `/decision` |
| `PermissionRequest` | `input` | **承認待ちを tool 情報付きで捕捉** |
| `Notification` | `input` / `done` | `notification_type`（9種）で判定。テキストパース不要 |
| `StopFailure` | `error` | `error_type`（rate_limit 等10種）付き。error LED の確実なトリガ |
| `PostToolUseFailure` | `error` | ツールレベルのエラー |
| `Stop` | `done` | ターン正常完了 |
| `SessionEnd` | `off` | — |

::: details HTTP hook（type:"http"）による subprocess ゼロ化
hook entry を command でなく HTTP にすると、Claude Code 本体が同一の JSON を bridge へ直接 POST します。毎イベントの `python3` 起動（数十ms×毎回）が消え、軽量要件に最適です。ヘッダの `$VAR` 補間（`allowedEnvVars`）で `CMUX_WORKSPACE_ID` も運べます。通知系は HTTP hook 化し、**承認ゲート（PreToolUse）だけはフェイルセーフ保証のため command hook を継続**する選択肢があります（HTTP hook は不通時フェイルオープン）。
:::

### codex 側の採用イベント（0.147.0 / verified-local）

codex には Claude Code 同型の lifecycle hooks が実装済みです（`codex features list` → `hooks stable true`）。1ターンで SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / Stop / SessionEnd の発火を実機確認し、**`PermissionRequest` も 2026-08-13 に実発火を確認**しました（`tool_name="apply_patch"` + `tool_input` 付き = 何を承認しようとしているかまで取れる）。

- 設定: `~/.codex/hooks.json` または `config.toml` の `[hooks]`（プロジェクト `.codex/` も可）
- payload はほぼ Claude Code 互換（`session_id` / `turn_id` / `cwd` / `tool_name` / `transcript_path`）→ `hook_client.py` を流用
- codex は exec を Claude Code と同じ `Bash` に正規化するため matcher も両系統で流用可能
- 非管理フックは初回に TUI の `/hooks` で trust が必要

### フォールバック・補完経路

| 経路 | 用途 | 実測負荷 |
|---|---|---|
| FSEvents: `~/.claude/sessions/{pid}.json` | status (busy/shell/idle/waiting) の live 更新を監視 | RSS 18MB / CPU 0.18% / 遅延 11ms |
| FSEvents: `~/.codex/sessions/**/rollout-*.jsonl` | `task_started` / `task_complete` を拾う（承認要求は永続化されないため hooks 前提） | 同上（ストリーム1本） |
| kqueue `EVFILT_PROC` | claude / codex / ChatGPT プロセスの死活検知 | ほぼゼロ |
| codex app-server プロトコル | `activeFlags.waitingOnApproval` 等が取れる理想的経路だが、他クライアントのスレッド broadcast は未検証 | 保留（第2経路） |

### 却下した経路

| 経路 | 理由 |
|---|---|
| codex `notify` | 単一スロットを ChatGPT Computer Use が占有。hooks で代替可能 |
| transcript JSONL 監視 | アクティブ中 228秒無書き込みを実測。リアルタイム性なし |
| `~/.codex/ipc/ipc.sock` 直結 | ChatGPT.app 所有のハブで非公開・壊れやすい |
| `log stream` | 状態情報なし・セッション識別不可 |

## セッション識別

| 系統 | 識別子 | 取得元 |
|---|---|---|
| Claude Code | `session_id` + `cwd` | 全 hook の stdin / HTTP hook body |
| Claude ↔ cmux | `CMUX_WORKSPACE_ID` | claude プロセスの環境変数（HTTP hook ヘッダで転送） |
| codex | `session_id` / `thread_id` + `cwd` | hook payload / app-server / rollout `session_meta` |
| codex Desktop 判別 | `originator="Codex Desktop"` | rollout `session_meta` |
