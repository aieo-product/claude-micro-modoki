# セットアップ手順（Codex Micro × Claude Micro）

本アプリ（bridge + 設定コンソール）を Codex Micro で使うための手順。

## 1. ハードウェア: 有線モードにする

Codex Micro 本体の**タッチセンサー（底面）を長押し → タップで巡回**し、**アンダーグローが白**になったら有線モード。
（USB ケーブルを挿すだけでは充電のみで有線接続にならない。詳細: `docs/phase0-findings.md`）

## 2. 本アプリ（bridge）に入力監視権限を付与

macOS はデバイスのキー読み取りに入力監視（Input Monitoring）権限が必要。

- **システム設定 > プライバシーとセキュリティ > 入力監視** を開く
- bridge を起動する**ターミナルアプリ**（Terminal / iTerm2 / cmux 等）、または launchd 常駐時は bridge のバイナリを追加して ON
- アプリを再起動

確認: 設定コンソール（http://127.0.0.1:35703/）の「入力監視」が「許可済み」になる。

### アクセシビリティ権限（アクション実行に必要, #5）

デバイスのキー**読み取り**は入力監視だが、割り当てたアクションを対象アプリへ
**キーストロークとして送出**するには別途 **アクセシビリティ（Accessibility）** 権限が要る。

- **システム設定 > プライバシーとセキュリティ > アクセシビリティ** を開く
  （※サイドバー先頭の「アクセシビリティ」＝機能設定とは別ページ）
- bridge を起動する**ターミナルアプリ**（cmux 等）、または常駐バイナリを追加して ON
- アプリ／bridge を再起動

| 権限 | 用途 |
|---|---|
| 入力監視（Input Monitoring） | デバイスのキー**読み取り**（承認・エージェント選択・ジェスチャ検出） |
| アクセシビリティ（Accessibility） | アクションの**キー送出**（ノブ回転→スクロール、キー→Esc/compact 等） |

未付与の症状: デバイスのキーは効くが、**割り当てアクションを押しても対象アプリが無反応**
（bridge ログには `keystroke 送出` が出るのに何も起きない）。
確認方法: 空の TextEdit を前面にしてアクションを発火し、文字/スクロールが入るか見る。
キー送出は**前面アプリ**に届くため、対象端末を前面にした状態で操作すること。

## 3. ★公式 Codex(ChatGPT) アプリの Codex Micro 連携を切る（重要）

**本アプリと公式アプリが同時にデバイスを掴むと競合する**（キーの二重処理・LED の奪い合い）。
公式アプリには連携を無効化する in-app トグルが無いため、**OS の入力監視権限を外す**ことで無効化する。

> 根拠: 公式アプリは入力監視権限が無いとデバイスのキーを読めない
> （アプリ内表示「Required for {デバイス名} key presses on macOS」/ `hasInputMonitoringPermission()` を必須チェック）。
> 権限を外せば公式アプリはキーに反応しなくなり、デバイス制御は本アプリに一本化される。

### 手順
1. **システム設定 > プライバシーとセキュリティ > 入力監視** を開く
2. リストの **ChatGPT**（公式 Codex アプリ）を **OFF**（トグルを切る／またはリストから削除）
3. **公式アプリを再起動**（メニュー > 終了 → 再度起動）。設定 > Codex Micro で「入力監視」が「未許可」になっていれば OK

> ⚠️ 公式アプリ自体は起動したままで良い（チャット機能は使える）。
> `codex-app` モードでは本アプリが**アプリ操作レベル**で公式アプリに実行を委譲するため、
> 公式アプリがデバイスのキーを読めなくても問題ない（`docs/mode-behavior.md` 参照）。

### モード別の必要性
| モード | 公式アプリ | 入力監視 |
|---|---|---|
| claude-app / cmux-claude / cmux-codex | 不要（終了でも可） | 公式アプリの入力監視は OFF |
| codex-app | 起動しておく（実行の委譲先） | 公式アプリの入力監視は OFF（本アプリが委譲） |

## 4. Python 環境と bridge 起動

```bash
python3 -m venv .venv
.venv/bin/pip install hidapi aiohttp
.venv/bin/python -m server.main
```

設定コンソール: http://127.0.0.1:35703/ （Claude 配色。モード切替・キー割当）

## 5. トレイアプリ（GUI）

macOS のメニューバーから設定コンソールを開く場合は、bridge の基本依存に加えてアプリ用依存をインストールします。`pystray` / `pywebview` / Pillow は `server.main` には不要で、PyInstaller はビルド時だけ使用します。

```bash
.venv/bin/pip install -r requirements-app.txt
.venv/bin/python -m app
```

トレイメニューから「コンソールを開く」「ブラウザで開く」「終了」を選べます。コンソール窓を閉じても bridge とトレイは常駐し、「コンソールを開く」で再表示できます。

### ポートを変更する

