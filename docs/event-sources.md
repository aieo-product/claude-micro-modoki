# エージェント状態イベントの取得設計（issue #18 / アプリ核仕様）

claude / codex の各セッションの状態（thinking 開始・ツール承認待ち・ターン完了・エラー）を
bridge が取得し、6 個のエージェントキー LED へ反映するための **イベント源の設計**。
本 bridge の中核仕様であり、[docs/mode-behavior.md](./mode-behavior.md) の LED 状態機の入力側を定義する。

> 調査は 2026-08-12 に多角的に実施（claude hooks / claude 非hooks / codex CLI / codex desktop / OS 機構 / cmux）。
> 各手段の feasibility 表記: **verified-local**（本機でコマンド/ファイルにより確認）/ **likely**（文献＋状況証拠）/ **uncertain** / **rejected**。
> 実機バージョン: Claude Code `2.1.228`、codex-cli `0.147.0`（homebrew, `/opt/homebrew/bin/codex`）、
> ChatGPT.app 内蔵 codex `0.147.0-alpha.6.5`、cmux `0.61.0`。

---

## 0. 設計原則（要件からの制約）

| 原則 | 内容 |
|---|---|
| **軽量・低負荷が最優先** | 常時ポーリング・ログ洪水パース・定常サブプロセス生成を避ける。イベント駆動が理想（実測 RSS~50MB / CPU~0.1% を維持） |
| **セッション識別が採用可否の鍵** | どのセッション/ワークスペースのイベントか区別できること。`session_id`（claude）/ `thread_id`+`cwd`（codex）/ `CMUX_WORKSPACE_ID`（cmux）で解決 |
| **push 優先・pull は補完** | hooks/OTLP の push を一次ソースとし、FSEvents 監視をフォールバックに。socket ポーリングは最小リクエストのみ |
| **読み取り専用購読** | 既存の公式連携（config・notify スロット等）を奪わず、壊さず共存する |

### LED 状態機（[mode-behavior.md](./mode-behavior.md) / `server/device.py` STATE_COLOR）

本設計が供給すべき状態は 5 種（+off）。イベント源はこの遷移にマップできなければならない。

| 状態 | 色 | 発生条件（claude/codex 共通の意味） |
|---|---|---|
| `idle` | 白 | 待機中（セッション開始・ターン完了後の静止） |
| `thinking` | 青 | 推論中・ツール実行中 |
| `input` | アンバー | ユーザー入力・**ツール承認待ち** |
| `done` | 緑 | ターン正常完了 |
| `error` | 赤 | API エラー・ツール失敗 |
| `off` | 消灯 | セッション終了 |

---

## 1. 結論（本命アーキテクチャ）

**二系統の hooks を中核**に、**FSEvents をフォールバック**に置く。**notify 奪取は不要**。

```
                 ┌─────────────── HTTP hook (type:"http") ───────────────┐
  Claude Code ───┤  StopFailure→error / PermissionRequest,Notification→input      │
   (全セッション)  │  Stop→done / UserPromptSubmit→thinking / SessionEnd→off        ├──▶ POST /api/event
                 └───────────────────────────────────────────────────────┘         │  POST /decision
                 ┌─────────────── codex hooks ([hooks]/hooks.json) ──────┐         │  （既存 bridge の
   codex CLI  ───┤  PermissionRequest→input / Stop→done / PreToolUse→thinking      ├──▶  aiohttp エンドポイント）
   codex Desktop  │  SessionStart→idle / SessionEnd→off                            │
                 └───────────────────────────────────────────────────────┘         │
                 ┌─────────────── FSEvents（フォールバック/補完）──────────┐       │
   OS 監視   ────┤  ~/.claude/sessions/{pid}.json（status live 更新）              ├──▶ 内部イベント
                 │  ~/.codex/sessions/…/rollout-*.jsonl（task_started/complete）  │
                 └───────────────────────────────────────────────────────┘
```

**なぜ hooks 中核か**: claude / codex とも同型の lifecycle hooks を持ち、`PermissionRequest` で承認待ちを、`Stop` で完了を、
イベント発火時のみのコストで取れる。既存の [`hook_client.py`](../hook_client.py) の設計をそのまま両系統に流用できる。

**なぜ notify を使わないか**: codex `notify` は `agent-turn-complete`（ターン完了）だけの単一イベント・単一 argv スロットで、
しかもそのスロットは既に **ChatGPT の Computer Use（画面自動操作）常駐サービス**が占有している（後述 §5 の訂正）。
hooks なら競合ゼロで、承認待ち・thinking まで取れる。notify は本命から降格。

