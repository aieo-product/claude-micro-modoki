#!/usr/bin/env python3
"""Install Claude Code and Codex hooks without replacing unrelated settings.

This is the cross-platform counterpart of ``install_hooks.sh``.  It is only
run when invoked explicitly; importing it is side-effect free.
"""

from __future__ import annotations

import argparse
import copy
import json
import ntpath
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent

CLAUDE_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "Notification",
    "Stop",
    "StopFailure",
    "SessionEnd",
    "PostToolUse",
    # ツールレベルの失敗を error LED に出す (bridge 側ハンドラの活性化, #75)
    "PostToolUseFailure",
)
CODEX_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
CODEX_TOOL_EVENTS = ("PreToolUse", "PermissionRequest", "PostToolUse")

Printer = Callable[[str], None]


class HookConfigError(ValueError):
    """A settings file cannot be merged safely."""


def _backup_stamp() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"


def config_paths(home: Path) -> tuple[Path, Path, Path]:
    """Return Claude, legacy Claude, and Codex user settings paths."""
    return (
        home / ".claude" / "settings.json",
        home / ".claude" / "settings.local.json",
        home / ".codex" / "hooks.json",
    )


def resolve_python(executable: str | os.PathLike[str] | None = None) -> Path:
    """Return the absolute interpreter path that will execute each hook.

    ``sys.executable`` keeps the generated command tied to the environment used
    for installation.  In a Windows project virtualenv this resolves to
    ``.venv\\Scripts\\python.exe``; on POSIX it commonly resolves to
    ``.venv/bin/python``.
    """
    value = os.fspath(executable) if executable is not None else sys.executable
    if not value:
        raise HookConfigError("Python 実行体を特定できません。")
    path = Path(value).expanduser()
    # Keep the virtualenv entry point itself instead of resolving its symlink to
    # the base interpreter.  The generated hook should visibly and predictably
    # use .venv/bin/python or .venv\Scripts\python.exe.
    absolute = path if path.is_absolute() else Path.cwd() / path
    if not absolute.is_file():
        raise HookConfigError(f"Python 実行体が見つかりません: {absolute}")
    return absolute


def build_hook_command(
    python: Path,
    client: Path,
    *,
    platform: str | None = None,
) -> str:
    """Quote an absolute interpreter/client command for the current OS shell."""
    target_platform = platform or sys.platform
    if target_platform == "win32":
        def windows_absolute(path: Path) -> str:
            value = os.fspath(path)
            # ntpath also lets the Windows quoting branch be regression-tested
            # from macOS without turning C:\... into a POSIX cwd-relative path.
            return ntpath.normpath(value if ntpath.isabs(value) else ntpath.abspath(value))

        argv = [windows_absolute(python), windows_absolute(client)]
        # list2cmdline implements Windows' CommandLineToArgvW-compatible quoting,
        # including spaces and trailing backslashes in absolute paths.
        return subprocess.list2cmdline(argv)
    argv = [str(python.absolute()), str(client.absolute())]
    return shlex.join(argv)


def load_config(path: Path, *, missing_ok: bool = True) -> dict:
    """Load and validate the part of a settings object that we need to edit."""
    if missing_ok and not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as source:
            config = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HookConfigError(f"{path} を JSON として読めません: {exc}") from exc
    if not isinstance(config, dict):
        raise HookConfigError(f"{path} のルートは JSON オブジェクトである必要があります。")
    hooks = config.get("hooks")
    if hooks is None:
        config.pop("hooks", None)
        return config
    if not isinstance(hooks, dict):
        raise HookConfigError(f"{path} の hooks は JSON オブジェクトである必要があります。")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise HookConfigError(f"{path} の hooks.{event} は配列である必要があります。")
        for group in groups:
            if not isinstance(group, dict):
                raise HookConfigError(f"{path} の hooks.{event} に不正なグループがあります。")
            commands = group.get("hooks")
            if commands is not None and not isinstance(commands, list):
                raise HookConfigError(
                    f"{path} の hooks.{event}[].hooks は配列である必要があります。"
                )
    return config