既定ポートはヘッドレス bridge と同じ `35703` です。すでに使用中ならトレイアプリはエラーを表示して終了するため、先に既存 bridge を停止するか、空いているポートを指定してください。`--port` は `CLAUDEMICRO_PORT` より優先されます。実機を使う bridge はポートが異なってもデバイスを奪い合うため、トレイアプリへ切り替える前に既存の手動起動・launchd サービスを必ず停止してください。

```bash
.venv/bin/python -m app --port 35704
CLAUDEMICRO_PORT=35704 .venv/bin/python -m app
```

現在の `hook_client.py` / `codex_hook_client.py` は `35703` に接続します。別ポートは主にデバイス無効時の衝突回避・コンソール確認用で、承認フローを使う場合は hook の接続先と bridge のポートを一致させる必要があります。

### GUI を出さないスモークテスト

`--smoke` は GUI パッケージを import せず、OS が割り当てた空きポートで bridge を起動し、HTTP 応答を確認してから終了します。CI や GUI 依存の未インストール環境でも利用できます。

```bash
CLAUDEMICRO_NO_DEVICE=1 .venv/bin/python -m app --smoke
```

### macOS アプリをビルドする

`requirements-app.txt` をインストールした `.venv` を用意し、リポジトリ直下から次を実行します。PyInstaller が設定コンソールを同梱した windowed アプリを `dist/ClaudeMicro.app` に生成します。

```bash
./scripts/build_app.sh
open dist/ClaudeMicro.app
```

### GUI の動作確認

1. 実機を使っているヘッドレス bridge / launchd サービスをすべて停止する（デバイス無効で UI だけを確認する場合は `CLAUDEMICRO_NO_DEVICE=1` と空きの `--port` を指定してもよい）
2. `.venv/bin/python -m app`（UI だけなら `CLAUDEMICRO_NO_DEVICE=1 .venv/bin/python -m app --port 35704`）を実行し、Claude 配色の丸いトレイアイコンと設定コンソールが表示されることを確認する
3. コンソール窓を閉じてもトレイが残り、「コンソールを開く」で窓が再表示されることを確認する
4. 「ブラウザで開く」で同じ設定コンソールが既定ブラウザに表示されることを確認する
5. 「終了」でトレイと bridge が終了し、使用していたポートが解放されることを確認する

初回起動時は、ソース起動なら使用するターミナルアプリ、バンドル起動なら `ClaudeMicro.app` に手順 2 の入力監視権限を付与してください。

## 6. 常駐化（launchd）

手順 4 で `.venv` を準備し、手動起動中の bridge があれば `Ctrl-C` で停止してから、次のスクリプトを実行します。bridge が現在のログインセッションで起動し、以後はログイン時にも自動起動します。異常終了した場合だけ再起動し、正常終了後は再起動しません。

```bash
./scripts/install_service.sh
```

生成される plist を確認するだけで、ファイル作成や launchd への登録を行わない場合は `--dry-run` を使います。

```bash
./scripts/install_service.sh --dry-run
```

- plist: `~/Library/LaunchAgents/com.claudemicro.bridge.plist`
- 標準出力・標準エラー: `~/Library/Logs/claudemicro/bridge.log`
- 設定コンソール: http://127.0.0.1:35703/

常駐中は手順 4 の `.venv/bin/python -m server.main` を別途実行しないでください。同じポートとデバイスを使用するため競合します。手動起動に戻す場合は、先に次のスクリプトで常駐を解除します。

```bash
./scripts/uninstall_service.sh
```

アンインストールは launchd の登録と plist を削除します。ログファイルは削除しません。再び常駐させる場合はインストールスクリプトをもう一度実行してください。

トレイアプリも同じ bridge とデバイスを使用するため、この launchd サービスと同時に起動しないでください。トレイアプリへ切り替える場合は、先にサービスをアンインストールしてください。

## 7. Claude Code の hook 設定

`examples/settings.local.json` を参考に、PreToolUse hook で `hook_client.py` を呼ぶよう設定する
（`~/.claude/settings.json` 等。パスは各自の配置に合わせる）。

### 承認対象ツールの指定

`CLAUDEMICRO_GATED_TOOLS` で承認対象をカンマ区切りで上書きできる。未設定または空の場合は
`Bash,Edit,Write,MultiEdit,NotebookEdit` が既定値。末尾の `*` は前方一致（例: `mcp__*`）、
単独の `*` はすべてのツールを承認対象にする。

```bash
export CLAUDEMICRO_GATED_TOOLS='Bash,mcp__*'
```

## トラブルシュート
- コンソールで「未接続」: 有線モード（白）か / USB 接続 / 手順2の入力監視を確認
- キーを押しても無反応: 承認要求が無い、またはキー割当（binding）未設定。設定コンソールで割当
- 割り当てアクションを押しても対象アプリが無反応: アクセシビリティ権限（手順2の追記）が未付与か、対象端末が前面でない
- LED が意図せず変わる/戻る: 手順3（公式アプリの入力監視 OFF）が未実施の可能性
- モード切替: ACT12（マイク右隣・右下）タップ=claude/codex、ダブルタップ=アプリ/cmux、長押し=auto
