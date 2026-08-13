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

## 5. 常駐化（launchd）

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

## 6. Claude Code の hook 設定

`examples/settings.local.json` を参考に、PreToolUse hook で `hook_client.py` を呼ぶよう設定する
（`~/.claude/settings.json` 等。パスは各自の配置に合わせる）。

## トラブルシュート
- コンソールで「未接続」: 有線モード（白）か / USB 接続 / 手順2の入力監視を確認
- キーを押しても無反応: 承認要求が無い、またはキー割当（binding）未設定。設定コンソールで割当
- LED が意図せず変わる/戻る: 手順3（公式アプリの入力監視 OFF）が未実施の可能性
- モード切替: ACT12（マイク右隣・右下）タップ=claude/codex、ダブルタップ=アプリ/cmux、長押し=auto
