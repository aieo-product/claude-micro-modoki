# モード切替とアクションの挙動（issue #7 / #11）

## モード切替キー（ACT12）

モードは **AI系統(family: claude / codex)** と **文脈(context: app / cmux)** の2軸 × 4通り。
切替キー `ACT12`（マイク右隣・右下）で操作する:

| 操作 | 動作 |
|---|---|
| **tap** | AI系統を切替（claude ⇄ codex）。context は維持 |
| **double** | 文脈を切替（アプリ ⇄ cmux(cli)）。family は維持 |
| **long** | auto（前面アプリ監視で自動切替）に復帰 |

例: `cmux-claude` → tap → `cmux-codex` → double → `codex-app` → tap → `claude-app`。

`config.mode.enabled` から除外したモードには **tap / double でも入らない**（切替先が除外中なら現モードに留まる）。
auto の自動切替・`POST /api/mode` も同様で、API は除外モードに 400 を返す（#77）。
`mode.current` が除外中の場合、起動時は enabled の先頭モードで起動する（除外モードで起動しない）。
`enabled` が list 以外（null 等）・空・未知 id のみのときは全モード扱いに正規化される。

枠(アンビエントリング)表示: **色 = family**（claude=コーラル / codex=青）、**エフェクト = context**（app=点灯 / cmux=呼吸）。

`ACT12` は本 bridge の予約キー。**codex モードでも常に有効**（モードを抜ける手段のため）。

## ★全モードで本アプリが頭脳。パススルーは「アクション実行だけ」（重要・明記）

**config 解釈・エージェント選択/表示・LED は全モードで本アプリが制御する**（codex-app 含む）。
エージェント表示を統合するため、**本アプリが codex アプリ側も制御する**。
モードで変わるのは **アクションの"実行先"だけ**。決定（どのアクションか）は常に本アプリの設定に従う。

| モード | 頭脳(config/表示/LED/エージェント) | アクションの実行先 |
|---|---|---|
| claude-app | 本アプリ | 本アプリが Claude アプリへキー送出 |
| cmux-claude | 本アプリ | 本アプリが cmux タブの CLI へ送出 |
| **codex-app** | **本アプリ** | **公式 Codex アプリへ委譲（実行だけパススルー）** |
| **cmux-codex** | **本アプリ** | **本アプリが cmux タブの codex CLI へ送出** |

- **codex-app**: 本アプリの設定通りに判定・表示し、**codex アクションの"実行"のみ公式 Codex アプリへ委譲**する
  （公式アプリを実行器として使う）。エージェント選択・LED・枠表示は本アプリが行い、表示を統合する。
- **cmux-codex**: codex を CLI で使うため公式アプリが検知不可 → **本アプリが実行まで担う**。
  cmux の session 情報（`CMUX_WORKSPACE_ID`）取得も必要なので実装はまるごと不要にはならない。
- 実装: `_on_gesture` は全モードで処理（早期 return しない）。実行先の分岐は `run_action` / `_exec_action`。
  承認系（approve/reject/hold）は本アプリが直接解決（Claude Code hook 由来の保留要求）。
- 注意: codex-app では公式アプリも HID を掴んでいるため LED 上書き競合があり得る。本アプリは
  枠・LED を定期再アサートして表示統合を優先する（公式アプリ側の Codex Micro 連携を切ると安定）。

## claude モードのアクション

claude 系モード（`claude-app` / `cmux-claude`）では本 bridge が主体:
- エージェントキー = 選択＋前面化（cmux はタブ select、app はアプリ前面化）
- アクションキー = カタログのアクションを実行（承認/拒否/保留は保留要求を解決、他は順次実装）
- 承認は**アクションキー**で行う（旧: エージェントキーの tap/double/long による承認は廃止。競合のため）
