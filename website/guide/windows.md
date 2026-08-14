# Windows サポート

<p><span class="cm-badge exp">実験的・未検証</span></p>

**Windows は未検証です。動作報告・修正 PR を歓迎します。** 実機での動作報告や問題は [issue #21](https://github.com/aieo-product/claude-micro-modoki/issues/21) へお寄せください。

## 未検証ポイント

| 項目 | 状態 |
|---|---|
| HID 共有 open | 未検証 |
| Claude Code / Codex hooks の発火 | 未検証 |
| Windows パスの解決 | 未検証 |
| PyInstaller による `.exe` ビルドと起動 | 未検証 |
| 前面アプリ検知 | **未実装**（auto モードは実質無効。手動モードは利用可能な想定） |

## セットアップ（PowerShell）

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install hidapi aiohttp
.\.venv\Scripts\python.exe -m pip install -r requirements-app.txt
.\.venv\Scripts\python.exe -m app
```

## hook のインストール／削除

hook はアプリ起動やビルドで自動実行されません。**必ず `--dry-run` でプレビューしてから**手動で実行してください。

```powershell
# インストール: プレビュー後に書き込み
.\.venv\Scripts\python.exe .\scripts\install_hooks.py --dry-run
.\.venv\Scripts\python.exe .\scripts\install_hooks.py

# 削除: プレビュー後に書き込み
.\.venv\Scripts\python.exe .\scripts\uninstall_hooks.py --dry-run
.\.venv\Scripts\python.exe .\scripts\uninstall_hooks.py
```

## `.exe` ビルド（未検証）

Windows 版の PyInstaller は同じ Windows 環境上で実行します。

```powershell
.\scripts\build_app.ps1
.\dist\ClaudeMicro\ClaudeMicro.exe
```
