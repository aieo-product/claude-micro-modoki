# cmux 連携（タブ制御）調査結果

検証日: 2026-08-12 / cmux `com.cmuxterm.app`（Electron系。AppleScript 辞書なし）

## 制御手段: Unix ソケット CLI

`/Applications/cmux.app/Contents/Resources/bin/cmux <command>`（`--json` で JSON 出力）

主要コマンド:
- `list-workspaces` — タブ(workspace)一覧。`ref`(workspace:N) / `index` / `title` / `selected` を返す（認証プロンプトなしで動作確認済み）
- `workspace-action --action select --workspace <id|ref|index>` — 指定タブを選択（`workspace.select`）
- `workspace-action --action <name>` — 他アクション（close/rename/reorder 等）
- `focus-window --window <id|ref>` — ウィンドウ前面化（`window.focus`）
- `list-windows` / `current-window` / `new-workspace [--command <text>]`
- `identify [--workspace] [--surface]` — 呼び出し元の workspace/surface を特定

ID 指定は **UUID / 短縮ref(workspace:1) / index** のいずれも可。

## ★セッション自己特定（環境変数）

cmux 内で起動したプロセスは以下の環境変数を持つ（= Claude Code セッションが自分のタブを特定できる）:

| 環境変数 | 意味 |
|---|---|
| `CMUX_WORKSPACE_ID` | workspace(タブ) UUID ← **これで session ↔ タブ を対応付け** |
| `CMUX_TAB_ID` | タブ UUID（本環境では workspace_id と同じ） |
| `CMUX_PANEL_ID` | ペインUUID |
| `CMUX_BUNDLE_ID` | `com.cmuxterm.app`（cmux 内判定に使える） |
| `CMUX_PORT` / `CMUX_PORT_RANGE` | ソケットポート |

## 本プロジェクトでの利用設計

- **SessionRegistry（#4）**: SessionStart フックで `CMUX_WORKSPACE_ID` を捕捉し `session_id → {cmux_workspace_id}` を記録。
  `CMUX_BUNDLE_ID` の有無で「cmux 内セッションか」を判定
- **エージェントキー押下 = 選択＋前面化**:
  - cmux モード: `cmux workspace-action --action select --workspace <CMUX_WORKSPACE_ID>` → `cmux focus-window --window <window_ref>`（または `open -a cmux`）
  - app モード: AppleScript 等でアプリ前面化（セッション個別性は cmux ほど確実でない）
- app モードより cmux モードの方が**セッション単位の前面化が正確**（環境変数で一意特定できるため）

## 注意
- `workspace-action --action select` は実行するとタブが切り替わるため、検証時は自セッションのタブが飛ぶ点に注意
- 認証: `--password` / `CMUX_SOCKET_PASSWORD` / Settings のキーチェーンパスワードの順。今回 list 系はプロンプトなしで動作