---

## 2. Claude Code のイベント源（v2.1.228 / verified-local）

hooks は使用中 6 種を含め **全 31 イベント**に拡充されている
（`strings ~/.local/share/claude/versions/2.1.228` の `executeXXXHooks` と
[code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) で照合）。
全イベントの stdin JSON に `session_id` が必ず入り、`cwd` / `transcript_path` / `permission_mode` / `hook_event_name` も共通。

### 2.1 採用イベントと LED マッピング

| hook イベント | LED 状態 | 取得できる情報 | 備考 |
|---|---|---|---|
| `SessionStart` | `idle` | `source`(startup/resume/clear/compact) | 使用中 |
| `UserPromptSubmit` | `thinking` | プロンプト受理 | 使用中 |
| `PreToolUse` | `thinking` | `tool_name`/`tool_input`/`tool_use_id` | 使用中（承認ゲートは `/decision`） |
| **`PermissionRequest`**（新） | `input` | `tool_name`/`tool_input`/`classification` | **承認待ちを tool 情報付きで捕捉**。JSON `decision.response`(allow/deny/escalate) で応答可 |
| **`Notification`**（種別拡充） | `input`/`done` | `notification_type`（9 種）/`message`/`severity` | 現 `hook_client.py` は message しか転送せず種別を捨てている → 下記 §2.2 |
| **`StopFailure`**（新） | `error` | `error_type`（rate_limit/overloaded/… 10 種）/`error_message` | **error LED の確実なトリガ**。API エラー終了のみ発火 |
| **`PostToolUseFailure`**（新） | `error` | `tool_error` | ツールレベルのエラー |
| `Stop` | `done` | ターン正常完了 | 使用中 |
| `SessionEnd` | `off` | — | 使用中 |
| （補助）`SubagentStart`/`SubagentStop` | — | `agent_id`/`agent_type` | サブエージェント可視化。`agent_id` の有無でメイン承認待ちと区別 |

`permissionDecision` の有効値は現行バイナリで `allow | deny | ask | defer`
（docs に `escalate` 表記ゆれあり。`hook_client.py` の `ask` は有効）。

### 2.2 Notification の notification_type（テキストパース不要化）

`matcher` で種別を絞れる。LED に効くもの:

| notification_type | 意味 | LED |
|---|---|---|
| `permission_prompt` | 承認プロンプト表示 | `input` |
| `idle_prompt` | 入力待ちアイドル | `input` |
| `agent_needs_input` | エージェントが入力要求 | `input` |
| `agent_completed` | エージェント完了 | `done` |
| `elicitation_*` | MCP 入力要求 | `input` |
| `auth_success` | 認証成功 | — |

> **即改善**: [`hook_client.py`](../hook_client.py) の payload に `notification_type` を1フィールド足すだけで、
> input/done 判定が message 文字列パースから種別判定になる（負荷増ゼロ）。

### 2.3 ★HTTP hook（`type:"http"`）— subprocess ゼロ化（本命の輸送）

hook entry を command でなく HTTP にすると、**Claude Code 本体が command hook と同一の JSON を bridge へ直接 POST** する。
毎イベントの `python3` 起動（数十 ms ×毎回）が完全に消え、軽量要件に最適。

