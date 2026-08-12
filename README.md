# claude-micro-modoki

Claude Code の承認操作とエージェント状態表示を **Codex Micro**（Work Louder 製マクロパッド）の物理キーと LED で行うプロジェクト。Codex 純正「Agent Keys」の Claude Code 版（もどき）です。

[verylowfreq/m5stack_claudecode_approval_console](https://github.com/verylowfreq/m5stack_claudecode_approval_console)（MIT）をベースに、デバイス層を M5Stack（WebSocket）から Codex Micro（raw HID）へ差し替える改修を行います。

## ドキュメント

- 📐 **設計書**: [docs/index.html](docs/index.html)（GitHub Pages: https://aieo-product.github.io/claude-micro-modoki/ ）
- ✅ **タスク一覧**: [TASKS.md](TASKS.md)

## 現在の状態

Phase 0（Codex Micro の raw HID 実機検証）待ち。現時点のコードは upstream のもの（M5Stack Core2 向け）がそのまま入っています。

```
Claude Code --PreToolUse hook--> hook_client.py --HTTP:35703--> bridge.py --WS:35704--> デバイス
```

## セットアップ（upstream 版・M5Stack）

1. `firmware/core2_approval_device` を Arduino IDE で M5Stack Core2 for AWS に書き込む（M5Unified / FastLED / ArduinoJson / WebSockets が必要）
2. 対象プロジェクトの `.claude/settings.local.json` に `examples/settings.local.json` の内容をコピーし、`hook_client.py` のパスを書き換える
3. `python3 bridge.py` を常駐させる
4. Claude Code を起動して作業する

## ライセンス

MIT License — upstream: © 2026 Mitsumine Suzu (verylowfreq) / fork 部分: © 2026 aieo-product
