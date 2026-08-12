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

## ★codex モードは「原作 Codex Micro 同等」のパススルー（重要・明記）

codex 系モード（`codex-app` / `cmux-codex`）では、**本 bridge はデバイス操作に介入しない**。

- 理由: 公式 Codex(ChatGPT) アプリが Codex Micro のキーイベントを直接処理する。HID は非排他 open のため
  キーは公式アプリと本 bridge の両方にブロードキャストされる。両方が反応すると二重動作になる。
- 方針: codex モードでは本 bridge はエージェント選択・アクション実行を**行わず、公式アプリにそのまま委ねる**。
  これにより **エージェントのフォーカスやアクションが原作（純正 Codex Micro）通りに動く**。
- LED も codex family では公式アプリに譲る（`set_agent_led` は no-op）。枠の色だけは本 bridge が表示。
- 実装: `server/main.py` の `_on_gesture` で、`ACT12`（モード切替）以外は codex family 時に early return。

つまり **「このアプリでラップした動作のまま codex に伝える」= 何もラップせず素通しする** ことで原作互換を実現する。

## claude モードのアクション

claude 系モード（`claude-app` / `cmux-claude`）では本 bridge が主体:
- エージェントキー = 選択＋前面化（cmux はタブ select、app はアプリ前面化）
- アクションキー = カタログのアクションを実行（承認/拒否/保留は保留要求を解決、他は順次実装）
- 承認は**アクションキー**で行う（旧: エージェントキーの tap/double/long による承認は廃止。競合のため）
