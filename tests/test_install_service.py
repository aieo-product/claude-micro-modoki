"""scripts/install_service.sh の plist 生成・権限 (#73) のテスト。

--dry-run はファイルも launchd も変更せず plist を標準出力へ出す (トークンは伏字)。
実インストール経路は fake launchctl/nc + 一時 HOME で外部影響なしに実行し、
実トークンの埋め込み・XML エスケープとファイル権限 (0600/0644) を検証する。
"""

import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
SCRIPT = REPO_DIR / "scripts" / "install_service.sh"
# macOS 同梱 /bin/bash (3.2) での動作を担保する
BASH = "/bin/bash" if sys.platform == "darwin" else "bash"
PLIST_REL = Path("Library/LaunchAgents/com.claudemicro.bridge.plist")

LEAK_CHECK = """# 子プロセスへ実トークンが環境継承されていたら記録する (レビュー指摘)
if [[ -n "${APPROVAL_BRIDGE_TOKEN:-}${TOKEN:-}" ]]; then
    touch "$state/leak"
fi
"""

LAUNCHCTL_SHIM = f"""#!/bin/bash
# テスト用 launchctl: bootstrap でマーカーを作り、以後だけ service print に応答する
state="${{CLAUDEMICRO_TEST_STATE:?}}"
{LEAK_CHECK}
case "${{1:-}}" in
    bootstrap)
        touch "$state/bootstrapped"
        ;;
    print)
        target="${{2:-}}"
        if [[ "$target" == gui/*/* ]]; then
            [[ -e "$state/bootstrapped" ]] || exit 1
            echo "    state = running"
            echo "    pid = 12345"
        fi
        ;;
esac
exit 0
"""

NC_SHIM = f"""#!/bin/bash
# テスト用 nc -z: bootstrap 済みのときだけ「ポートが応答する」扱いにする
state="${{CLAUDEMICRO_TEST_STATE:?}}"
{LEAK_CHECK}
[[ -e "$state/bootstrapped" ]]
"""


class InstallServiceTestBase(unittest.TestCase):
    def _env(self, extra_env=None, *, home=None, shim_path=None, state=None):
        env = {
            key: value for key, value in os.environ.items()
            if key not in ("APPROVAL_BRIDGE_TOKEN", "CLAUDEMICRO_PORT",
                           "CLAUDEMICRO_PYTHON", "CLAUDEMICRO_TEST_STATE")
        }
        if home is not None:
            env["HOME"] = str(home)
        if shim_path is not None:
            env["PATH"] = f"{shim_path}{os.pathsep}" + env.get("PATH", "")
        if state is not None:
            env["CLAUDEMICRO_TEST_STATE"] = str(state)
        env.update(extra_env or {})
        return env

    def _run(self, args, env):
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            capture_output=True, text=True, env=env, timeout=60)

    def assert_plutil_valid(self, plist_text: str):
        """plutil が使える環境では Apple 実装でも整形式を確認する。"""
        plutil = shutil.which("plutil")
        if not plutil:
            return
        descriptor, path = tempfile.mkstemp(suffix=".plist")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(plist_text)
            proc = subprocess.run(
                [plutil, "-lint", path], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        finally:
            os.unlink(path)


class DryRunTests(InstallServiceTestBase):
    def _dry_run(self, extra_env=None):
        return self._run(["--dry-run"], self._env(extra_env))

    def test_default_has_no_environment_variables(self):
        """環境変数なしなら従来どおり EnvironmentVariables を書かない。"""
        proc = self._dry_run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = plistlib.loads(proc.stdout.encode("utf-8"))
        self.assertNotIn("EnvironmentVariables", data)
        self.assertEqual(data["Label"], "com.claudemicro.bridge")
        self.assertEqual(data["ProgramArguments"][1:], ["-m", "server.main"])
        self.assert_plutil_valid(proc.stdout)

    def test_token_is_masked_and_port_visible(self):
        """dry-run は実トークンを標準出力 (CI ログ等) へ出さない。"""
        token = "real-secret-token"
        proc = self._dry_run(
            {"APPROVAL_BRIDGE_TOKEN": token, "CLAUDEMICRO_PORT": "45710"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(token, proc.stdout)
        data = plistlib.loads(proc.stdout.encode("utf-8"))
        env_vars = data["EnvironmentVariables"]
        self.assertEqual(env_vars["APPROVAL_BRIDGE_TOKEN"], "********")
        self.assertEqual(env_vars["CLAUDEMICRO_PORT"], "45710")

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

    def test_control_char_token_is_rejected(self):
        """改行・タブ入りトークンはコマンド置換や HTTP ヘッダで壊れるため拒否する。"""
        for bad in ("bad\ntoken", "bad\ttoken", "bad\rtoken"):
            with self.subTest(bad=repr(bad)):
                proc = self._dry_run({"APPROVAL_BRIDGE_TOKEN": bad})
                self.assertEqual(proc.returncode, 2, proc.stdout)
                self.assertIn("制御文字", proc.stderr)


class FakeInstallTests(InstallServiceTestBase):
    """fake launchctl/nc + 一時 HOME で本経路を通し、権限と埋め込み内容を検証する。"""

    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp(prefix="claudemicro-install-test-"))
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.home = self.workdir / "home"
        self.home.mkdir()
        self.state = self.workdir / "state"
        self.state.mkdir()
        shims = self.workdir / "bin"
        shims.mkdir()
        for name, body in (("launchctl", LAUNCHCTL_SHIM), ("nc", NC_SHIM)):
            shim = shims / name
            shim.write_text(body, encoding="utf-8")
            shim.chmod(0o755)
        self.shims = shims

    def _install(self, extra_env=None):
        env = self._env(
            {"CLAUDEMICRO_PYTHON": sys.executable, **(extra_env or {})},
            home=self.home, shim_path=self.shims, state=self.state)
        return self._run([], env)

    def _installed_plist(self):
        path = self.home / PLIST_REL
        self.assertTrue(path.is_file(), f"plist がありません: {path}")
        return path

    def test_install_with_token_embeds_real_value_with_0600(self):
        token = 'se&c<r>et"tok'
        # 呼び出し元が TOKEN を export 済みでも、スクリプト内の TOKEN 代入が
        # export 属性を引き継いで漏れないこと (export -n) も同時に検証する
        proc = self._install(
            {"APPROVAL_BRIDGE_TOKEN": token, "CLAUDEMICRO_PORT": "45710",
             "TOKEN": "caller-exported"})
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # 実トークンが launchctl/nc の環境へ継承されていない (shim が leak を記録する)
        self.assertFalse((self.state / "leak").exists(),
                         "子プロセスの環境に実トークンが継承された")
        path = self._installed_plist()
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600, oct(mode))
        text = path.read_text(encoding="utf-8")
        data = plistlib.loads(text.encode("utf-8"))
        env_vars = data["EnvironmentVariables"]
        self.assertEqual(env_vars["APPROVAL_BRIDGE_TOKEN"], token)
        self.assertEqual(env_vars["CLAUDEMICRO_PORT"], "45710")
        self.assertEqual(data["ProgramArguments"][0], sys.executable)
        self.assertIn("0600", proc.stdout)  # 平文保存の注意が表示される
        self.assert_plutil_valid(text)

    def test_install_without_env_keeps_0644_and_no_env_block(self):
        proc = self._install()
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        path = self._installed_plist()
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o644, oct(mode))
        data = plistlib.loads(path.read_bytes())
        self.assertNotIn("EnvironmentVariables", data)
