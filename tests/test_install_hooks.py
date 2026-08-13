"""Focused tests for the cross-platform hook installers."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts import install_hooks, uninstall_hooks  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _tree_snapshot(root: Path) -> dict[str, tuple[str, object]]:
    """Capture names and contents, including directories and symbolic links."""
    result: dict[str, tuple[str, object]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path))
        elif path.is_dir():
            result[relative] = ("directory", None)
        else:
            result[relative] = ("file", path.read_bytes())
    return result


def _event_commands(config: dict, event: str) -> list[object]:
    commands: list[object] = []
    for group in config.get("hooks", {}).get(event, []):
        commands.extend(group.get("hooks", []))
    return commands


def _owned_count(config: dict, event: str, client: Path) -> int:
    return sum(
        install_hooks.is_our_command(command, client)
        for command in _event_commands(config, event)
    )


class HookInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.python = install_hooks.resolve_python(sys.executable)
        self.claude_client = (REPO_DIR / "hook_client.py").resolve(strict=True)
        self.codex_client = (REPO_DIR / "codex_hook_client.py").resolve(strict=True)

    def test_install_dry_run_changes_nothing_and_prints_complete_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            claude_path, _legacy_path, codex_path = install_hooks.config_paths(home)
            _write_json(claude_path, {"theme": "dark"})
            (home / "sentinel.txt").write_text("leave me alone\n", encoding="utf-8")
            before = _tree_snapshot(home)
            output: list[str] = []

            install_hooks.install(
                home=home,
                executable=self.python,
                repo_dir=REPO_DIR,
                dry_run=True,
                backup_stamp="20260813-010203-456",
                printer=output.append,
            )

            self.assertEqual(_tree_snapshot(home), before)
            self.assertFalse((home / ".codex").exists())
            text = "\n".join(output)
            claude_command = install_hooks.build_hook_command(
                self.python, self.claude_client
            )
            codex_command = install_hooks.build_hook_command(
                self.python, self.codex_client
            )
            self.assertIn(f"Claude command: {claude_command}", text)
            self.assertIn(f"Codex command: {codex_command}", text)
            self.assertIn(str(self.claude_client), claude_command)
            self.assertIn(str(self.codex_client), codex_command)
            self.assertTrue(self.claude_client.is_absolute())
            self.assertTrue(self.codex_client.is_absolute())
            self.assertIn(str(claude_path.resolve()), text)
            self.assertIn(str(codex_path.resolve()), text)
            for event in install_hooks.CLAUDE_EVENTS + ("PreToolUse",):
                self.assertIn(event, text)
            for event in install_hooks.CODEX_EVENTS + install_hooks.CODEX_TOOL_EVENTS:
                self.assertIn(event, text)

    def test_merge_preserves_unrelated_keys_groups_and_commands(self) -> None:
        claude_command = install_hooks.build_hook_command(
            self.python, self.claude_client
        )
        codex_command = install_hooks.build_hook_command(
            self.python, self.codex_client
        )
        claude_foreign = {
            "type": "command",
            "command": "python /opt/acme/claude-hook.py",
            "timeout": 91,
            "tag": "foreign",
        }
        claude_prompt = {"type": "prompt", "prompt": "preserve this prompt"}
        claude_mixed = {
            "matcher": "Bash",
            "label": "mixed group",
            "hooks": [
                install_hooks.command_hook(claude_command, 1),
                claude_foreign,
                claude_prompt,
            ],
        }
        claude_group = {
            "matcher": "Read",
            "hooks": [{"type": "command", "command": "notify-read"}],
        }
        claude_custom_event = [
            {"label": "custom", "hooks": [{"type": "http", "url": "https://example.test"}]}
        ]
        claude_before = {
            "$schema": "https://example.test/claude-schema.json",
            "permissions": {"allow": ["Read"]},
            "hooks": {
                "SessionStart": [claude_mixed, claude_group],
                "AcmeEvent": claude_custom_event,
            },
        }

        codex_foreign = {
            "type": "command",
            "command": "python /opt/acme/codex-hook.py",
            "timeout": 7,
        }
        codex_mixed = {
            "matcher": "shell",
            "extra": {"preserve": True},
            "hooks": [
                codex_foreign,
                install_hooks.command_hook(codex_command, 3),
            ],
        }
        codex_custom_event = [
            {"hooks": [{"type": "command", "command": "audit-event"}]}
        ]
        codex_before = {
            "notice": "keep",
            "features": {"hooks": True},
            "hooks": {
                "PreToolUse": [codex_mixed],
                "AcmeEvent": codex_custom_event,
            },
        }
        original_claude = copy.deepcopy(claude_before)
        original_codex = copy.deepcopy(codex_before)

        claude_after, codex_after, actual_claude_command, actual_codex_command = (
            install_hooks.merged_configs(
                claude_before,
                codex_before,
                python=self.python,
                repo_dir=REPO_DIR,
            )
        )

        self.assertEqual(claude_before, original_claude)
        self.assertEqual(codex_before, original_codex)
        self.assertEqual(actual_claude_command, claude_command)
        self.assertEqual(actual_codex_command, codex_command)
        self.assertEqual(claude_after["$schema"], claude_before["$schema"])
        self.assertEqual(claude_after["permissions"], claude_before["permissions"])
        self.assertEqual(codex_after["notice"], codex_before["notice"])
        self.assertEqual(codex_after["features"], codex_before["features"])
        self.assertEqual(claude_after["hooks"]["AcmeEvent"], claude_custom_event)
        self.assertEqual(codex_after["hooks"]["AcmeEvent"], codex_custom_event)

        expected_claude_mixed = copy.deepcopy(claude_mixed)
        expected_claude_mixed["hooks"] = [claude_foreign, claude_prompt]
        self.assertEqual(
            claude_after["hooks"]["SessionStart"][:2],
            [expected_claude_mixed, claude_group],
        )
        expected_codex_mixed = copy.deepcopy(codex_mixed)
        expected_codex_mixed["hooks"] = [codex_foreign]
        self.assertEqual(codex_after["hooks"]["PreToolUse"][0], expected_codex_mixed)

        for event in install_hooks.CLAUDE_EVENTS + ("PreToolUse",):
            with self.subTest(client="Claude", event=event):
                self.assertEqual(_owned_count(claude_after, event, self.claude_client), 1)
        for event in install_hooks.CODEX_EVENTS + install_hooks.CODEX_TOOL_EVENTS:
            with self.subTest(client="Codex", event=event):
                self.assertEqual(_owned_count(codex_after, event, self.codex_client), 1)

    def test_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            first_output: list[str] = []
            install_hooks.install(
                home=home,
                executable=self.python,
                repo_dir=REPO_DIR,
                backup_stamp="20260813-020304-100",
                printer=first_output.append,
            )
            claude_path, _legacy_path, codex_path = install_hooks.config_paths(home)
            first_contents = {
                claude_path: claude_path.read_bytes(),
                codex_path: codex_path.read_bytes(),
            }

            second_output: list[str] = []
            install_hooks.install(
                home=home,
                executable=self.python,
                repo_dir=REPO_DIR,
                backup_stamp="20260813-020305-101",
                printer=second_output.append,
            )

            self.assertEqual(claude_path.read_bytes(), first_contents[claude_path])
            self.assertEqual(codex_path.read_bytes(), first_contents[codex_path])
            self.assertEqual(list(home.rglob("*.claudemicro.bak.*")), [])
            self.assertEqual("\n".join(second_output).count("変更なし:"), 2)
            claude = _read_json(claude_path)
            codex = _read_json(codex_path)
            for event in install_hooks.CLAUDE_EVENTS + ("PreToolUse",):
                self.assertEqual(_owned_count(claude, event, self.claude_client), 1)
            for event in install_hooks.CODEX_EVENTS + install_hooks.CODEX_TOOL_EVENTS:
                self.assertEqual(_owned_count(codex, event, self.codex_client), 1)

    def test_install_backs_up_each_existing_config_with_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            claude_path, _legacy_path, codex_path = install_hooks.config_paths(home)
            claude_original = b'{"theme":"solarized","hooks":{}}\n'
            codex_original = b'{"notice":"existing","hooks":{}}\n'
            claude_path.parent.mkdir(parents=True)
            codex_path.parent.mkdir(parents=True)
            claude_path.write_bytes(claude_original)
            codex_path.write_bytes(codex_original)
            stamp = "20260813-030405-789"
            output: list[str] = []

            install_hooks.install(
                home=home,
                executable=self.python,
                repo_dir=REPO_DIR,
                backup_stamp=stamp,
                printer=output.append,
            )

            claude_backup = claude_path.with_name(
                f"{claude_path.name}.claudemicro.bak.{stamp}"
            )
            codex_backup = codex_path.with_name(
                f"{codex_path.name}.claudemicro.bak.{stamp}"
            )
            self.assertEqual(claude_backup.read_bytes(), claude_original)
            self.assertEqual(codex_backup.read_bytes(), codex_original)
            self.assertNotEqual(claude_path.read_bytes(), claude_original)
            self.assertNotEqual(codex_path.read_bytes(), codex_original)
            self.assertIn(str(claude_backup), "\n".join(output))
            self.assertIn(str(codex_backup), "\n".join(output))

    def test_install_preserves_symlink_and_backs_up_resolved_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            claude_path, _legacy_path, _codex_path = install_hooks.config_paths(home)
            claude_path.parent.mkdir(parents=True)
            managed_target = root / "dotfiles" / "claude-settings.json"
            managed_target.parent.mkdir()
            original = b'{"theme":"managed"}\n'
            managed_target.write_bytes(original)
            link_value = os.path.relpath(managed_target, claude_path.parent)
            try:
                claude_path.symlink_to(link_value)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symbolic links are unavailable: {exc}")
            stamp = "20260813-031415-926"
            output: list[str] = []

            install_hooks.install(
                home=home,
                executable=self.python,
                repo_dir=REPO_DIR,
                backup_stamp=stamp,
                printer=output.append,
            )

            target_backup = managed_target.with_name(
                f"{managed_target.name}.claudemicro.bak.{stamp}"
            )
            link_backup = claude_path.with_name(
                f"{claude_path.name}.claudemicro.bak.{stamp}"
            )
            self.assertTrue(claude_path.is_symlink())
            self.assertEqual(os.readlink(claude_path), link_value)
            self.assertEqual(target_backup.read_bytes(), original)
            self.assertFalse(link_backup.exists())
            claude_config = _read_json(managed_target)
            self.assertEqual(claude_config["theme"], "managed")
            self.assertEqual(
                _owned_count(claude_config, "SessionStart", self.claude_client),
                1,
            )
            warnings = [line for line in output if line.startswith("警告:")]
            self.assertEqual(len(warnings), 1)
            self.assertIn(str(claude_path), warnings[0])
            self.assertIn(str(managed_target), warnings[0])

    def test_uninstall_removes_only_current_repo_commands(self) -> None:
        claude_command = install_hooks.build_hook_command(
            self.python, self.claude_client
        )
        codex_command = install_hooks.build_hook_command(
            self.python, self.codex_client
        )
        other_claude_client = REPO_DIR.parent / f"{REPO_DIR.name}-copy" / "hook_client.py"
        other_codex_client = (
            REPO_DIR.parent / f"{REPO_DIR.name}-copy" / "codex_hook_client.py"
        )
        other_claude = install_hooks.command_hook(
            install_hooks.build_hook_command(self.python, other_claude_client), 20
        )
        other_codex = install_hooks.command_hook(
            install_hooks.build_hook_command(self.python, other_codex_client), 21
        )
        claude_http = {"type": "http", "url": "https://example.test/claude"}
        codex_prompt = {"type": "prompt", "prompt": "keep codex prompt"}

        claude_config = {
            "theme": "dark",
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "mixed",
                        "label": "preserve",
                        "hooks": [
                            install_hooks.command_hook(claude_command, 10),
                            other_claude,
                            claude_http,
                        ],
                    },
                    {"matcher": "foreign", "hooks": [other_claude]},
                ],
                "Stop": [{"hooks": [install_hooks.command_hook(claude_command, 10)]}],
                "AcmeEvent": [{"hooks": [{"type": "command", "command": "acme"}]}],
            },
        }
        expected_claude = copy.deepcopy(claude_config)
        expected_claude["hooks"]["SessionStart"][0]["hooks"] = [
            other_claude,
            claude_http,
        ]
        del expected_claude["hooks"]["Stop"]

        codex_config = {
            "notice": "keep",
            "hooks": {
                "SessionStart": [{"hooks": [install_hooks.command_hook(codex_command, 10)]}],
                "PreToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [other_codex, install_hooks.command_hook(codex_command, 10), codex_prompt],
                    }
                ],
                "AcmeEvent": [{"hooks": [other_codex]}],
            },
        }
        expected_codex = copy.deepcopy(codex_config)
        del expected_codex["hooks"]["SessionStart"]
        expected_codex["hooks"]["PreToolUse"][0]["hooks"] = [
            other_codex,
            codex_prompt,
        ]

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            claude_path, _legacy_path, codex_path = install_hooks.config_paths(home)
            _write_json(claude_path, claude_config)
            _write_json(codex_path, codex_config)
            output: list[str] = []

            uninstall_hooks.uninstall(
                home=home,
                repo_dir=REPO_DIR,
                backup_stamp="20260813-040506-222",
                printer=output.append,
            )

            self.assertEqual(_read_json(claude_path), expected_claude)
            self.assertEqual(_read_json(codex_path), expected_codex)
            self.assertIn("Claude", "\n".join(output))
            self.assertIn("Codex", "\n".join(output))
            self.assertIn("(2 件)", "\n".join(output))
            for event in expected_claude["hooks"]:
                self.assertEqual(_owned_count(expected_claude, event, self.claude_client), 0)
            for event in expected_codex["hooks"]:
                self.assertEqual(_owned_count(expected_codex, event, self.codex_client), 0)

    def test_uninstall_preserves_symlink_and_backs_up_resolved_target(self) -> None:
        claude_command = install_hooks.build_hook_command(
            self.python, self.claude_client
        )
        config = {
            "theme": "managed",
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            install_hooks.command_hook(claude_command, 10)
                        ]
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            claude_path, _legacy_path, _codex_path = install_hooks.config_paths(home)
            claude_path.parent.mkdir(parents=True)
            managed_target = root / "dotfiles" / "claude-settings.json"
            _write_json(managed_target, config)
            original = managed_target.read_bytes()
            link_value = os.path.relpath(managed_target, claude_path.parent)
            try:
                claude_path.symlink_to(link_value)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symbolic links are unavailable: {exc}")
            stamp = "20260813-041516-271"
            output: list[str] = []

            uninstall_hooks.uninstall(
                home=home,
                repo_dir=REPO_DIR,
                backup_stamp=stamp,
                printer=output.append,
            )

            target_backup = managed_target.with_name(
                f"{managed_target.name}.claudemicro.bak.{stamp}"
            )
            link_backup = claude_path.with_name(
                f"{claude_path.name}.claudemicro.bak.{stamp}"
            )
            self.assertTrue(claude_path.is_symlink())
            self.assertEqual(os.readlink(claude_path), link_value)
            self.assertEqual(target_backup.read_bytes(), original)
            self.assertFalse(link_backup.exists())
            self.assertEqual(_read_json(managed_target), {"theme": "managed"})
            warnings = [line for line in output if line.startswith("警告:")]
            self.assertEqual(len(warnings), 1)
            self.assertIn(str(claude_path), warnings[0])
            self.assertIn(str(managed_target), warnings[0])

    def test_uninstall_dry_run_changes_nothing(self) -> None:
        claude_command = install_hooks.build_hook_command(
            self.python, self.claude_client
        )
        codex_command = install_hooks.build_hook_command(
            self.python, self.codex_client
        )
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            claude_path, legacy_path, codex_path = install_hooks.config_paths(home)
            _write_json(
                claude_path,
                {"hooks": {"Stop": [{"hooks": [install_hooks.command_hook(claude_command, 10)]}]}},
            )
            _write_json(
                codex_path,
                {"hooks": {"Stop": [{"hooks": [install_hooks.command_hook(codex_command, 10)]}]}},
            )
            _write_json(legacy_path, {"legacy": "must remain"})
            before = _tree_snapshot(home)
            output: list[str] = []

            uninstall_hooks.uninstall(
                home=home,
                repo_dir=REPO_DIR,
                dry_run=True,
                backup_stamp="20260813-050607-333",
                printer=output.append,
            )

            self.assertEqual(_tree_snapshot(home), before)
            text = "\n".join(output)
            self.assertIn(str(claude_path.resolve()), text)
            self.assertIn(str(codex_path.resolve()), text)
            self.assertIn("(1 件)", text)
            self.assertIn("settings.json.claudemicro.bak.20260813-050607-333", text)
            self.assertIn("hooks.json.claudemicro.bak.20260813-050607-333", text)

    def test_windows_command_quoting_uses_absolute_paths(self) -> None:
        python = Path(r"C:\Program Files\ClaudeMicro\python.exe")
        client = Path(r"C:\Users\Jane Doe\claude micro\hook_client.py")

        command = install_hooks.build_hook_command(
            python,
            client,
            platform="win32",
        )

        expected = subprocess.list2cmdline([str(python), str(client)])
        self.assertEqual(command, expected)
        self.assertIn(f'"{python}"', command)
        self.assertIn(f'"{client}"', command)

    def test_windows_path_ownership_is_case_insensitive_and_token_exact(self) -> None:
        client = Path(r"C:\Users\Jane Doe\Repo\hook_client.py")
        same_client = r"c:/users/JANE DOE/repo/HOOK_CLIENT.PY"
        owned_command = {
            "type": "command",
            "command": subprocess.list2cmdline(
                [r"C:\Program Files\Python\python.exe", same_client]
            ),
        }
        neighboring_checkout = {
            "type": "command",
            "command": subprocess.list2cmdline(
                [
                    r"C:\Program Files\Python\python.exe",
                    r"C:\Users\Jane Doe\Repo-copy\hook_client.py",
                ]
            ),
        }
        suffix_only = {
            "type": "command",
            "command": subprocess.list2cmdline(
                [r"C:\Python\python.exe", str(client) + ".backup"]
            ),
        }

        self.assertTrue(install_hooks.is_our_command(owned_command, client))
        self.assertFalse(install_hooks.is_our_command(neighboring_checkout, client))
        self.assertFalse(install_hooks.is_our_command(suffix_only, client))
        config = {
            "hooks": {
                "Stop": [
                    {"hooks": [owned_command, neighboring_checkout, suffix_only]}
                ]
            }
        }
        self.assertEqual(install_hooks.remove_our_hooks(config, client), 1)
        self.assertEqual(
            config["hooks"]["Stop"][0]["hooks"],
            [neighboring_checkout, suffix_only],
        )


if __name__ == "__main__":
    unittest.main()
