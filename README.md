# claude-micro-modoki

Claude Code の承認操作とエージェント状態表示を **Codex Micro**（Work Louder 製マクロパッド）の物理キーと LED で行うプロジェクト。Codex 純正「Agent Keys」の Claude Code 版（もどき）です。

[verylowfreq/m5stack_claudecode_approval_console](https://github.com/verylowfreq/m5stack_claudecode_approval_console)（MIT）をベースに、デバイス層を M5Stack（WebSocket）から Codex Micro（raw HID）へ差し替える改修を行います。

## ドキュメント

- 🌐 **ドキュメントサイト（設計書 + セットアップガイド）**: https://aieo-product.github.io/claude-micro-modoki/ （ソース: `website/`、main への push で自動デプロイ）
- 🛠 **セットアップ手順**: [docs/setup.md](docs/setup.md)（有線モード / 入力監視 / **公式アプリ連携の切り方**）
- 🔌 **vendor プロトコル**: [docs/vendor-protocol.md](docs/vendor-protocol.md)（Report ID 6 の JSON-RPC）
- 🎛 **モード/アクション挙動**: [docs/mode-behavior.md](docs/mode-behavior.md)（4モード・codex パススルー）
- 🧩 **cmux 連携**: [docs/cmux-integration.md](docs/cmux-integration.md)（タブ制御 CLI）
- 📐 設計書: [docs/index.html](docs/index.html) / ✅ タスク: [TASKS.md](TASKS.md) / 進行は GitHub Issues

## 現在の状態

Phase 0 完了（純正ファームの vendor JSON-RPC で読み書き実現、QMK 自前ビルドは不要）。
bridge v2（`server/`）を asyncio で実装し、Codex Micro を raw HID で駆動。

```
Claude Code --PreToolUse hook--> hook_client.py --HTTP:35703--> bridge(server/) --raw HID--> Codex Micro
```

- 4モード（claude-app / codex-app / cmux-claude / cmux-codex）。config・表示・LED は全モードで本アプリが制御
- codex-app は「アクションの実行だけ」公式 Codex アプリへ委譲（`docs/mode-behavior.md`）
- 設定コンソール（Claude 配色）: http://127.0.0.1:35703/

## セットアップ

macOS の設定は **→ [docs/setup.md](docs/setup.md) を参照**（要点: 有線モード＝白 / bridge に入力監視付与 / **公式アプリの入力監視を OFF にして連携を切る** / `.venv` で `server.main` 起動 / hook 設定）。Windows は後述の未検証手順を参照してください。

旧 M5Stack 版（upstream）は `firmware/` と `bridge.py` に残置。

## トレイアプリ

既存 bridge と設定コンソールを、デスクトップのメニューバー／システムトレイに常駐する薄いアプリ層から利用できます。追加の GUI 依存はヘッドレス bridge から分離されています。以下の例は macOS です。

```bash
.venv/bin/pip install hidapi aiohttp
.venv/bin/pip install -r requirements-app.txt
.venv/bin/python -m app
```

既定の `35703` が使われている場合は既存 bridge を停止するか、CLI または環境変数で別ポートを指定します（CLI の指定が優先）。実機を使う bridge はポートが異なってもデバイスを奪い合うため、トレイアプリへ切り替える前に既存の手動起動・常駐サービス（macOS の launchd など）を停止してください。

```bash
.venv/bin/python -m app --port 35704
CLAUDEMICRO_PORT=35704 .venv/bin/python -m app
```

hook クライアント（`hook_client.py` / `codex_hook_client.py`）とヘッドレス bridge（`python -m server.main`）も同じ `CLAUDEMICRO_PORT` を尊重します。hooks は Claude Code / codex 側のプロセス環境の環境変数を読むため、別ポート運用ではその環境にも同じ値を設定してください（hook 側の未設定・不正値は既定 `35703`）。`0`（OS 割当）はスモーク・UI 確認専用で、hooks が接続先を特定できないため承認フローでは使えません。

GUI を出さない起動確認では、GUI 依存を import せず、OS が選ぶ空きポートで bridge の応答と終了処理を検証します。

```bash
CLAUDEMICRO_NO_DEVICE=1 .venv/bin/python -m app --smoke
```

macOS アプリのビルドは、アプリ用依存をインストールした `.venv` から行います。

```bash
./scripts/build_app.sh
open dist/ClaudeMicro.app
```

詳しい準備、launchd 版との切り替え、GUI の確認手順は [docs/setup.md](docs/setup.md#5-トレイアプリgui) を参照してください。

## hook の手動インストール／削除

hook インストーラーはアプリ起動やビルド時に自動実行されません。必ずユーザーが手動で実行し、書き込み前にクロスプラットフォーム Python 版の `--dry-run` で対象ファイル、追加・削除予定のフック、書き込み予定の有無を確認してください。選択肢は「mac は .sh / どの OS でも .py 可」です。

macOS（`.sh` で書き込む場合も、先に `.py` でプレビュー）:

```bash
.venv/bin/python scripts/install_hooks.py --dry-run
./scripts/install_hooks.sh
.venv/bin/python scripts/uninstall_hooks.py --dry-run
./scripts/uninstall_hooks.sh
```

どの OS でも Python 版でインストール／削除できます。Windows では以下を PowerShell から実行します。

```powershell
# インストール: プレビュー後に書き込み
.\.venv\Scripts\python.exe .\scripts\install_hooks.py --dry-run
.\.venv\Scripts\python.exe .\scripts\install_hooks.py

# 削除: プレビュー後に書き込み
.\.venv\Scripts\python.exe .\scripts\uninstall_hooks.py --dry-run
.\.venv\Scripts\python.exe .\scripts\uninstall_hooks.py
```

## Windows サポート（実験的・未検証）

**Windows は未検証です。動作報告・修正 PR を歓迎します。** Windows 実機での動作報告や問題は [GitHub issue #21](https://github.com/aieo-product/claude-micro-modoki/issues/21) へお寄せください。

現在の未検証ポイントは次の 5 点です。

- HID 共有 open
- Claude Code / Codex hooks の発火
- Windows パスの解決
- PyInstaller による `.exe` ビルドと起動
- 前面アプリ検知（未実装）

Windows の前面アプリ検知は未実装のため、auto モードは実質無効です。手動モードは利用可能な想定です。

PowerShell で仮想環境を作成し、依存を入れて起動します。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install hidapi aiohttp
.\.venv\Scripts\python.exe -m pip install -r requirements-app.txt
.\.venv\Scripts\python.exe -m app
```

Windows 版の PyInstaller は同じ Windows 環境上で実行します。ビルドスクリプトも未検証です。

```powershell
.\scripts\build_app.ps1
.\dist\ClaudeMicro\ClaudeMicro.exe
```

hook のインストールと削除は自動実行されません。前節の Python 版コマンドを手動で実行し、必ず `--dry-run` を先に確認してください。

## ライセンス

MIT License — upstream: © 2026 Mitsumine Suzu (verylowfreq) / fork 部分: © 2026 aieo-product
