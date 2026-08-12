# claude-micro-modoki

Claude Code の承認操作とエージェント状態表示を **Codex Micro**（Work Louder 製マクロパッド）の物理キーと LED で行うプロジェクト。Codex 純正「Agent Keys」の Claude Code 版（もどき）です。

[verylowfreq/m5stack_claudecode_approval_console](https://github.com/verylowfreq/m5stack_claudecode_approval_console)（MIT）をベースに、デバイス層を M5Stack（WebSocket）から Codex Micro（raw HID）へ差し替える改修を行います。

## ドキュメント

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

**→ [docs/setup.md](docs/setup.md) を参照**（要点: 有線モード＝白 / bridge に入力監視付与 / **公式アプリの入力監視を OFF にして連携を切る** / `.venv` で `server.main` 起動 / hook 設定）。

旧 M5Stack 版（upstream）は `firmware/` と `bridge.py` に残置。

## ライセンス

MIT License — upstream: © 2026 Mitsumine Suzu (verylowfreq) / fork 部分: © 2026 aieo-product
