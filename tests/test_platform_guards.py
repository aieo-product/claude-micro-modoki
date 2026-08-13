"""Windows compatibility guards that can be exercised without hardware."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import codex_hook_client
import hook_client
from server import config as config_mod

# Avoid loading a developer-specific config while server.main creates its global Bridge.
with mock.patch.object(
        config_mod, "load",
        return_value=config_mod._deep_merge(config_mod.DEFAULT_CONFIG, {})):
    from server import main as server_main


_FRONTMOST_APP_SCRIPT = (
    'tell application "System Events" to name of first application process '
    'whose frontmost is true'
)


class FrontmostAppPlatformTests(unittest.IsolatedAsyncioTestCase):
    async def test_win32_returns_none_without_spawning_osascript(self):
        spawn = mock.AsyncMock(
            side_effect=AssertionError("non-Darwin must not spawn osascript"))

        with mock.patch.object(server_main.sys, "platform", "win32"), \
                mock.patch.object(
                    server_main.asyncio, "create_subprocess_exec", spawn):
            result = await server_main._frontmost_app()

        self.assertIsNone(result)
        spawn.assert_not_awaited()

    async def test_darwin_keeps_the_existing_osascript_contract(self):
        process = mock.Mock()
        process.communicate = mock.AsyncMock(
            return_value=(b"ChatGPT\n", None))
        spawn = mock.AsyncMock(return_value=process)

        with mock.patch.object(server_main.sys, "platform", "darwin"), \
                mock.patch.object(
                    server_main.asyncio, "create_subprocess_exec", spawn):
            result = await server_main._frontmost_app()

        self.assertEqual(result, "ChatGPT")
        spawn.assert_awaited_once_with(
            "osascript", "-e", _FRONTMOST_APP_SCRIPT,
            stdout=server_main.asyncio.subprocess.PIPE,
            stderr=server_main.asyncio.subprocess.DEVNULL,
        )
        process.communicate.assert_awaited_once_with()


class FocusSessionPlatformTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _bridge(mode: str):
        bridge = server_main.Bridge.__new__(server_main.Bridge)
        bridge.mode = mode
        bridge.cfg = {
            "cmux_cli": "/opt/cmux/bin/cmux",
            "mode": {"codex_app": "ChatGPT"},
        }
        bridge._run = mock.AsyncMock()
        return bridge

    async def test_win32_app_focus_is_a_noop(self):
        bridge = self._bridge("claude-app")

        with mock.patch.object(server_main.sys, "platform", "win32"):
            await bridge._focus_session({})

        bridge._run.assert_not_awaited()

    async def test_darwin_keeps_the_existing_open_contract(self):
        bridge = self._bridge("codex-app")

        with mock.patch.object(server_main.sys, "platform", "darwin"):
            await bridge._focus_session({})

        bridge._run.assert_awaited_once_with("open", "-a", "ChatGPT")

    async def test_win32_cmux_focus_remains_available(self):
        bridge = self._bridge("cmux-claude")

        with mock.patch.object(server_main.sys, "platform", "win32"):
            await bridge._focus_session({"cmux_workspace_id": "workspace:42"})

        self.assertEqual(
            bridge._run.await_args_list,
            [
                mock.call(
                    "/opt/cmux/bin/cmux",
                    "workspace-action",
                    "--action",
                    "select",
                    "--workspace",
                    "workspace:42",
                ),
                mock.call(
                    "/opt/cmux/bin/cmux",
                    "focus-window",
                    "--window",
                    "window:1",
                ),
            ],
        )


class DevicePlatformTests(unittest.TestCase):
    def test_win32_import_does_not_load_the_darwin_hid_symbol(self):
        """Import device.py in a child so fake platform/modules cannot leak."""
        repository = Path(__file__).resolve().parents[1]
        program = textwrap.dedent(
            """
            import ctypes
            import itertools
            import json
            import sys
            import threading
            import time
            import types

            sys.path.insert(0, sys.argv[1])
            fake_hid = types.ModuleType("hid")
            fake_hid.__file__ = "sentinel-hid-library"
            sys.modules["hid"] = fake_hid

            def forbidden_cdll(*args, **kwargs):
                raise AssertionError(
                    "ctypes.CDLL was called for HID on simulated win32")

            ctypes.CDLL = forbidden_cdll
            sys.platform = "win32"

            from server import device

            assert device.hid is fake_hid
            print("guarded")
            """
        )

        with tempfile.TemporaryDirectory() as fake_home:
            environment = os.environ.copy()
            environment.update({
                "HOME": fake_home,
                "USERPROFILE": fake_home,
                "CLAUDEMICRO_NO_DEVICE": "1",
                "PYTHONNOUSERSITE": "1",
            })
            environment.pop("PYTHONPATH", None)
            completed = subprocess.run(
                [sys.executable, "-I", "-c", program, str(repository)],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(
            completed.returncode, 0,
            f"child stderr:\n{completed.stderr}\nchild stdout:\n{completed.stdout}",
        )
        self.assertEqual(completed.stdout.strip(), "guarded")


class HookLogPlatformTests(unittest.TestCase):
    def test_clients_append_without_fcntl(self):
        clients = (
            (hook_client, "claudecode.log"),
            (codex_hook_client, "codexhook.log"),
        )

        with tempfile.TemporaryDirectory() as directory:
            for client, filename in clients:
                with self.subTest(client=client.__name__):
                    path = os.path.join(directory, filename)
                    with open(path, "w", encoding="utf-8") as log_file:
                        log_file.write("existing\n")

                    with mock.patch.object(client, "LOG", path), \
                            mock.patch.object(client, "fcntl", None):
                        client.log("windows fallback")

                    with open(path, encoding="utf-8") as log_file:
                        self.assertEqual(
                            log_file.read(),
                            "existing\nwindows fallback\n",
                        )


if __name__ == "__main__":
    unittest.main()
