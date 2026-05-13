"""Behavioral tests for .specify/scripts/bash/constitution-check.sh.

Each test sets up an isolated temporary git repository, drops in the lint
script under test, stages a scenario, and asserts the script's exit code
and message content.
"""
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LINT_SCRIPT = REPO_ROOT / ".specify" / "scripts" / "bash" / "constitution-check.sh"


def _run(cmd, cwd, check=True, env=None):
    full_env = os.environ.copy()
    # Avoid the operator's global git config (signing, hooks, templates)
    # leaking into the temp repo.
    full_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    full_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    full_env["GIT_AUTHOR_NAME"] = "Test"
    full_env["GIT_AUTHOR_EMAIL"] = "test@example.invalid"
    full_env["GIT_COMMITTER_NAME"] = "Test"
    full_env["GIT_COMMITTER_EMAIL"] = "test@example.invalid"
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=full_env,
    )


class ConstitutionCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="constitution-check-"))
        # Make a temp repo that mirrors the lint script's location, so its
        # pathspec excludes (':!**/constitution-check.sh', etc.) behave the
        # same as in the real repo.
        script_dir = self.tmp / ".specify" / "scripts" / "bash"
        script_dir.mkdir(parents=True)
        shutil.copy(LINT_SCRIPT, script_dir / "constitution-check.sh")
        (script_dir / "constitution-check.sh").chmod(0o755)
        self.script = script_dir / "constitution-check.sh"

        _run(["git", "init", "-q", "-b", "main", "."], cwd=self.tmp)
        # Seed an initial commit so HEAD exists.
        (self.tmp / "README.md").write_text("# tmp\n")
        _run(["git", "add", "README.md", ".specify"], cwd=self.tmp)
        _run(["git", "commit", "-q", "-m", "init"], cwd=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stage(self, rel_path: str, content: str):
        path = self.tmp / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        # -f because the lint targets paths that are typically gitignored;
        # the temp repo has no .gitignore but we want behavior parity.
        _run(["git", "add", "-f", rel_path], cwd=self.tmp)

    # ── happy path ────────────────────────────────────────────────────────
    def test_clean_repo_exits_zero(self):
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        r2 = _run([str(self.script), "--staged"], cwd=self.tmp, check=False)
        self.assertEqual(r2.returncode, 0, msg=r2.stderr)

    # ── usage errors ──────────────────────────────────────────────────────
    def test_unknown_mode_exits_two(self):
        r = _run([str(self.script), "--bogus"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown mode", r.stderr)

    def test_outside_git_repo_exits_two(self):
        nogit = Path(tempfile.mkdtemp(prefix="constitution-check-nogit-"))
        try:
            r = _run([str(self.script), "--full"], cwd=nogit, check=False)
            self.assertEqual(r.returncode, 2)
            self.assertIn("not inside a git repository", r.stderr)
        finally:
            shutil.rmtree(nogit, ignore_errors=True)

    # ── Principle II: tracked files under gitignored data roots ──────────
    def test_data_root_tracked_file_flags_principle_ii(self):
        self._stage("data/leak.json", '{"x": 1}\n')
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, msg=r.stderr)
        self.assertIn("Principle II", r.stderr)
        self.assertIn("data/leak.json", r.stderr)

    def test_export_root_tracked_file_flags_principle_ii(self):
        self._stage("export/site/index.html", "<html></html>\n")
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, msg=r.stderr)
        self.assertIn("Principle II", r.stderr)

    def test_claude_root_tracked_file_flags_principle_ii(self):
        self._stage(".claude/state.json", "{}\n")
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, msg=r.stderr)
        self.assertIn("Principle II", r.stderr)

    # ── Principle V: token-shaped strings ─────────────────────────────────
    def test_staged_openai_key_shape_flags_principle_v(self):
        self._stage(
            "src/leaky.py",
            'TOKEN = "sk-' + "a" * 40 + '"\n',
        )
        r = _run([str(self.script), "--staged"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, msg=r.stderr)
        self.assertIn("Principle V", r.stderr)

    def test_full_aws_key_shape_flags_principle_v(self):
        committed = self.tmp / "src" / "aws.py"
        committed.parent.mkdir(parents=True, exist_ok=True)
        committed.write_text('KEY = "AKIA' + "ABCDEFGHIJKLMNOP" + '"\n')
        _run(["git", "add", "src/aws.py"], cwd=self.tmp)
        _run(["git", "commit", "-q", "-m", "leak"], cwd=self.tmp)
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, msg=r.stderr)
        self.assertIn("Principle V", r.stderr)

    def test_constitution_doc_mentions_dont_flag_principle_v(self):
        # The constitution file itself mentions example prefixes like 'sk-…'
        # in prose; those MUST NOT be flagged. Simulate by adding text that
        # contains a literal placeholder, not a real-looking token.
        (self.tmp / ".specify" / "memory").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".specify" / "memory" / "constitution.md").write_text(
            "Tokens like `sk-" + "x" * 40 + "` MUST NOT be committed.\n"
        )
        _run(
            ["git", "add", ".specify/memory/constitution.md"],
            cwd=self.tmp,
        )
        r = _run([str(self.script), "--staged"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    # ── Principle VI: bare except ────────────────────────────────────────
    def test_bare_except_in_src_flags_principle_vi(self):
        bad = textwrap.dedent(
            """
            def f():
                try:
                    risky()
                except:
                    pass
            """
        ).lstrip()
        self._stage("src/bad.py", bad)
        _run(["git", "commit", "-q", "-m", "bad except"], cwd=self.tmp)
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, msg=r.stderr)
        self.assertIn("Principle VI", r.stderr)
        self.assertIn("src/bad.py", r.stderr)

    def test_narrow_except_in_src_passes(self):
        ok = textwrap.dedent(
            """
            def f():
                try:
                    risky()
                except ValueError:
                    raise
            """
        ).lstrip()
        self._stage("src/ok.py", ok)
        _run(["git", "commit", "-q", "-m", "ok except"], cwd=self.tmp)
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    # ── Principle VI: --no-verify in committed code ──────────────────────
    def test_no_verify_in_script_flags_principle_vi(self):
        self._stage("scripts/release.sh", "git commit --no-verify -m fast\n")
        _run(["git", "commit", "-q", "-m", "bad script"], cwd=self.tmp)
        r = _run([str(self.script), "--full"], cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, msg=r.stderr)
        self.assertIn("Principle VI", r.stderr)
        self.assertIn("--no-verify", r.stderr)


if __name__ == "__main__":
    unittest.main()
