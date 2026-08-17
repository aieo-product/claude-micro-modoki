# Codex Micro 公式設定画面の観察メモ

出典: `userInput/codexMicroCapture/画面収録 2026-08-12 13.48.12.mov`（ChatGPT アプリ > 設定 > 連携 > Codex Micro、2026-08-12 収録）

## 画面構成

1. **接続カード**
   - 接続: 接続済み
   - バッテリー: 90% + 充電中アイコン（→ 無線動作あり）
   - 入力監視: 許可済み（「macOS で Codex Micro のキー入力に必要です」→ **公式アプリも Input Monitoring を要求**。我々の TCC 調査結果と整合）
   - 明るさ: スライダー 0–100%
   - 自動調光: ドロップダウン（例: 3 分）。「操作がないとオフ、エージェントキーの色や状態が変わると再度オン」

2. **レイアウト**（クリック可能なパッド実物図・「レイアウトをリセット」あり）
   - 1 段目: ジョイスティック（丸・白）/ キー ×2 / 黒丸（エンコーダーor電源?）
   - 2 段目: エージェントキー系 ×4（紫ドット表示）
   - 3 段目: アクションキー ×4（FAST⚡ / APPR✓ / REJ✗ / FORK 系アイコン）
   - 4 段目: RGB ドット付き黒丸（ノブ）/ 幅広マイクキー 🎙 / CODEX キー
   - キークリック → 「キーキャップを編集」モーダル
   - ジョイスティッククリック → 「アナログスティック」モーダル

3. **キーキャップを編集モーダル**（例: ACT06）
   - キーキャップギャラリー（刻印を選ぶ）: FAST / APPR / REJ / FORK / MIC1 / CODEX / BUG / OAI / TERM / DWN / DEL / NEW / NAV / MAGIC / DIFF / PLAY / GIT / DRAFT / BRANCH / MRG / PR / PAINT / LAB / PARTY / TIME / MIND+ / MIND- / EMPT1–4 / SETUP / FOLD / UPL / APPS / :yolo: / :yeet:
   - 「割り当て済みショートカットまたはスキル」選択ドロップダウン。カテゴリ: Chat 系アクション（サイドチャットを開く / チャットをアーカイブ / ピン留め切替 / 一時チャット / 新しいウィンドウで開く）、アプリ操作（元に戻す / やり直す / 設定 / 音声チャット系）、スキル（Figma 系, Agents SDK, Browser…）、環境アクション 1–3、ブランチを作成 等
   - 「キーキャップのデフォルト: 高速モードを切り替え」= 刻印にデフォルト動作が紐付く

4. **アナログスティックモーダル**: 上/右/下/左 それぞれに割り当て（観察時: 上=プランモード切替 / 右=進む / 下=サイドバー切替 / 左=前へ）。同じアクション/スキル検索 UI

5. **オプション**
   - エージェントキー: 「6 つのエージェントキーがフォローまたはトリガーする対象を選択」→ 最近のチャット（他選択肢あり）
   - ノブ: 入力欄内の移動 / 推論のみ（推論エフォート調整）/ 会話のスクロール / **カスタム割り当て（回転・クリック・長押しに個別アクション）**
   - マイクキー: プッシュトゥトーク（他選択肢あり）
   - マイクキーを個別に使用: トグル（幅広キー下の 2 スイッチを個別割り当て）
   - 1 回のタップで Codex にフォーカス: トグル

## 公式アプリのメニューショートカット（実機採取, #42）

`System Events` で ChatGPT.app のメニューバーを読み取り（`AXMenuItemCmdChar` / `AXMenuItemCmdModifiers`）採取した実在の割当。
`server/main.py` の `CODEX_APP_KEYSTROKE_MAP` はこの表に基づく（推測での追加は禁止）。

| メニュー | 項目 | ショートカット | 本アプリのアクション |
|---|---|---|---|
| ファイル | 新しいチャット | ⌘N | `new-session` |
| ファイル | 新しいウィンドウ | （割当なし） | 未対応（メニュー操作が必要） |
| 表示 | サイドバーを切り替える | ⌘B | `sidebar-toggle` |
| 表示 | ターミナルを開く | ⌃⌥@ | `focus-term` |
| 表示 | レビューパネルの表示を切り替え | ⌘⌥B | `diff` |
| 表示 | 前のチャット / 次のチャット | ⌘⇧[ / ⌘⇧] | `prev-session` / `next-session` |
| 表示 | 前へ / 進む | ⌘[ / ⌘] | `back` / `forward` |
| 表示 | 下部パネル / ファイルツリー / 検索 | ⌘J / ⌘⇧E / ⌘F | 未割当（対応アクション未定義） |