def _normalise_path_token(token: str, *, windows: bool) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1]
    if windows:
        return ntpath.normcase(ntpath.normpath(token))
    return token


def is_our_command(command: object, client: Path) -> bool:
    """Identify only command hooks that invoke this checkout's client path."""
    if not isinstance(command, dict) or command.get("type") != "command":
        return False
    command_text = str(command.get("command", ""))
    client_text = str(client)
    windows = sys.platform == "win32" or (
        len(client_text) >= 3 and client_text[1:3] in (":\\", ":/")
    )
    expected = _normalise_path_token(client_text, windows=windows)
    parse_failed = False
    for posix in (not windows, windows):
        try:
            tokens = shlex.split(command_text, posix=posix)
        except ValueError:
            parse_failed = True
            continue
        if any(_normalise_path_token(token, windows=windows) == expected for token in tokens):
            return True
    # Match the shell installers' tolerant fallback for an already malformed
    # command, while avoiding substring matches for valid commands.
    if parse_failed:
        text = command_text.replace("\\", "/")
        needle = client_text.replace("\\", "/")
        if windows:
            text, needle = text.casefold(), needle.casefold()
        return needle in text
    return False


def remove_our_hooks(config: dict, client: Path) -> int:
    """Remove our commands while preserving unrelated commands and groups."""
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


def command_hook(command: str, timeout: int) -> dict:
    return {"type": "command", "command": command, "timeout": timeout}


def add_group(
    config: dict,
    event: str,
    command: str,
    *,
    matcher: str | None = None,
    timeout: int = 10,
) -> None:
    hooks = config.setdefault("hooks", {})
    group = {"hooks": [command_hook(command, timeout)]}
    if matcher is not None:
        group["matcher"] = matcher
    hooks.setdefault(event, []).append(group)


def merged_configs(
    claude_config: dict,
    codex_config: dict,
    *,
    python: Path,
    repo_dir: Path = REPO_DIR,
) -> tuple[dict, dict, str, str]:
    """Return settings with exactly one current claudemicro group per event."""
    claude_client = (repo_dir / "hook_client.py").resolve(strict=True)
    codex_client = (repo_dir / "codex_hook_client.py").resolve(strict=True)
    claude_command = build_hook_command(python, claude_client)
    codex_command = build_hook_command(python, codex_client)

    claude_result = copy.deepcopy(claude_config)
    codex_result = copy.deepcopy(codex_config)
    remove_our_hooks(claude_result, claude_client)
    remove_our_hooks(codex_result, codex_client)

    for event in CLAUDE_EVENTS:
        add_group(claude_result, event, claude_command)
    add_group(claude_result, "PreToolUse", claude_command, matcher="*", timeout=300)

    # Codex's normal hook schema uses synchronous command fields.  The
    # observe-only client bounds its own bridge timeout.
    for event in CODEX_EVENTS:
        add_group(codex_result, event, codex_command)
    for event in CODEX_TOOL_EVENTS:
        add_group(codex_result, event, codex_command, matcher=".*")

    return claude_result, codex_result, claude_command, codex_command


def resolve_config_target(path: Path, *, printer: Printer = print) -> Path:
    """Return the file to replace, preserving a configured symbolic link."""
    if not path.is_symlink():
        return path
    target = path.resolve()
    printer(f"警告: {path} はシンボリックリンクです。リンク先 {target} を対象にします。")
    return target


def make_backup(path: Path, backup_stamp: str, *, printer: Printer = print) -> Path:
    """Copy an existing settings file to a timestamped sibling atomically."""
    path = resolve_config_target(path, printer=printer)
    backup = path.with_name(path.name + f".claudemicro.bak.{backup_stamp}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{backup.name}.", dir=path.parent)
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
    printer(f"バックアップ: {backup}")
    return backup


