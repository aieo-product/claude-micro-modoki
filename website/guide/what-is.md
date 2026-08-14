# claude-micro-modoki とは

**Claude Code の承認操作とエージェント状態表示を、Codex Micro（Work Louder 製マクロパッド）の物理キーと LED で行うプロジェクト**です。Codex 純正機能「Agent Keys」の Claude Code 版（もどき）を目指しています。

[verylowfreq/m5stack_claudecode_approval_console](https://github.com/verylowfreq/m5stack_claudecode_approval_console)（MIT）をベースに、デバイス層を M5Stack（WebSocket）から Codex Micro（raw HID）へ差し替えています。

## なにが嬉しいのか

<div class="cm-cards">
  <div class="cm-card">
    <div class="icon">👀</div>
    <h4>ターミナルを見張らなくていい</h4>
    <p>複数の Claude Code セッションを並行で走らせても、承認待ちになるとキーの LED がアンバーに明滅。視界の隅で分かります。</p>
  </div>
  <div class="cm-card">
    <div class="icon">⚡</div>
    <h4>承認が1タップ</h4>
    <p>「このコマンド実行していい？」に対して、承認・保留・拒否をそれぞれ物理キー1タップで応答。どのセッションかはエージェントキーで選択。</p>
  </div>
  <div class="cm-card">
    <div class="icon">🔁</div>
    <h4>codex とも共存</h4>
    <p>Claude Code だけでなく codex CLI / 公式 Codex アプリのセッションも同じパッドで扱えます。モード切替はキー1つ。</p>
  </div>
  <div class="cm-card">
    <div class="icon">🪶</div>
    <h4>とにかく軽い</h4>
    <p>常時ポーリングなし・イベント駆動のみ。複数 AI を運用するマシンでメモリを食い潰さないことを最重要要件に設計しています。</p>
  </div>
</div>

## 仕組み（30秒版）

1. Claude Code / codex の **hooks** がセッションのイベント（プロンプト送信・ツール承認要求・完了・エラー）を発火する
2. hook クライアントがそれを **HTTP でローカルの bridge（ポート 35703）** に転送する
3. bridge が **raw HID（vendor JSON-RPC）** で Codex Micro の LED を更新し、キー入力を受け取る
4. あなたがキーを押すと、bridge が承認応答やセッション前面化を実行する

詳しくは [全体アーキテクチャ](/design/architecture) を参照してください。

## 対応環境

| 環境 | 状態 |
|---|---|
| macOS + Claude Code (CLI) | <span class="cm-badge done">対応済み</span> 本流。実機 E2E 検証済み |
| macOS + codex CLI / 公式 Codex アプリ | <span class="cm-badge done">対応済み</span> 4モードで切替 |
| cmux（ターミナルマルチプレクサ） | <span class="cm-badge done">対応済み</span> タブ単位のセッション前面化 |
| Windows | <span class="cm-badge exp">実験的</span> 未検証・検証歓迎（[issue #21](https://github.com/aieo-product/claude-micro-modoki/issues/21)） |
| Claude Desktop（BLE ハードウェアバディ） | <span class="cm-badge plan">予定</span> ファーム書き換えで対応構想（[詳細](/guide/claude-desktop)） |

## 必要なもの

- **Codex Micro**（Work Louder 製。VID:PID `303A:8360`、ESP32-S3 ベース）
- macOS（Windows は実験的）
- Python 3.10+（`hidapi` と `aiohttp` のみで動作）
- Claude Code（および任意で codex CLI / 公式 Codex アプリ / cmux）

準備ができたら [セットアップ](/guide/setup) へ進みましょう。
