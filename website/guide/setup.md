# セットアップ（macOS）

Codex Micro を Claude Code の承認コンソールにするまで、**約10分**です。上から順に進めてください。

::: tip 事前に用意するもの
Codex Micro 本体・USB ケーブル・macOS・Python 3.10+・Claude Code。リポジトリを clone しておいてください。
```bash
git clone https://github.com/aieo-product/claude-micro-modoki.git
cd claude-micro-modoki
```
:::

<div class="cm-steps">

<div class="cm-step">

#### デバイスを「有線モード」にする
<p class="goal">ゴール: アンダーグロー（本体下面の光）が <b>白</b> になる</p>

Codex Micro 本体の**底面タッチセンサーを長押し → タップで巡回**し、アンダーグローが**白**になったら有線モードです。

::: warning USB ケーブルを挿すだけではダメ
ケーブル接続だけでは**充電のみ**で、有線接続にはなりません。必ずタッチセンサーでモードを切り替えてください。
:::

</div>

<div class="cm-step">

#### Python 環境を作って bridge を起動する
<p class="goal">ゴール: ブラウザで <b>http://127.0.0.1:35703/</b> に設定コンソールが表示される</p>

```bash
python3 -m venv .venv
.venv/bin/pip install hidapi aiohttp
.venv/bin/python -m server.main
```

起動したら設定コンソール <http://127.0.0.1:35703/> を開いてください（Claude 配色の画面。モード切替・キー割当ができます）。

</div>

<div class="cm-step">

#### bridge に「入力監視」権限を付与する
<p class="goal">ゴール: 設定コンソールの「入力監視」が <b>許可済み</b> になる</p>

macOS ではデバイスのキー読み取りに **入力監視（Input Monitoring）** 権限が必要です。

1. **システム設定 > プライバシーとセキュリティ > 入力監視** を開く
2. bridge を起動している**ターミナルアプリ**（Terminal / iTerm2 / cmux など）を追加して **ON**
3. ターミナルアプリを再起動して bridge を起動し直す

::: details launchd 常駐やトレイアプリを使う場合は？
launchd 常駐なら bridge のバイナリ、`.app` ビルド版なら `ClaudeMicro.app` に権限を付与します（後述のステップ参照）。
:::

</div>

<div class="cm-step">

#### 公式 Codex(ChatGPT) アプリの連携を切る ★重要
<p class="goal">ゴール: 公式アプリの設定 > Codex Micro で「入力監視」が <b>未許可</b> になる</p>

本アプリと公式アプリが**同時にデバイスを掴むと競合**します（キーの二重処理・LED の奪い合い）。公式アプリには連携オフのトグルが無いため、**OS の入力監視権限を外して**無効化します。

1. **システム設定 > プライバシーとセキュリティ > 入力監視** を開く
2. リストの **ChatGPT**（公式 Codex アプリ）を **OFF**（または削除）
3. 公式アプリを**再起動**し、設定 > Codex Micro の「入力監視」が「未許可」になっていることを確認

::: tip 公式アプリは起動したままで OK
チャット機能は普通に使えます。`codex-app` モードでは本アプリがアプリ操作レベルで実行を委譲するので、公式アプリがキーを読めなくても問題ありません。
:::

</div>

<div class="cm-step">

#### Claude Code の hook を設定する
<p class="goal">ゴール: Claude Code のツール承認がパッドの LED に出る</p>

hook インストーラーで `~/.claude/settings.json` に PreToolUse などの hook を追加します。**必ず `--dry-run` でプレビューしてから**書き込んでください。

```bash
.venv/bin/python scripts/install_hooks.py --dry-run
./scripts/install_hooks.sh
```

手動で設定する場合は `examples/settings.local.json` を参考にしてください。外すときは:

```bash
.venv/bin/python scripts/uninstall_hooks.py --dry-run
./scripts/uninstall_hooks.sh
```

::: details 承認対象ツールを絞る（任意）
既定では `Bash,Edit,Write,MultiEdit,NotebookEdit` が承認対象です。`CLAUDEMICRO_GATED_TOOLS` で上書きできます（`*` 後方一致対応）。
```bash
export CLAUDEMICRO_GATED_TOOLS='Bash,mcp__*'
```
:::

</div>

<div class="cm-step">

#### 動作確認
<p class="goal">ゴール: 物理キーで承認できた 🎉</p>

1. Claude Code で何かツール実行が必要なプロンプトを送る（例: 「ls を実行して」）
2. エージェントキーの LED が**アンバーに明滅**（承認待ち）することを確認
3. **承認キーをタップ** → Claude Code 側でツールが実行される

<div class="cm-strip">
  <span class="cm-led breath" style="--led:#E8B24A;"></span>
  <span class="cm-led" style="--led:#46C077;"></span>
</div>
<p style="text-align:center;font-size:12px;color:var(--cm-muted);">承認待ち（アンバー明滅）→ タップ → 完了（緑）</p>

</div>

</div>

## 常駐化する（どれか1つを選ぶ）

bridge は**1プロセスだけ**動かします。以下は排他です — 切り替えるときは先に今の方式を止めてください。

| 方式 | 向いている人 | 起動方法 |
|---|---|---|
| **手動起動** | まず試したい | `.venv/bin/python -m server.main` |
| **launchd 常駐** | ログイン時に自動で動いてほしい | `./scripts/install_service.sh` |
| **トレイアプリ** | メニューバーから操作したい | `.venv/bin/python -m app` |

### launchd 常駐

```bash
./scripts/install_service.sh          # インストール（--dry-run でプレビュー可）
./scripts/uninstall_service.sh        # 解除
```

- plist: `~/Library/LaunchAgents/com.claudemicro.bridge.plist`
- ログ: `~/Library/Logs/claudemicro/bridge.log`
- 異常終了時だけ自動再起動します（正常終了では再起動しません）

### トレイアプリ <span class="cm-badge exp">GUI は実機検証中</span>

```bash
.venv/bin/pip install -r requirements-app.txt
.venv/bin/python -m app
```

メニューバーから「コンソールを開く」「ブラウザで開く」「終了」を選べます。`.app` にビルドする場合:

```bash
./scripts/build_app.sh
open dist/ClaudeMicro.app
```

::: warning ポートとデバイスは1つだけ
launchd サービス・手動起動・トレイアプリは**同じポート 35703 と同じデバイス**を使います。同時起動すると競合するので、必ず1つに絞ってください。
:::

## トラブルシュート

| 症状 | 確認すること |
|---|---|
| コンソールで「未接続」 | 有線モード（白）か / USB 接続 / 入力監視権限 |
| キーを押しても無反応 | 承認要求が来ているか / キー割当（binding）を設定コンソールで確認 |
| LED が勝手に変わる・戻る | 公式アプリの入力監視 OFF（ステップ4）が未実施の可能性 |
| モードが分からなくなった | ACT12 長押しで auto（前面アプリ自動切替）に復帰 |