def atomic_write(path: Path, config: dict, *, printer: Printer = print) -> None:
    """Replace JSON in its own directory while retaining existing permissions."""
    path = resolve_config_target(path, printer=printer)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(config, target, ensure_ascii=False, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        if not hasattr(os, "fchmod"):
            os.chmod(temporary_name, mode)
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


def _legacy_warning(legacy_path: Path, claude_path: Path, *, printer: Printer) -> None:
    if legacy_path.exists() or legacy_path.is_symlink():
        printer(f"警告: 旧設定 {legacy_path} が存在します。")
        printer(f"      Claude のユーザー全体フックは {claude_path} に登録します。")
        printer("      旧設定内の claudemicro フックは自動削除しません。")


def install(
    *,
    home: Path,
    executable: str | os.PathLike[str] | None = None,
    repo_dir: Path = REPO_DIR,
    dry_run: bool = False,
    backup_stamp: str | None = None,
    printer: Printer = print,
) -> None:
    """Plan and optionally apply both hook configuration updates."""
    home = home.resolve()
    python = resolve_python(executable)
    claude_path, legacy_path, codex_path = config_paths(home)
    _legacy_warning(legacy_path, claude_path, printer=printer)

    # Validate both inputs before creating directories, backups, or writes.
    claude_before = load_config(claude_path)
    codex_before = load_config(codex_path)
    claude_after, codex_after, claude_command, codex_command = merged_configs(
        claude_before,
        codex_before,
        python=python,
        repo_dir=repo_dir,
    )
    plans = (
        ("Claude", claude_path, claude_before, claude_after),
        ("Codex", codex_path, codex_before, codex_after),
    )
    stamp = backup_stamp or _backup_stamp()
    write_targets = {
        path: resolve_config_target(path, printer=printer)
        for _label, path, before, after in plans
        if before != after
    }

    if dry_run:
        printer("[dry-run] 設定ファイル、ディレクトリ、バックアップは変更しません。")
        printer(f"[dry-run] Python: {python}")
        printer(f"[dry-run] Claude command: {claude_command}")
        printer(f"[dry-run] Claude events: {' / '.join(CLAUDE_EVENTS + ('PreToolUse',))}")
        printer(f"[dry-run] Codex command: {codex_command}")
        printer(
            f"[dry-run] Codex events: "
            f"{' / '.join(CODEX_EVENTS + CODEX_TOOL_EVENTS)}"
        )
        for label, path, before, after in plans:
            if before == after:
                printer(f"[dry-run] 変更なし: {label}: {path}")
            elif path.exists():
                target = write_targets[path]
                backup = target.with_name(target.name + f".claudemicro.bak.{stamp}")
                printer(f"[dry-run] 更新予定: {label}: {path}")
                printer(f"[dry-run] バックアップ予定: {backup}")
            else:
                printer(f"[dry-run] 新規作成予定: {label}: {path}")
        return

    changed = [plan for plan in plans if plan[2] != plan[3]]
    for _label, path, _before, _after in changed:
        write_targets[path].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Create every required backup before writing either configuration.
    for _label, path, _before, _after in changed:
        target = write_targets[path]
        if target.exists():
            make_backup(target, stamp, printer=printer)
        else:
            printer(f"新規作成: {path}")
    for label, path, before, after in plans:
        if before == after:
            printer(f"変更なし: {path}")
        else:
            atomic_write(write_targets[path], after, printer=printer)
            printer(f"更新: {label}: {path}")

    printer("")
    printer("claudemicro フックを登録しました。")
    printer(f"  Claude: {claude_path}")
    printer("    " + " / ".join(CLAUDE_EVENTS + ("PreToolUse",)))
    printer(f"  Codex:  {codex_path}")
    printer("    " + " / ".join(CODEX_EVENTS + CODEX_TOOL_EVENTS))
    printer("")
    printer("Codex の非管理フックは、初回に Codex TUI の /hooks で trust を承認してください。")
    printer(f"削除: {SCRIPT_DIR / 'uninstall_hooks.py'}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude Code / Codex のユーザー設定に claudemicro フックを登録します。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="変更予定だけを表示し、設定・バックアップを一切変更しない",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        install(home=Path.home(), dry_run=args.dry_run)
    except (HookConfigError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
