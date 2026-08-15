"""scripts/install_service.sh の plist 生成 (#73) のテスト。

--dry-run はファイルも launchd も変更せず plist を標準出力へ出すだけなので、
インストール環境に触れずに生成内容を検証できる。
"""

import os
import plistlib
import subprocess
import unittest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_DIR, "scripts", "install_service.sh")


class InstallServicePlistTests(unittest.TestCase):
    def _dry_run(self, extra_env=None):
        env = {
            key: value for key, value in os.environ.items()
            if key not in ("APPROVAL_BRIDGE_TOKEN", "CLAUDEMICRO_PORT")
        }
        env.update(extra_env or {})
        return subprocess.run(
            ["bash", SCRIPT, "--dry-run"],
            capture_output=True, text=True, env=env, timeout=30)

    def test_default_has_no_environment_variables(self):
        """環境変数なしなら従来どおり EnvironmentVariables を書かない。"""
        proc = self._dry_run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = plistlib.loads(proc.stdout.encode("utf-8"))
        self.assertNotIn("EnvironmentVariables", data)
        self.assertEqual(data["Label"], "com.claudemicro.bridge")
        self.assertEqual(data["ProgramArguments"][1:], ["-m", "server.main"])

    def test_token_and_port_are_embedded_and_escaped(self):
        """トークン (XML 特殊文字含む) とポートが plist へ正しく入る。"""
        token = 'se&c<r>et"tok'
        proc = self._dry_run(
            {"APPROVAL_BRIDGE_TOKEN": token, "CLAUDEMICRO_PORT": "45710"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = plistlib.loads(proc.stdout.encode("utf-8"))
        env_vars = data["EnvironmentVariables"]
        self.assertEqual(env_vars["APPROVAL_BRIDGE_TOKEN"], token)
        self.assertEqual(env_vars["CLAUDEMICRO_PORT"], "45710")

    def test_token_only_omits_port_key(self):
        """トークンだけ指定した場合、CLAUDEMICRO_PORT キーは書かれない。"""
        proc = self._dry_run({"APPROVAL_BRIDGE_TOKEN": "secret"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = plistlib.loads(proc.stdout.encode("utf-8"))
        env_vars = data["EnvironmentVariables"]
        self.assertEqual(env_vars["APPROVAL_BRIDGE_TOKEN"], "secret")
        self.assertNotIn("CLAUDEMICRO_PORT", env_vars)

    def test_port_only_omits_token_key(self):
        """ポートだけ指定した場合、トークンのキーは書かれない。"""
        proc = self._dry_run({"CLAUDEMICRO_PORT": "45710"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = plistlib.loads(proc.stdout.encode("utf-8"))
        env_vars = data["EnvironmentVariables"]
        self.assertEqual(env_vars["CLAUDEMICRO_PORT"], "45710")
        self.assertNotIn("APPROVAL_BRIDGE_TOKEN", env_vars)

    def test_invalid_port_is_rejected(self):
        """不正ポートは plist を出さず exit 2 (常駐だけ別ポートになる事故を防ぐ)。"""
        for bad in ("abc", "0", "65536", "-1", "1 2"):
            with self.subTest(bad=bad):
                proc = self._dry_run({"CLAUDEMICRO_PORT": bad})
                self.assertEqual(proc.returncode, 2, proc.stdout)
                self.assertIn("CLAUDEMICRO_PORT", proc.stderr)
