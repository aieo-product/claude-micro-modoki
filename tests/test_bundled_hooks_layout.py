"""hooks 導入ファイル一式が「コピーされたレイアウト」でも動くこと (#81)。

.app 同梱 (pyinstaller/claudemicro.spec の hooks_datas) は、チェックアウトと
同じ相対配置 (<root>/hook_client.py + <root>/scripts/install_hooks.py) を
Resources 配下へコピーする。installer はクライアントを厳密パス解決するため、
この配置が崩れると .app からの hooks 導入が壊れる。ここではレイアウトの
コピーを模擬し、チェックアウト外からの導入が成立することを検証する。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
BUNDLED = (
    "hook_client.py",
    "codex_hook_client.py",
    "scripts/install_hooks.py",
    "scripts/uninstall_hooks.py",
)


class BundledLayoutTests(unittest.TestCase):
    def setUp(self):
        # macOS の /var -> /private/var を先に正規化し、installer の resolve() 出力と揃える
        self.tmp = Path(tempfile.mkdtemp(prefix="claudemicro-bundle-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "Resources"
        for rel in BUNDLED:
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_DIR / rel, dst)
        self.home = self.tmp / "home"
        self.home.mkdir()

    def _run(self, script: str):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / script), "--dry-run"],
            capture_output=True, text=True, env=env, timeout=60)

    def test_spec_lists_all_bundled_files(self):
        """spec の同梱リストとこのテストの前提レイアウトを同期させる。"""
        spec = (REPO_DIR / "pyinstaller" / "claudemicro.spec").read_text(
            encoding="utf-8")
        for rel in BUNDLED:
            self.assertIn(Path(rel).name, spec)

    def test_installer_dry_run_resolves_copied_layout(self):
        proc = self._run("install_hooks.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(str(self.root / "hook_client.py"), proc.stdout)
        self.assertIn(str(self.root / "codex_hook_client.py"), proc.stdout)
        self.assertIn(sys.executable, proc.stdout)

    def test_uninstaller_dry_run_works_from_copied_layout(self):
        proc = self._run("uninstall_hooks.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
