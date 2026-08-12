# Claude Approval Console × Codex Micro — タスク一覧

upstream: `verylowfreq/m5stack_claudecode_approval_console` (MIT)
fork 先: `aieo-product/claude-micro-modoki`

凡例: 🔴必須 / 🟡条件付き / ⏱目安工数

## Phase 0 — 実機検証（最優先・ここで方式が決まる）

- [~] **T0-1** 🔴 Work Louder「Input」アプリ（= ChatGPT アプリ内 Codex Micro 連携）は認識・動作確認済み。専用 Input アプリ検証は不要と判断
- [x] **T0-2** 🔴 usevia.app（VIA）は非該当。0xFF60 が無く独自 vendor プロトコル（`v.oai.*`）のため VIA は使わない
- [x] **T0-3** 🔴 HID 列挙完了 (2026-08-12)。0xFF60 なし、0xFF00 / Report ID 6 に 64byte 双方向チャネル発見。
      有線モード（タッチセンサーで白）+ 入力監視権限（cmux）で open 成功。非排他 open が必須。
      詳細: `docs/phase0-findings.md` / スクリプト: `tools/t0_3_hid_probe.py`
- [x] **T0-4** 🔴 **完了**。vendor JSON-RPC を解析（ChatGPT.app app.asar）+ 実機で LED 制御・キー読み取り両方成功。
      LED: `v.oai.thstatus`(スレッド別) / `v.oai.rgbcfg`(キー+アンビエント)。キー入力も同チャネルに JSON 通知。
      詳細: `docs/vendor-protocol.md` / 実装: `server/device.py` / 検証: `tools/t0_4_*.py`
- [x] **T0-5** **判定: 純正ファームで実現可 → Phase 4（QMK 自前ビルド）はスキップ**。読み書き両方が vendor チャネルで可能

## Phase 1 — fork・リポジトリ基盤

- [ ] **T1-1** 🔴 aieo-product へ fork（`setup_fork.sh` 参照）、リポジトリ名 `claude-micro-modoki` に変更 ⏱0.5h
- [ ] **T1-2** 🔴 `docs/index.html`（本設計書）をコミットし、GitHub Pages（main / docs）を有効化 ⏱0.5h
- [ ] **T1-3** 🔴 README で参照されているのに upstream に同梱されていない `settings.local.json` のサンプルを `examples/` に追加 ⏱0.5h
- [ ] **T1-4** LICENSE に upstream の著作権表記を維持したまま fork の追記を行う ⏱0.5h
- [ ] **T1-5** `claudecode.log` など生成物の `.gitignore` 追加 ⏱0.2h

## Phase 2 — bridge 再実装

進捗 (2026-08-12): `server/` に bridge v2 の初版を実装済み（aiohttp / asyncio）。
設定コンソール `console/index.html`（公式設定画面を踏襲、`docs/codex-micro-official-ui.md` 参照）、
`config.json` による設定駆動、Web からの承認フォールバック（/api/resolve、Tailscale 経由リモート承認用）、
キー学習（/api/learn）付き。起動: `.venv/bin/python -m server.main` → http://127.0.0.1:35703/

- [x] **T2-1** 🔴 bridge を asyncio で再実装: busy-wait 排除、リクエストID付きキュー、応答タイムアウト（240s）、同時複数リクエスト対応 ⏱6-8h
- [x] **T2-2** 🔴 バインドを 0.0.0.0 → 127.0.0.1 に変更、共有トークン認証（`APPROVAL_BRIDGE_TOKEN`）を追加 ⏱2h
- [x] **T2-3** 🔴 DeviceAdapter インターフェースを定義（`set_led(key, state)` / `on_key_event(cb)` / `clear()`） ⏱2h
      → HidAdapter として実装。set_led は T0-4 解明まで no-op
- [ ] **T2-4** 🔴 HidAdapter 実装（hidapi、切断・再接続処理含む） ⏱6-8h
      → キー読み取り・ジェスチャー検出・再接続は実装済み。実機テストは入力監視権限の付与待ち。LED 書き込みは T0-4 待ち
- [ ] **T2-5** 🟡 WsAdapter として既存 M5Stack 経路を移植（upstream 追従用） ⏱3h
- [ ] **T2-6** hook_client.py 改修: イベント種別透過・session_id 付与・ログローテーション・tool_input 切り詰め ⏱2h

## Phase 3 — hooks 拡張（Agent Keys 相当）

- [ ] **T3-1** 🔴 Notification / Stop / SessionStart フックを追加し、LED 状態（入力待ち・完了）に反映 ⏱3h
- [ ] **T3-2** 🔴 SessionRegistry 実装: session_id ↔ Agent Key(1-6) 割当、SessionStart で確保・終了で解放、7 本目以降は共有キーに集約 ⏱4h
- [ ] **T3-3** キー操作定義の実装: tap=allow / long=deny / double=ask ⏱2h
- [ ] **T3-4** ロータリーエンコーダー / ジョイスティックの割当検討（任意: セッション切替・音量等） ⏱2h

## Phase 4 — ファームウェア（T0-5 で「不可」判定の場合のみ）→ **スキップ確定**

T0-5 で純正ファームでの読み書きが確認できたため Phase 4 全体を実施しない。
（純正ファームは vendor JSON-RPC `v.oai.*` を Report ID 6 で提供。QMK 化・文鎮化リスク回避）

- [-] **T4-1** ~~QMK 環境構築~~ 不要
- [-] **T4-2** ~~raw HID コマンド実装~~ 不要（純正が SET_LED 相当 = thstatus/rgbcfg を提供）
- [-] **T4-3** ~~書き戻し手順~~ 不要

## Phase 5 — QA・運用

- [ ] **T5-1** launchd（macOS）/ systemd（Linux）での bridge 常駐化手順を作成 ⏱2h
- [ ] **T5-2** 実運用テスト 1 週間（複数セッション・タイムアウト・USB 抜き差し） ⏱-
- [ ] **T5-3** README 全面改訂（セットアップ手順・トラブルシュート） ⏱3h
- [ ] **T5-4** 🟡 upstream への還元検討（DeviceAdapter 化は本家にも有益なため PR 候補） ⏱-

## 依存関係

```
T0-1..4 ─→ T0-5 ─┬→ Phase 2（純正ファームで可の場合）
                  └→ Phase 4 → Phase 2（自前ビルドが必要な場合）
Phase 1 は並行実施可 / Phase 3 は Phase 2 完了後 / Phase 5 は最後
```