未記載のアクション（fork / git / pr / archive / pin 等）は**メニューにショートカットが見つからなかった**もの。
実装するにはメニュー項目クリック（AXPress）等が必要で、現状は送出しない（誤操作回避）。


## 公式アプリのキーボードショートカット設定（実機採取, #51）

> 採取環境: **ChatGPT.app 26.803.81509**（既定値はアプリ更新で変わりうる）

ChatGPT.app の **設定 → キーボードショートカット** は全アクションにキーを割当できる一覧。
既定で割当済みのものは**セットアップ不要**で送出できる（`CODEX_APP_KEYSTROKE_MAP`）。

| アクション | 既定 | 本アプリ |
|---|---|---|
| 新しいチャット | ⌘N | `new-session` |
| 一時チャット | ⇧⌘N | `temp-chat` |
| チャットをアーカイブ | ⇧⌘A | `archive` |
| サイドチャットを開く | ⌥⌘S | `side-chat` |
| ピン留めを切り替え | ⌥⌘P | `pin` |
| Codex に切り替え | ⌃3 | `codex-focus` |
| サイドバーを切り替える | ⌘B | `sidebar-toggle` |
| ターミナルを開く | ⌃@（JIS 表示 `^\``） | `focus-term` |
| レビューパネルの表示を切り替え | ⌥⌘B | `diff` |
| 前/次のチャット | ⇧⌘[ / ⇧⌘] | `prev-session` / `next-session` |
| 前へ / 進む | ⌘[ / ⌘] | `back` / `forward` |
| リクエストを承認 / 拒否 | ⏎ / Escape | （承認は bridge 側で解決するため未使用） |

### 既定が「未割り当て」のもの（ユーザー割当が必要）
コミットまたはプッシュ / ブランチを作成 / ドラフト PR を作成 / PR を作成 / PR をマージ /
GitHub で PR を開く / 高速モードを切り替え / プランモードの切り替え / 推論の負荷（切替・上げ・下げ）/
新しいウィンドウで開く 等。

> **★アプリのショートカット割当をローカルに書き込む手段は見つかっていない**。実測（ChatGPT.app 26.803.81509）
> では、UI で割当を変更しても `com.openai.chat.plist` / `com.openai.codex.plist` / `~/.codex/config.toml` の
> いずれにも反映されなかった（アカウント同期の可能性が高いが未確定）。したがって**現時点でスクリプトによる
> 一括設定は行えない**ため、各自がアプリ内で割り当て、本アプリの `CODEX_APP_KEYSTROKE_MAP` に追記して送出する。
> 将来ローカル設定手段が判明した場合はこの記述を更新すること。

## 公式デバイス設定のスキーマ（`~/.codex/config.toml`）

公式アプリの Codex Micro 設定は **TOML でローカル保存**されており、機械可読:

```toml
[desktop]
codex-micro-lighting-brightness = 100
codex-micro-single-tap-agent-keys = false
codex-micro-agent-source = "pinned"

[desktop.codex-micro-layout]
version = 1
encoderMode = "reasoning"        # ノブ
voiceButtonMode = "push-to-talk" # マイクキー
separateMicrophoneKeys = false

[desktop.codex-micro-layout.slots.ACT07]
keycapId = "APPR"                # キーキャップ表示

[desktop.codex-micro-layout.analogStick.up]
type = "command"
commandId = "composer.togglePlanMode"   # 十字: 公式 commandId
# right=navigateForward / down=toggleSidebar / left=navigateBack
```

本アプリの `analog_stick` / `knob` / `mic_key` 既定は上記公式既定と一致している。
将来的にこの TOML を読み取れば、公式アプリで設定済みのユーザーは**追加設定ゼロ**で本アプリに反映できる。


## モード非依存のアクション実行（#55）

本家のアナログスティック設定は family（claude/codex）の区別が無く、同じ割当がそのまま機能する。
本アプリもこれに合わせ、両系統に存在する概念（例: プランモード切替）は `scope: common` とし、
**モードで弾かず、実行手段をモードごとに選ぶ**:

| モード | 実行手段 |
|---|---|
| claude 系（claude-app / cmux-claude） | `KEYSTROKE_MAP`（例: プランモード = Shift+Tab） |
| codex-app | `CODEX_APP_KEYSTROKE_MAP` + **`config.codex_app_shortcuts`（ユーザー上書き）** |
| cmux-codex（codex CLI） | `config.terminal_shortcuts`（上書き）> **`CODEX_CLI_KEYSTROKE_MAP`**（#57 の調査で確認済み）> Claude 固有コマンドは送らない |

