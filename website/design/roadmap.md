# ロードマップ

進行は [GitHub Issues](https://github.com/aieo-product/claude-micro-modoki/issues) で管理しています。2026-08-13 時点の状況です。

## フェーズ概観

| フェーズ | 内容 | 状態 |
|---|---|---|
| Phase 0 | vendor プロトコル解明（Report ID 6 JSON-RPC） | <span class="cm-badge done">完了</span> |
| Phase 2 | bridge v2（asyncio + raw HID）・hook クライアント | <span class="cm-badge done">完了</span>（切断・再接続の実機検証 [#3](https://github.com/aieo-product/claude-micro-modoki/issues/3) が残） |
| Phase 3 | 4モード・SessionRegistry・LED 状態機・イベント取込 | <span class="cm-badge wip">大半完了</span> |
| Phase 5 | 手軽化: launchd 常駐・トレイアプリ・Windows 対応 | <span class="cm-badge wip">マージ済み・実機検証中</span> |
| 次期 | Claude Desktop 対応（BLE バディ化・統合ファーム） | <span class="cm-badge plan">調査・設計中</span> |

## 完了した主なマイルストーン

- <span class="cm-badge done">#1</span> vendor プロトコル解明 — 純正ファームのまま読み書き実現、QMK 自前ビルド不要に
- <span class="cm-badge done">#2</span> hook_client の bridge v2 対応
- <span class="cm-badge done">#4</span> SessionRegistry — セッション ↔ エージェントキーの LRU 割当・前面化
- <span class="cm-badge done">#6</span> LED 状態機を本家凡例準拠に
- <span class="cm-badge done">#7 #11</span> 4モード化と codex パススルー設計
- <span class="cm-badge done">#18(中核)</span> claude + codex 二系統 hooks によるイベント取込
- <span class="cm-badge done">#22</span> 承認ゲート対象ツールのフィルタ
- <span class="cm-badge done">#20</span> トレイアプリ化（pystray + pywebview + PyInstaller）
- <span class="cm-badge done">#21</span> Windows 対応（未検証・検証歓迎ポリシー）

## 進行中・予定

| Issue | 内容 | 状態 |
|---|---|---|
| [#25](https://github.com/aieo-product/claude-micro-modoki/issues/25) | Claude Desktop 公式ハードウェアバディ (BLE) のプロトコル調査 | <span class="cm-badge wip">調査中</span> |
| [#27](https://github.com/aieo-product/claude-micro-modoki/issues/27) | ファーム書換の前提調査 — 分解不要のブートローダ移行・バックアップ確立 | <span class="cm-badge done">前提確認済み</span> |
| [#29](https://github.com/aieo-product/claude-micro-modoki/issues/29) | 統合ファーム設計: USB HID キーパッド + BLE バディ両立（ESP32-S3） | <span class="cm-badge plan">設計中</span> |
| [#18](https://github.com/aieo-product/claude-micro-modoki/issues/18) | codex 状態を app-server プロトコルで取込（4種統合監視） | <span class="cm-badge wip">残タスク</span> |
| [#8](https://github.com/aieo-product/claude-micro-modoki/issues/8) | 設定コンソールの実機連動（キー学習・LED・承認） | <span class="cm-badge wip">進行中</span> |
| [#30](https://github.com/aieo-product/claude-micro-modoki/issues/30) | トレイアプリ実機バグ（終了時 join タイムアウト・auto 前面検知の往復） | <span class="cm-badge wip">修正予定</span> |
| [#9](https://github.com/aieo-product/claude-micro-modoki/issues/9) | Tailscale リモート承認・README 整備 | <span class="cm-badge plan">一部完了</span> |
| [#3](https://github.com/aieo-product/claude-micro-modoki/issues/3) | HidAdapter 切断・再接続・スリープ復帰の実機検証 | <span class="cm-badge plan">未着手</span> |

Claude Desktop 対応の全体像は [Claude Desktop 対応（予定）](/guide/claude-desktop) を参照してください。