```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://127.0.0.1:35703/api/event",
            "headers": {
              "X-Bridge-Token": "$APPROVAL_BRIDGE_TOKEN",
              "X-Cmux-Workspace": "$CMUX_WORKSPACE_ID"
            },
            "allowedEnvVars": ["APPROVAL_BRIDGE_TOKEN", "CMUX_WORKSPACE_ID"],
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- 応答 body は command hook の JSON 出力と同スキーマ。**2xx + `hookSpecificOutput` で `permissionDecision` も返せる**
  → `PreToolUse` の承認ゲート（`/decision`）も HTTP hook で置換可能。
- **HTTP ステータスコード単体では block 不可**（2xx を返した上で body で判断）。
- ヘッダは `$VAR` / `${VAR}` 補間。`allowedEnvVars` に列挙した変数のみ解決 → **`CMUX_WORKSPACE_ID` をヘッダで運べる**
  （POST body には env が入らないため、セッション↔cmux 対応はこのヘッダ経由が確実）。
- 非 2xx / 不通 / タイムアウトは non-blocking エラー扱い（Claude は止まらない = ライフサイクル通知のフェイルオープンに合致）。
- タイムアウト既定は command/http とも 10 分、`UserPromptSubmit` は 30 秒、`SessionEnd` は全 hook 合計 1.5 秒バジェット。

> **設計判断**: 通知系（Notification/Stop/StopFailure 等）は HTTP hook 化して subprocess ゼロに。
> 一方 **`PreToolUse` の承認ゲートはフェイルセーフ（bridge 不通時に `ask` へ倒す）を保証するため command hook を継続**する選択もある
> （HTTP hook は不通時フェイルオープン）。bridge 常時起動を前提にできるなら承認も HTTP に一本化可。

### 2.4 補助イベント源（hooks 以外）

| 手段 | 用途 | feasibility | 負荷 |
|---|---|---|---|
| **`~/.claude/sessions/{pid}.json`** レジストリ | status `busy/shell/idle/waiting` を sessionId+cwd+name 付きで live 更新。FSEvents 監視でポーリング0のフォールバック | verified-local（`waiting` の承認時発火のみ要ライブ確認1回） | 極小 |
| OpenTelemetry（OTLP http/json） | `tool_decision`/`tool_result`/`user_prompt` を session.id 付き push。bridge の aiohttp に `/v1/logs` を足す | likely（要 env 設定） | 5s バッチ・push |
| `~/.claude/history.jsonl` tail | プロンプト送信の即時記録（hooks を仕込めないセッションのフォールバック） | verified-local | 極小 |
| statusline `ping` 追記 | 既存 `~/.claude/statusline.py` に1行足せば ctx 残量等の補助シグナル | verified-local | 増分ゼロ |
| transcript JSONL 監視 | — | **rejected**（アクティブ中 228 秒無書き込みを実測、リアルタイム性なし） | — |
| `claude -p stream-json` / Agent SDK | 既存対話セッションを外から観測 **不可**（attach API なし） | rejected | — |

---

## 3. codex のイベント源（0.147.0 / verified-local + 公式ドキュメント）

★HANDOFF の「codex は notify が本命」「app-server は homebrew 不可」は**本調査で訂正**された。

### 3.1 ★codex hooks（本命・新発見）

codex に Claude Code 同型の lifecycle hooks が実装済み。`codex features list` → `hooks stable true` を本機で確認。
公式仕様は [learn.chatgpt.com/docs/hooks](https://learn.chatgpt.com/docs/hooks)（`developers.openai.com/codex/hooks` から 308）。

**イベント**: `SessionStart` / `SessionEnd` / `UserPromptSubmit` / `PreToolUse` / **`PermissionRequest`** /
`PostToolUse` / `PreCompact` / `PostCompact` / `SubagentStart` / `SubagentStop` / `Stop`。

**共通 payload（stdin JSON）**: `session_id` / `cwd` / `hook_event_name` / `transcript_path` / `model`、
turn スコープは `turn_id`、多くは `permission_mode`。`PreToolUse`/`PostToolUse` は `tool_name`/`tool_use_id`/`tool_input`(+`tool_response`)、
`SessionStart` は `source`(startup/resume/clear/compact)、`Stop` は `last_assistant_message`。
→ **claude hooks とほぼ同じ = `hook_client.py` を流用可能**。

> **★2026-08-12 実発火を verified-local で確認**（scratch dir + project-local `.codex/hooks.json` + `codex exec`）。
> 1ターンで **SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / Stop / SessionEnd の6イベントが発火**（各 `<event> Completed` も確認）。
> 実測 payload 例（PreToolUse）: `session_id=019ff675-…`, `turn_id=019ff675-…`, `cwd=<workdir>`, `model=gpt-5.6-sol`,
> `tool_name="Bash"`（codex は exec を **Claude Code と同じ `Bash` に正規化** → matcher が両系統で流用可）,
> `tool_use_id="exec-…"`, `tool_input={"command":"…"}`, `transcript_path` は **rollout jsonl を直接指す**（hooks ↔ §3.3 rollout 監視の突合キー）。
> **`PermissionRequest` も 2026-08-13 に発火確認（verified-local）**。ワークスペース外書込（`apply_patch`）で承認が要る 2 回目のターンを走らせ、
> `apply_patch` の直前に発火。実測 payload: `hook_event_name="PermissionRequest"`, `session_id`/`turn_id`/`cwd`/`transcript_path`,
> `permission_mode="default"`, **`tool_name="apply_patch"`**, **`tool_input={"command":"*** Begin Patch…"}`**
> （＝**何を承認しようとしているかまで tool_input 付きで取れる**）。これが input/承認待ち LED の主トリガ。
> exec の `--approve-for-me`（自動承認）経路でも hook は request 時点で発火する（承認の解決前にタップできる）。
> 承認"解決"の専用イベントは無いので、次の `PostToolUse`/`Stop` で消灯するか、bridge 側の承認応答で解除する設計にする。

**設定**（`~/.codex/hooks.json` または `config.toml` の `[hooks]`。プロジェクト `<repo>/.codex/` も可）:

```toml
[[hooks.PermissionRequest]]
matcher = ".*"