### 公式側で既定未割り当ての機能を使う
プランモード切替・高速モード・推論負荷・git/PR などは公式アプリの既定ショートカットが無い。
1. 公式アプリの **設定 > キーボードショートカット** で任意のキーを割り当てる
2. 本アプリの設定 `codex_app_shortcuts` に登録する（**コード変更不要**）

```json
{ "codex_app_shortcuts": {
    "plan-mode": { "text_key": "y", "modifiers": ["command", "option"] } } }
```

端末（cmux-codex 等）で Claude 固有ガードを越えて送りたい場合は `terminal_shortcuts` を使う:

```json
{ "terminal_shortcuts": {
    "plan-mode": { "key_code": 48, "modifiers": ["shift"] } } }
```

未登録のまま実行すると、ログに「codex-app 未割当: 公式アプリの設定 > キーボードショートカットで
割り当て、設定の codex_app_shortcuts に登録してください」と表示される。

## codex CLI のキーバインド（実機調査, codex-cli 0.147.0 / issue #57）

TUI の実装・公式ソース・ドキュメントを突き合わせた調査結果より、**confirmed のもののみ**採用:

| アクション | codex CLI |
|---|---|
| プランモード切替 | **Shift+Tab**（Default/Plan の循環。直接入るなら `/plan`） |
| 推論エフォート | **Option+.** で上げ / **Option+,** で下げ（別名 Shift+↑/↓） |
| 実行中の中断 | **Esc** |
| コンパクト / 新規 / 再開 | `/compact` / `/new` / `/resume` |
| 差分 / 高速モード / サイド会話 | `/diff` / `/fast` / `/side` |
| アーカイブ / フォーク / 承認モード | `/archive` / `/fork` / `/permissions` |

> 補足: Shift+Tab は**モデル選択ではなく Plan モード循環**。モデル選択は `/model`。
> 会話スクロールは `Ctrl+T`（トランスクリプト）を開いてから pager キー、という2段操作のため未対応。
> git / PR / ブランチ作成 / 前後セッション切替は専用コマンドが無く（unknown）、誤送出回避のため非マップ。

## 本プロジェクトへの反映

- `console/index.html` で 接続カード（バッテリー行含む） / レイアウト図クリック割り当て + 「レイアウトをリセット」 / オプション の構成を踏襲（#93）
  - 「レイアウトをリセット」は本家にも同名ボタンがあるが**対象範囲は未採取**。本アプリでは独自仕様として「レイアウト図とオプション欄で設定する項目」（キー割当・アナログスティック・ノブ・マイクキー・エージェントキー・オプション）を既定に戻す（明るさ・自動調光・承認タイムアウトは対象外。確認ダイアログ→「保存」で確定の 2 段階）
- **キーキャップを編集モーダルは本家構成**（#93）: 刻印ギャラリー（採取 33 種 + EMPT1–4、`server/actions.py` の `KEYCAPS`）→ 刻印を選ぶと「キーキャップのデフォルト」の動作が割り当てに入る → 「割り当て済みショートカットまたはスキル」ドロップダウンで上書き。刻印の既定は採取ベースのみ（`official_config.KEYCAP_MAP` と同一の 18 種。未採取の刻印は既定なし）。刻印 (`keys[*].keycap`) は動作 (`action`) とは別に保存し、本家同様「刻印≠割り当て」を保つ。UNDO/REDO 刻印は公式ギャラリーで未確認のため載せない
  - 刻印の絵文字 (`glyph`) は**本アプリ独自の近似表示**（本家は刻印画像。採取記録は ID 文字列のみで画像は未採取）。ID 文字列の方が採取根拠のある表示
- ジョイスティックのクリックで「アナログスティック」モーダル（本家同様。#93 で末尾カードから移設）
- 本アプリ固有の要素（実機キー学習・役割=エージェントキー/未割り当て・モード切替・承認待ち・テスト発火・イベント監視・承認タイムアウト）は本家に無いが維持
- アクション体系は Claude Code 用に置換: accept(allow) / fallback(ask) / deny + エージェントキー 1–6
- スキル割り当て・マイク/音声系の実動作は対象外（マイクは #68、ノブのカスタム割り当ては設定のみ #34/#35）
- エージェントキー「最近のチャット」≒ 我々の SessionRegistry LRU 方式（設計と一致）
