#!/usr/bin/env bash
# Claude Code / Codex のユーザー設定に claudemicro フックを登録する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
HOOK_PYTHON="$REPO_DIR/.venv/bin/python"
CLAUDE_CLIENT="$REPO_DIR/hook_client.py"
CODEX_CLIENT="$REPO_DIR/codex_hook_client.py"
USER_HOME="${HOME:?HOME が設定されていません}"
CLAUDE_CONFIG="$USER_HOME/.claude/settings.json"
LEGACY_CLAUDE_CONFIG="$USER_HOME/.claude/settings.local.json"
CODEX_CONFIG="$USER_HOME/.codex/hooks.json"
BACKUP_STAMP="$(date '+%Y%m%d-%H%M%S')-$$"

if [[ ! -x "$HOOK_PYTHON" ]]; then
    echo "エラー: フック用 Python が実行できません: $HOOK_PYTHON" >&2
    echo "先にリポジトリの .venv を準備してください。" >&2
    exit 1
fi
if [[ ! -f "$CLAUDE_CLIENT" || ! -f "$CODEX_CLIENT" ]]; then
    echo "エラー: フッククライアントが見つかりません。" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "エラー: 設定のマージに必要な python3 が見つかりません。" >&2
    exit 1
fi
if [[ -e "$LEGACY_CLAUDE_CONFIG" || -L "$LEGACY_CLAUDE_CONFIG" ]]; then
    echo "警告: 旧設定 $LEGACY_CLAUDE_CONFIG が存在します。" >&2
    echo "      Claude のユーザー全体フックは $CLAUDE_CONFIG に登録します。" >&2
    echo "      旧設定内の claudemicro フックは自動削除しないため、必要に応じて手動で除去してください。" >&2
fi

# 設定ファイルは両方を検証してからバックアップ・更新する。
python3 - "$CLAUDE_CONFIG" "$CODEX_CONFIG" "$HOOK_PYTHON" \
    "$CLAUDE_CLIENT" "$CODEX_CLIENT" "$BACKUP_STAMP" <<'PY'
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import sys
import tempfile


claude_path = Path(sys.argv[1])
codex_path = Path(sys.argv[2])
hook_python = Path(sys.argv[3])
claude_client = Path(sys.argv[4])
codex_client = Path(sys.argv[5])
backup_stamp = sys.argv[6]


def load_config(path: Path) -> dict:
    """既存 JSON を読み、フックを安全にマージできる形か検証する。"""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as source:
            config = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"エラー: {path} を JSON として読めません: {exc}")
    if not isinstance(config, dict):
        raise SystemExit(f"エラー: {path} のルートは JSON オブジェクトである必要があります。")
    hooks = config.get("hooks")
    if hooks is None:
        config.pop("hooks", None)
        return config
    if not isinstance(hooks, dict):
        raise SystemExit(f"エラー: {path} の hooks は JSON オブジェクトである必要があります。")
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
    """現在のリポジトリ内クライアントを呼ぶ command だけを出自付きと判定する。"""
    if not isinstance(command, dict) or command.get("type") != "command":
        return False
    command_text = str(command.get("command", ""))
    try:
        return str(client) in shlex.split(command_text)
    except ValueError:
        # 壊れた shell 引用符があっても、文字列上明らかな場合は出自付きとする。
        return str(client) in command_text


def remove_our_hooks(config: dict, client: Path):
    """既存グループ内の他フックを残し、claudemicro の command だけ外す。"""
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, groups in list(hooks.items()):
        kept_groups = []
        for group in groups:
            commands = group.get("hooks")
            if not isinstance(commands, list):
                kept_groups.append(group)
                continue
            kept_commands = [item for item in commands if not is_our_command(item, client)]
            if len(kept_commands) == len(commands):
                kept_groups.append(group)
            elif kept_commands:
                group["hooks"] = kept_commands
                kept_groups.append(group)
            # 対象 command しかない空グループはイベントからも外す。
        if kept_groups:
            hooks[event] = kept_groups
        elif groups:
            del hooks[event]


def command_hook(command: str, timeout: int) -> dict:
    return {"type": "command", "command": command, "timeout": timeout}


def add_group(config: dict, event: str, command: str, *, matcher=None,
              timeout: int = 10):
    hooks = config.setdefault("hooks", {})
    group = {
        "hooks": [command_hook(command, timeout)],
    }
    if matcher is not None:
        group["matcher"] = matcher
    hooks.setdefault(event, []).append(group)


def make_backup(path: Path):
    """既存ファイルを属性付きで保存する。新規ファイルには復元元がない。"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
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
    else:
        print(f"新規作成: {path}")


def atomic_write(path: Path, config: dict):
    """元のパーミッションを維持しつつ、同一ディレクトリ上で置換する。"""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
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


# 一方が不正なときももう一方を書き換えないよう、先に両方読む。
claude_config = load_config(claude_path)
codex_config = load_config(codex_path)
claude_before = json.loads(json.dumps(claude_config))
codex_before = json.loads(json.dumps(codex_config))

claude_command = shlex.join([str(hook_python), str(claude_client)])
codex_command = shlex.join([str(hook_python), str(codex_client)])

remove_our_hooks(claude_config, claude_client)
remove_our_hooks(codex_config, codex_client)

for event in (
    "SessionStart", "UserPromptSubmit", "Notification", "Stop",
    "StopFailure", "SessionEnd", "PostToolUse",
):
    add_group(claude_config, event, claude_command)
add_group(claude_config, "PreToolUse", claude_command, matcher="*", timeout=300)

# Codex 0.147.0 の通常 hook は async を解釈しない。observe-only クライアント側で
# 通信時間を境界化するため、ここではサポートされる同期 command フィールドだけを使う。
for event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
    add_group(codex_config, event, codex_command)
for event in ("PreToolUse", "PermissionRequest", "PostToolUse"):
    add_group(codex_config, event, codex_command, matcher=".*")

if claude_config != claude_before:
    make_backup(claude_path)
    atomic_write(claude_path, claude_config)
else:
    print(f"変更なし: {claude_path}")
if codex_config != codex_before:
    make_backup(codex_path)
    atomic_write(codex_path, codex_config)
else:
    print(f"変更なし: {codex_path}")
PY

echo
echo "claudemicro フックを登録しました。"
echo "  Claude: $CLAUDE_CONFIG"
echo "    SessionStart / UserPromptSubmit / Notification / Stop / StopFailure / SessionEnd / PostToolUse / PreToolUse"
echo "  Codex:  $CODEX_CONFIG"
echo "    SessionStart / UserPromptSubmit / PreToolUse / PermissionRequest / PostToolUse / Stop / SessionEnd"
echo
echo "Codex の非管理フックは、初回に Codex TUI の /hooks で trust を承認してください。"
echo "削除: $SCRIPT_DIR/uninstall_hooks.sh"