[[hooks.PermissionRequest.hooks]]
type = "command"
command = '/path/to/.venv/bin/python /path/to/codex_hook_client.py'
timeout = 30
```

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "…", "async": true } ] }
    ]
  }
}
```

- **decision 返却**: `PreToolUse` は `permissionDecision`(deny+reason / allow+`updatedInput`)、
  `PermissionRequest` は `behavior`(allow/deny)。`PostToolUse`/`Stop` 等は `decision:"block"`。
  → **観測タップとして使うなら decision を返さず素通し**すればよい。
- **`async:true`** でノンブロッキング（最大 8 並行/セッション）。
- **trust 承認が必要**: 非管理フックは初回に TUI の `/hooks` で trust（ハッシュ追跡、変更で再承認）。
  `--dangerously-bypass-hook-trust` で一括バイパス可。
- **全サーフェス発火**: CLI TUI / exec / **ChatGPT desktop app** / IDE で発火とドキュメントが明記
  （※公式ページはサーフェス列挙を明示していない箇所があり、**Desktop アプリでの実発火は要ライブ検証**）。

### 3.2 codex app-server プロトコル（訂正・補完）

★**homebrew 版 0.147.0 に同梱**（旧「standalone 必須」は誤り）。`codex app-server daemon/proxy/generate-json-schema/remote-control` を本機で確認。
`codex app-server generate-json-schema` で全スキーマを生成し
（`scratchpad/codex-schema/` に `ServerNotification.json` 176KB 等）、以下を確認:

- **ServerNotification（70 種弱）**: `thread/status/changed`(ThreadStatus=`notLoaded/idle/systemError/active`+`activeFlags`) /
  `turn/started` / `turn/completed` / `item/reasoning/textDelta`（=thinking）/ `item/agentMessage/delta` /
  `error` / `warning` 等。
- **ServerRequest（承認要求）**: `item/commandExecution/requestApproval` / `item/fileChange/requestApproval` /
  `item/permissions/requestApproval` / `execCommandApproval` / `applyPatchApproval`。
- **セッション識別**: 全通知が `threadId`(+`turnId`)。Thread 定義に `cwd`/`sessionId`/`gitInfo`/`agentNickname`。
- **`activeFlags` に `waitingOnApproval`/`waitingOnUserInput`** があり LED 状態機にそのまま写像できる（意味的に理想）。

| 状態 | app-server 経路 |
|---|---|
| `thinking` | `thread/status/changed`(active) / `item/reasoning/textDelta` |
| `input` | ServerRequest(`*/requestApproval`) / activeFlags `waitingOnApproval` |
| `done` | `turn/completed` / status→`idle` |
| `error` | status→`systemError` / `error` 通知 |

> **未検証（likely 止まり）**: app-server は接続ごとに initialize しスレッドを駆動するモデル。bridge が新規接続したとき、
> **他クライアント（ChatGPT / 別 TUI）が作ったスレッドのイベントが自動 broadcast されるか**は要実接続テスト。
> 共有 daemon（`remote-control`）構成なら見込みあり。細粒度（thinking 途中経過）が要る場合の第2経路として保留。

### 3.3 rollout ファイル監視（フォールバック / verified-local）

`~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` に **CLI も Desktop も同じ場所**へ追記
（先頭 `session_meta` に `session_id`/`cwd`/`originator`。実測: `originator` = `Codex Desktop` / `codex_exec`）。

