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

枠(アンビエントリング)表示: **色 = family**（claude=コーラル / codex=青）、**エフェクト = context**（app=点灯 / cmux=呼吸）。

`ACT12` は本 bridge の予約キー。**codex モードでも常に有効**（モードを抜ける手段のため）。

## ★codex の2モードは挙動が異なる（重要・明記）

codex 系でも **codex-app と cmux-codex で本 bridge の役割が真逆**になる。取りこぼし注意。

### codex-app = パススルー（原作 Codex Micro 同等）
公式 Codex(ChatGPT) アプリが起動中で、デバイスのキーイベントを直接処理する。
- HID は非排他 open のためキーは公式アプリと本 bridge の両方に届く。両方が反応すると二重動作になる。
- 方針: 本 bridge は**介入せず素通し**（エージェント選択・アクション・LED を公式に委ねる）。
  → エージェントのフォーカス等が**原作通り**に動く。`set_agent_led` は no-op、枠色のみ本 bridge が表示。
- 実装: `is_passthrough()`（family=codex かつ context=app）が True のとき `_on_gesture` は `ACT12` 以外 early return。
- **本アプリの codex アクション設定は、codex-app では実行されない**（公式アプリ側の設定・動作がそのまま反映される）。
  ユーザーは公式アプリ側で codex の挙動を設定する。

### cmux-codex = 本 bridge が実装（公式アプリでは検知不可）
codex を **CLI で cmux 内**で使うケース。公式 Codex アプリはこの CLI セッションを検知できない。
- したがって**本 bridge が実装する**: エージェントキー = cmux タブ前面化（`workspace-action --action select`）、
  アクションキー = **本アプリで設定した codex アクション**を実行（codex CLI へキーストローク送出等）。
- cmux では session 情報（`CMUX_WORKSPACE_ID`）取得が必須なので、実装はまるごと不要にはならない。
- **本アプリでセットした codex 動作は、cmux-codex ではその設定通りに動作する**。

まとめ: **codex-app = 素通し（原作互換）／ cmux-codex = 本アプリ設定で動作**。

## claude モードのアクション

claude 系モード（`claude-app` / `cmux-claude`）では本 bridge が主体:
- エージェントキー = 選択＋前面化（cmux はタブ select、app はアプリ前面化）
- アクションキー = カタログのアクションを実行（承認/拒否/保留は保留要求を解決、他は順次実装）
- 承認は**アクションキー**で行う（旧: エージェントキーの tap/double/long による承認は廃止。競合のため）
