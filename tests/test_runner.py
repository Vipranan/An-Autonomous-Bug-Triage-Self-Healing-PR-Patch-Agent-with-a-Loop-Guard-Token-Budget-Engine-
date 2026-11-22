"""Unit tests for the Workspace and Verification Runner."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

from src.runner import (
    CommandResult,
    IsolatedWorkspace,
    PathTraversalError,
    resolve_safe_path,
    run_command,
    safe_read_file,
    safe_write_file,
)


class TestRunner(unittest.TestCase):
    """Test suite covering workspace isolation, path traversal guards, and command execution."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.test_dir.name)

        # Seed initial files
        (self.base_dir / "app.py").write_text("print('hello world')", encoding="utf-8")
        (self.base_dir / "sub").mkdir()
        (self.base_dir / "sub" / "data.txt").write_text("test-data", encoding="utf-8")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_path_traversal_detection(self):
        """Verify resolve_safe_path, safe_read_file, safe_write_file reject path traversal."""
        # Relative traversal up
        with self.assertRaises(PathTraversalError):
            resolve_safe_path(self.base_dir, "../outside.txt")

        with self.assertRaises(PathTraversalError):
            resolve_safe_path(self.base_dir, "sub/../../outside.txt")

        # Absolute traversal outside base
        outside_abs = Path(tempfile.gettempdir()).resolve().parent
        if outside_abs == self.base_dir.resolve():
            outside_abs = outside_abs.parent
        with self.assertRaises(PathTraversalError):
            resolve_safe_path(self.base_dir, outside_abs)

        with self.assertRaises(PathTraversalError):
            safe_read_file(self.base_dir, "../outside.txt")

        with self.assertRaises(PathTraversalError):
            safe_write_file(self.base_dir, "../escape.txt", "malicious")

        # Valid in-boundary paths should resolve correctly
        valid = resolve_safe_path(self.base_dir, "app.py")
        self.assertEqual(valid, (self.base_dir / "app.py").resolve())

        sub_valid = resolve_safe_path(self.base_dir, "sub/data.txt")
        self.assertEqual(sub_valid, (self.base_dir / "sub" / "data.txt").resolve())

    def test_safe_read_and_write_file(self):
        """Verify safe reading and writing within boundary."""
        content = safe_read_file(self.base_dir, "app.py")
        self.assertEqual(content, "print('hello world')")

        written_path = safe_write_file(self.base_dir, "sub/new_file.py", "val = 42")
        self.assertTrue(written_path.exists())
        self.assertEqual(safe_read_file(self.base_dir, "sub/new_file.py"), "val = 42")

    def test_run_command_success_and_capture(self):
        """Verify normal command execution capturing stdout, stderr, and returncode."""
        result = run_command([
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('stdout test\\n'); sys.stderr.write('stderr test\\n')",
        ])
        self.assertEqual(result.returncode, 0)
        self.assertIn("stdout test", result.stdout)
        self.assertIn("stderr test", result.stderr)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.truncated)
        self.assertTrue(result.success)

    def test_run_command_timeout(self):
        """Verify execution times out cleanly without hanging."""
        # Sleep for 5 seconds with a 0.5s timeout
        result = run_command([sys.executable, "-c", "import time; time.sleep(5)"], timeout_sec=0.5)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -1)
        self.assertIn("Command timed out", result.stderr)
        self.assertFalse(result.success)

    def test_run_command_output_truncation(self):
        """Verify oversized stdout/stderr is truncated symmetrically to protect token budgets."""
        # Generate 20,000 characters
        cmd = [sys.executable, "-c", "print('A' * 20000)"]
        result = run_command(cmd, max_output_chars=500)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.truncated)
        self.assertIn("[truncated", result.stdout)
        self.assertLess(len(result.stdout), 1000)

    def test_isolated_workspace_isolation_and_teardown(self):
        """Verify experiments inside IsolatedWorkspace do not dirty the source repository."""
        original_app_file = self.base_dir / "app.py"
        original_content = original_app_file.read_text(encoding="utf-8")

        with IsolatedWorkspace(self.base_dir) as ws:
            ws_path = ws.workspace_dir
            self.assertIsNotNone(ws_path)
            self.assertTrue(ws_path.exists())
            self.assertNotEqual(ws_path, self.base_dir)

            # Mutate file in workspace
            ws.write_file("app.py", "print('modified in sandbox')")
            ws.write_file("new_temp.py", "x = 100")

            # Verify isolated workspace sees the changes
            self.assertEqual(ws.read_file("app.py"), "print('modified in sandbox')")
            self.assertEqual(ws.read_file("new_temp.py"), "x = 100")

            # Run a command inside workspace
            res = ws.run("python3 app.py")
            self.assertEqual(res.returncode, 0)
            self.assertIn("modified in sandbox", res.stdout)

            # CRITICAL CHECK: Original source repo MUST remain completely unmodified
            self.assertEqual(original_app_file.read_text(encoding="utf-8"), original_content)
            self.assertFalse((self.base_dir / "new_temp.py").exists())

        # CRITICAL CHECK: Workspace directory must be cleaned up after exit
        self.assertFalse(ws_path.exists())


if __name__ == "__main__":
    unittest.main()