- **event_msg**: `task_started`(turn 開始) / `task_complete`(turn 完了) / `agent_reasoning` / `agent_message` / `token_count` 等。
- **承認要求イベントは rollout に永続化されない**（8 月分全 grep で approval 系ゼロ）→ 承認待ちは hooks で取る前提。
- Desktop の app-server プロセスが rollout FD を open 保持し逐次 append（`lsof` 確認）。
- 監視は当日ディレクトリ + mtime 新しいファイルのみに絞り、`task_started`/`task_complete`/`user_message` 行のみ拾う
  （`agent_reasoning`/`token_count` は turn 中に高頻度追記のためデバウンス必須）。

### 3.4 却下・非推奨の codex 経路

| 手段 | 判定 | 理由 |
|---|---|---|
| `notify`（turn-ended） | 非推奨 | 単一スロットを Computer Use が占有。hooks があるので不要 |
| OpenTelemetry `[otel]` | likely（補完） | `tool_decision`/`tool_result` を conversation.id 付き push。承認待ち・完了の直接イベントなし・要 config 変更 |
| `~/.codex/ipc/ipc.sock` 直結 | uncertain | フレーミングは `u32LE 長プレフィックス + JSON エンベロープ`（前回の拒否は改行 JSON が原因）。ただし **ChatGPT.app が所有するハブ**で `/v1/initialize` ハンドシェイク必須・非公開・壊れやすい |
| `codex mcp-server` / `codex exec --json` | rejected | 自分が起動したセッションのみ。他者の観測に使えない（exec 分は rollout でカバー） |
| `tui.notifications`(OSC9/BEL) | rejected | 端末に届くだけで bridge から傍受不可（pty 非所有） |
| `state_5.sqlite` / `.codex-global-state.json` | rejected（登録簿としては可） | live 状態フィードなし。`threads` テーブル(id→cwd/title) はセッション名解決の補助に流用可 |

---

## 4. OS レベルのイベント機構（全て実機ベンチ済み）

FSEvents 監視と死活検知の実装基盤。

| 機構 | 用途 | 実測負荷 | feasibility |
|---|---|---|---|
| **FSEvents（watchdog）** | `~/.codex/sessions/` + `~/.claude/(sessions\|projects)/` の JSONL 追記監視 | **RSS 18MB / CPU 0.18% / 遅延 11ms**、ポーリング0・subprocess0 | verified-local |
| **kqueue `EVFILT_VNODE`**（stdlib） | 依存ゼロ版のファイル監視。`loop.add_reader()` で asyncio ネイティブ統合 | RSS 増ほぼ0・遅延 15〜38ms | verified-local |
| **kqueue `EVFILT_PROC` `NOTE_EXIT`** | claude/codex/ChatGPT プロセスの死活検知（ポーリング不要） | RSS0・CPU0・終了即時 | verified-local |
| **NSWorkspace 通知**（pyobjc） | 前面アプリ検知（将来の `host.focused_app`）。didActivate/didLaunch/didTerminate | **+26MB**（AppKit import）→ 使う時のみ遅延 import | verified-local |
| darwin notification（notifyd） | bridge 自作 IPC の軽量起床シグナル（ペイロード無し） | RSS0・遅延 18ms | verified-local（既存 claude/codex は未使用） |
| `log stream` | — | 意外に軽い（RSS 4MB）が状態情報なし・セッション識別不可 | rejected |
| launchd WatchPaths | bridge 自体の初回自動起動のみ | 実行中ジョブへの配送機構ではない | rejected（起動用途のみ可） |

> FSEvents は監視ディレクトリ数に比例したコスト増がない（ストリーム1本）。watchdog は venv 依存。
> 依存を避けるなら kqueue（stdlib）で代替可だが、日付別ディレクトリの付け替えと fd 管理が要る。

---

## 5. ★重要な訂正（HANDOFF / メモリの上書き）

本調査で以下が実機確認により訂正された。

1. **codex にも hooks がある**（stable）。→ codex 側も notify でなく hooks が本命。承認待ちも取れる。
2. **codex app-server は homebrew 版に同梱**。→ 旧「standalone install 必須で homebrew 不可」は誤り。第2経路として利用可。
3. **`SkyComputerUseClient`/`Service` は Codex Micro の LED ホストではない**。
   これは **ChatGPT の「Computer Use」（画面自動操作 = Operator 相当）の macOS 常駐サービス**。
   - 両バイナリ `strings -a` に HID/LED/macropad/rgb/report id 系が皆無、`lsof` でも HID デバイス未オープン。
   - config.toml の `notify=['…SkyComputerUseClient','turn-ended']` と `Handles a Codex turn-ended notification` は、
     codex のターン終了を画面オーバーレイのピル（`ChatGPT is using your computer`）に伝えて消す用途。
   - **結論**: Codex Micro の公式ホストは本機に存在せず、**LED を駆動しているのは本 bridge だけ**。相乗り先を探す必要はない。

