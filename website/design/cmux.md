# cmux 連携（タブ制御）

[cmux](https://cmux.sh)（Electron 系ターミナルマルチプレクサ）のタブを、エージェントキーから選択・前面化するための連携設計です（2026-08-12 検証 / cmux 0.61.0）。

## 制御手段: Unix ソケット CLI

AppleScript 辞書が無いため、同梱 CLI を使います:

```
/Applications/cmux.app/Contents/Resources/bin/cmux <command> [--json]
```

| コマンド | 用途 |
|---|---|
| `list-workspaces` | タブ一覧（`ref` / `index` / `title` / `selected`） |
| `workspace-action --action select --workspace <id>` | 指定タブを選択 |
| `focus-window --window <id>` | ウィンドウ前面化 |
| `identify` | 呼び出し元の workspace / surface を特定 |

ID は UUID / 短縮 ref（`workspace:1`）/ index のいずれも指定可能です。

## セッション自己特定（環境変数）

cmux 内で起動したプロセスは以下の環境変数を持ち、Claude Code セッションが**自分のタブを特定**できます。

| 環境変数 | 意味 |
|---|---|
| `CMUX_WORKSPACE_ID` | タブ（workspace）UUID — **session ↔ タブの対応付けに使用** |
| `CMUX_PANEL_ID` | ペイン UUID |
| `CMUX_BUNDLE_ID` | `com.cmuxterm.app`（cmux 内かどうかの判定に使える） |

## 本プロジェクトでの利用

<div class="cm-figure">
<svg viewBox="0 0 820 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="cmux連携フロー">
  <defs>
    <marker id="cm-arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" opacity=".6"/></marker>
    <marker id="cm-arr-accent" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#D97757"/></marker>
  </defs>
  <rect class="box-dark" x="20" y="60" width="150" height="60" rx="12"/>
  <text x="95" y="86" text-anchor="middle" class="t-white">AG02 タップ</text>
  <text x="95" y="104" text-anchor="middle" class="t-mono" fill="#8593A8">エージェントキー</text>

  <rect class="box-accent" x="230" y="60" width="200" height="60" rx="10"/>
  <text x="330" y="86" text-anchor="middle">SessionRegistry</text>
  <text x="330" y="104" text-anchor="middle" class="t-mono t-muted t-small">session_id → workspace_id</text>

  <rect class="box" x="490" y="20" width="310" height="60" rx="10"/>
  <text x="645" y="45" text-anchor="middle" class="t-mono t-small">cmux workspace-action --action select</text>
  <text x="645" y="65" text-anchor="middle" class="t-mono t-small">--workspace $CMUX_WORKSPACE_ID</text>

  <rect class="box" x="490" y="110" width="310" height="50" rx="10"/>
  <text x="645" y="140" text-anchor="middle" class="t-mono t-small">cmux focus-window --window &lt;ref&gt;</text>

  <path class="arrow-accent" d="M172 90 H 226"/>
  <path class="arrow" d="M432 78 L 486 58"/>
  <path class="arrow" d="M432 102 L 486 128"/>
  <text x="410" y="185" text-anchor="middle" class="t-mono t-muted t-small">SessionStart hook で CMUX_WORKSPACE_ID を捕捉 → キー押下で該当タブを select + 前面化</text>
</svg>
</div>

- **SessionRegistry（#4）**: SessionStart hook で `CMUX_WORKSPACE_ID` を捕捉し、`session_id → workspace_id` を記録
- **エージェントキー押下 = 選択 + 前面化**: cmux モードでは該当タブを select してウィンドウを前面化。app モードよりも**セッション単位の前面化が正確**（環境変数で一意特定できるため）
- **cmux は claude の状態集約者**: cmux の wrapper 注入は claude のみ。codex は cmux の集約対象外のため、[hooks / rollout 監視](/design/event-sources) で取得する

## 注意

- `workspace-action --action select` は実行するとタブが実際に切り替わる（検証時は自分のタブが飛ぶ）
- 認証は `--password` / `CMUX_SOCKET_PASSWORD` / キーチェーンの順。list 系はプロンプトなしで動作確認済み
