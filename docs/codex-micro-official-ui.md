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

> **★アプリのショートカットはローカルに保存されない**（実測: 割当変更後も `com.openai.chat.plist` /
> `~/.codex/config.toml` とも不変）＝**アカウント同期**とみられる。よって**スクリプトでの一括設定は不可**で、
> 各自がアプリ内で割り当てる必要がある。割当後は本アプリの `CODEX_APP_KEYSTROKE_MAP` に追記すれば送出できる。

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

## 本プロジェクトへの反映

- `console/index.html` で 接続カード / レイアウト図クリック割り当て / オプション の 3 構成を踏襲
- アクション体系は Claude Code 用に置換: accept(allow) / fallback(ask) / deny + エージェントキー 1–6
- キーキャップ刻印・スキル割り当て・マイク/音声系は対象外（将来: ノブのカスタム割り当ては T3-4 で検討）
- エージェントキー「最近のチャット」≒ 我々の SessionRegistry LRU 方式（設計と一致）