---

## 6. セッション識別（採用可否の鍵）

| 系統 | 識別子 | 取得元 |
|---|---|---|
| Claude Code | `session_id`(UUID) + `cwd` | 全 hook stdin / HTTP hook body。cmux wrapper が `--session-id` を注入し起動時から確定 |
| Claude ↔ cmux | `CMUX_WORKSPACE_ID` / `CMUX_PANEL_ID` | claude プロセス env（実プロセスで確認）。HTTP hook のヘッダ `$CMUX_WORKSPACE_ID` で運ぶ |
| codex | `session_id` / `thread_id` + `cwd` | codex hook payload / app-server threadId / rollout session_meta |
| codex Desktop 判別 | `originator="Codex Desktop"` | rollout `session_meta` |

**cmux は claude の状態集約者**（[cmux-integration.md](./cmux-integration.md) 参照）。
`/tmp/cmux.sock`（認証不要・0.1ms/req）や `session-*.json`（約8秒周期上書き）から workspace UUID 付き `claude_code` ステータスが取れるが、
**codex は cmux に wrapper 注入されておらず**（`bin/` は claude のみ）集約対象外。codex は §3 の hooks/rollout で取る。

---

## 7. 実装フェーズ（#18 の再計画）

| 段階 | 内容 | 前提 |
|---|---|---|
| **7-1** | `hook_client.py` に `notification_type` 転送を追加（§2.2） | 設定変更なし・即実施可 |
| **7-2** | claude 側 hooks を HTTP hook 化（§2.3）+ `StopFailure`/`PermissionRequest` 追加、`/api/event` を拡張 | `settings.local.json` 追記（要バックアップ）＋ live 確認 |
| **7-3** | codex hooks クライアント（`hook_client.py` 流用）+ `~/.codex/hooks.json` 配線 | config 追記＋ TUI `/hooks` trust（**要ユーザー同意**） |
| **7-4** | FSEvents フォールバック（`~/.claude/sessions/` + `~/.codex/sessions/` 監視） | venv に watchdog（or kqueue 実装） |
| **7-5**（保留） | app-server daemon 購読（thinking 細粒度が要るとき） | daemon 起動＋ broadcast 範囲の実接続テスト |

### ライブ検証の状況

| # | 項目 | 状況 |
|---|---|---|
| 1a | **codex hooks が CLI(`codex exec`)で発火するか** | ✅ **完了(2026-08-13, verified-local)**。SessionStart/UserPromptSubmit/PreToolUse/PostToolUse/**PermissionRequest**/Stop/SessionEnd 全発火。payload に session_id/turn_id/cwd/tool_name/tool_input/transcript_path |
| 1b | codex hooks が **ChatGPT Desktop** で発火するか | ⏳ 未(ネイティブGUIのため要ユーザー操作) |
| 2 | claude `~/.claude/sessions/{pid}.json` の `waiting` が承認時に立つか | ⏳ 未(承認待ちの瞬間に要スナップショット) |
| 3 | codex app-server daemon で他クライアントのスレッドを購読できるか | ⏳ 未(保留tier。hooks で CLI は充足したため優先度低) |

> 検証1a の証跡: `scratchpad/codex-hook-test/`（project-local `.codex/hooks.json` + logger + `hook-events.run1.log`）。
> グローバル `~/.codex/config.toml` は未編集（バックアップ `config.toml.bak-*` あり）。

いずれも設定変更または実ターン起動を伴うため、**バックアップの上でユーザー同意を得てから**実施する
（[HANDOFF の進め方: プライバシー/軽量要件遵守]）。

---

## 参照

- [docs/mode-behavior.md](./mode-behavior.md) — LED 状態機・4モード（本設計の出力側）
- [docs/cmux-integration.md](./cmux-integration.md) — cmux セッション識別
- [docs/vendor-protocol.md](./vendor-protocol.md) — HID / LED 低レベル
- [hook_client.py](../hook_client.py) — 現行フッククライアント（HTTP hook 化・codex 流用の起点）
- 生成物: `codex app-server generate-json-schema`（ServerNotification/ServerRequest の一次資料）
