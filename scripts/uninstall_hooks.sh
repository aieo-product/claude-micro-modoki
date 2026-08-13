#!/usr/bin/env bash
# Claude Code / Codex 設定から claudemicro 由来のフックだけを削除する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
CLAUDE_CLIENT="$REPO_DIR/hook_client.py"
CODEX_CLIENT="$REPO_DIR/codex_hook_client.py"
USER_HOME="${HOME:?HOME が設定されていません}"
CLAUDE_CONFIG="$USER_HOME/.claude/settings.json"
LEGACY_CLAUDE_CONFIG="$USER_HOME/.claude/settings.local.json"
CODEX_CONFIG="$USER_HOME/.codex/hooks.json"
BACKUP_STAMP="$(date '+%Y%m%d-%H%M%S')-$$"

case "${1:-}" in
    "") ;;
    -h|--help)
        echo "使い方: $0"
        echo "  現在の設定から claudemicro 由来のフックだけを削除します。"
        exit 0
        ;;
    *)
        echo "エラー: 不明な引数です: $1" >&2
        echo "使い方: $0" >&2
        exit 2
        ;;
esac

if [[ $# -gt 1 ]]; then
    echo "エラー: 引数が多すぎます。" >&2
    exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "エラー: 設定の更新に必要な python3 が見つかりません。" >&2
    exit 1
fi
if [[ -e "$LEGACY_CLAUDE_CONFIG" || -L "$LEGACY_CLAUDE_CONFIG" ]]; then
    echo "警告: 旧設定 $LEGACY_CLAUDE_CONFIG が存在します。" >&2
    echo "      このスクリプトは $CLAUDE_CONFIG のみ更新します。" >&2
    echo "      旧設定内の claudemicro フックは必要に応じて手動で除去してください。" >&2
fi

python3 - "$CLAUDE_CONFIG" "$CODEX_CONFIG" "$CLAUDE_CLIENT" \
    "$CODEX_CLIENT" "$BACKUP_STAMP" <<'PY'
import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import sys
import tempfile


targets = (
    (Path(sys.argv[1]), Path(sys.argv[3])),
    (Path(sys.argv[2]), Path(sys.argv[4])),
)
backup_stamp = sys.argv[5]


def load_config(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as source:
            config = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"エラー: {path} を JSON として読めません: {exc}")
    if not isinstance(config, dict):
        raise SystemExit(f"エラー: {path} のルートは JSON オブジェクトである必要があります。")
    hooks = config.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise SystemExit(f"エラー: {path} の hooks は JSON オブジェクトである必要があります。")
    if isinstance(hooks, dict):
        for event, groups in hooks.items():
            if not isinstance(groups, list):
                raise SystemExit(f"エラー: {path} の hooks.{event} は配列である必要があります。")
            for group in groups:
                if not isinstance(group, dict):
                    raise SystemExit(f"エラー: {path} の hooks.{event} に不正なグループがあります。")
                commands = group.get("hooks")
                if commands is not None and not isinstance(commands, list):
                    raise SystemExit(f"エラー: {path} の hooks.{event}[].hooks は配列である必要があります。")
    return config


def is_our_command(command, client: Path) -> bool:
    if not isinstance(command, dict) or command.get("type") != "command":
        return False
    command_text = str(command.get("command", ""))
    try:
        return str(client) in shlex.split(command_text)
    except ValueError:
        # 壊れた shell 引用符があっても、文字列上明らかな場合は出自付きとする。
        return str(client) in command_text


def remove_our_hooks(config: dict, client: Path) -> int:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event, groups in list(hooks.items()):
        kept_groups = []
        for group in groups:
            commands = group.get("hooks")
            if not isinstance(commands, list):
                kept_groups.append(group)
                continue
            kept_commands = []
            for command in commands:
                if is_our_command(command, client):
                    removed += 1
                else:
                    kept_commands.append(command)
            if len(kept_commands) == len(commands):
                kept_groups.append(group)
            elif kept_commands:
                group["hooks"] = kept_commands
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        elif groups:
            del hooks[event]
    if not hooks:
        config.pop("hooks", None)
    return removed


def atomic_write(path: Path, config: dict):
    mode_bits = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode_bits)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(config, target, ensure_ascii=False, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def make_backup(path: Path):
    """削除直前の現在設定を、属性を保ったタイムスタンプ付きファイルに保存する。"""
    backup = path.with_name(path.name + f".claudemicro.bak.{backup_stamp}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{backup.name}.", dir=path.parent)
    os.close(descriptor)
    try:
        shutil.copy2(path, temporary_name)
        os.replace(temporary_name, backup)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    print(f"バックアップ: {backup}")


# 一方の JSON が不正な場合にも部分更新しないよう、先に両方を読む。
loaded = [
    (path, client, load_config(path))
    for path, client in targets
    if path.exists()
]

# 全変更をメモリ上で確定し、書換対象すべてのバックアップを先に作る。
planned = []
for config_path, client, config in loaded:
    count = remove_our_hooks(config, client)
    planned.append((config_path, config, count))
for config_path, _config, count in planned:
    if count:
        make_backup(config_path)

for config_path, config, count in planned:
    if count:
        atomic_write(config_path, config)
    print(f"削除: {config_path} ({count} 件)")

existing = {path for path, _client, _config in loaded}
for config_path, _client in targets:
    if config_path not in existing:
        print(f"設定ファイルなし: {config_path}")
PY

echo "claudemicro 由来のフックだけを削除しました。"
