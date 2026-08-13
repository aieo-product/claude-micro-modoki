#!/usr/bin/env python3
"""Remove only this checkout's Claude Code and Codex hook commands.

This is the cross-platform counterpart of ``uninstall_hooks.sh``.  It is only
run when invoked explicitly; importing it is side-effect free.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

try:  # Direct script execution puts scripts/ itself on sys.path.
    from install_hooks import (
        HookConfigError,
        Printer,
        REPO_DIR,
        SCRIPT_DIR,
        _backup_stamp,
        atomic_write,
        config_paths,
        load_config,
        make_backup,
        remove_our_hooks,
        resolve_config_target,
    )
except ImportError:  # Also support importing this file as scripts.uninstall_hooks.
    from scripts.install_hooks import (
        HookConfigError,
        Printer,
        REPO_DIR,
        SCRIPT_DIR,
        _backup_stamp,
        atomic_write,
        config_paths,
        load_config,
        make_backup,
        remove_our_hooks,
        resolve_config_target,
    )


def _legacy_warning(legacy_path: Path, claude_path: Path, *, printer: Printer) -> None:
    if legacy_path.exists() or legacy_path.is_symlink():
        printer(f"警告: 旧設定 {legacy_path} が存在します。")
        printer(f"      このスクリプトは {claude_path} のみ更新します。")
        printer("      旧設定内の claudemicro フックは必要に応じて手動で除去してください。")


def uninstall(
    *,
    home: Path,
    repo_dir: Path = REPO_DIR,
    dry_run: bool = False,
    backup_stamp: str | None = None,
    printer: Printer = print,
) -> None:
    """Plan and optionally remove current-repository hook commands."""
    home = home.resolve()
    claude_path, legacy_path, codex_path = config_paths(home)
    _legacy_warning(legacy_path, claude_path, printer=printer)
    targets = (
        ("Claude", claude_path, (repo_dir / "hook_client.py").resolve()),
        ("Codex", codex_path, (repo_dir / "codex_hook_client.py").resolve()),
    )

    # Validate every existing input before making any change to either one.
    loaded = []
    for label, path, client in targets:
        if path.exists():
            loaded.append((label, path, client, load_config(path, missing_ok=False)))

    plans = []
    for label, path, client, config in loaded:
        count = remove_our_hooks(config, client)
        plans.append((label, path, config, count))
    stamp = backup_stamp or _backup_stamp()
    write_targets = {
        path: resolve_config_target(path, printer=printer)
        for _label, path, _config, count in plans
        if count
    }

    if dry_run:
        printer("[dry-run] 設定ファイルとバックアップは変更しません。")
        existing = {path for _label, path, _config, _count in plans}
        for label, path, config, count in plans:
            del config  # the count/path are the useful, non-sensitive preview
            printer(f"[dry-run] 削除予定: {label}: {path} ({count} 件)")
            if count:
                target = write_targets[path]
                backup = target.with_name(target.name + f".claudemicro.bak.{stamp}")
                printer(f"[dry-run] バックアップ予定: {backup}")
        for label, path, _client in targets:
            if path not in existing:
                printer(f"[dry-run] 設定ファイルなし: {label}: {path}")
        return

    # Back up every file that will change before writing either one.
    for _label, path, _config, count in plans:
        if count:
            make_backup(write_targets[path], stamp, printer=printer)
    for label, path, config, count in plans:
        if count:
            atomic_write(write_targets[path], config, printer=printer)
        printer(f"削除: {label}: {path} ({count} 件)")

    existing = {path for _label, path, _config, _count in plans}
    for label, path, _client in targets:
        if path not in existing:
            printer(f"設定ファイルなし: {label}: {path}")
    printer("claudemicro 由来のフックだけを削除しました。")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude Code / Codex 設定から claudemicro 由来のフックだけを削除します。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="削除予定だけを表示し、設定・バックアップを一切変更しない",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        uninstall(home=Path.home(), dry_run=args.dry_run)
    except (HookConfigError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
