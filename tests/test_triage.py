"""Unit tests for the Input Normalizer and Triage Brief module."""

import unittest
from src.triage import TriageBrief, build_triage_brief


class TestTriageBrief(unittest.TestCase):
    """Test suite covering deterministic triage brief generation."""

    def test_fix_this_with_error_log_snippet(self):
        """Covers: 'fix this' + error/log snippet."""
        user_input = "fix this"
        log_snippet = """
Traceback (most recent call last):
  File "src/patchguard/engine.py", line 42, in run_loop
    result = execute_step(current_state)
  File "src/patchguard/utils.py", line 15, in execute_step
    raise ZeroDivisionError("division by zero")
ZeroDivisionError: division by zero
"""
        brief = build_triage_brief(user_input, log_snippet=log_snippet)

        self.assertFalse(brief.is_ambiguous)
        self.assertEqual(brief.raw_input, "fix this")
        self.assertEqual(brief.target_hint, "src/patchguard/utils.py")
        self.assertIn("ZeroDivisionError", brief.hypothesis)
        self.assertIn("src/patchguard/utils.py", brief.hypothesis)
        self.assertIsNotNone(brief.verification_cmd)
        self.assertIn("python3 -m unittest", brief.verification_cmd)
        self.assertEqual(len(brief.clarifying_questions), 0)
        self.assertIn("log", brief.signals)
        self.assertEqual(brief.signals["log"]["error_type"], "ZeroDivisionError")

    def test_fix_this_with_pytest_failure_snippet(self):
        """Covers: pytest failure snippet in log."""
        user_input = "fix this"
        log_snippet = "FAILED tests/test_engine.py::test_guard_retry_cap - AssertionError: retries exceeded"
        brief = build_triage_brief(user_input, log_snippet=log_snippet)

        self.assertFalse(brief.is_ambiguous)
        self.assertEqual(brief.target_hint, "tests/test_engine.py")
        self.assertEqual(brief.verification_cmd, "pytest tests/test_engine.py::test_guard_retry_cap")
        self.assertIn("AssertionError", brief.hypothesis)

    def test_fix_this_with_git_diff(self):
        """Covers: 'fix this' + recent git diff."""
        user_input = "fix this"
        git_diff = """diff --git a/src/patchguard/runner.py b/src/patchguard/runner.py
index 1234567..89abcdef 100644
--- a/src/patchguard/runner.py
+++ b/src/patchguard/runner.py
@@ -10,3 +10,4 @@ def run():
+    faulty_call()
"""
        brief = build_triage_brief(user_input, git_diff=git_diff)

        self.assertFalse(brief.is_ambiguous)
        self.assertEqual(brief.raw_input, "fix this")
        self.assertEqual(brief.target_hint, "src/patchguard/runner.py")
        self.assertIn("runner.py", brief.hypothesis)
        self.assertIsNotNone(brief.verification_cmd)
        self.assertEqual(len(brief.clarifying_questions), 0)
        self.assertIn("git_diff", brief.signals)
        self.assertEqual(brief.signals["git_diff"]["modified_files"], ["src/patchguard/runner.py"])

    def test_fix_this_with_no_signals_ambiguous(self):
        """Covers: 'fix this' with no signals (is_ambiguous == True and clarifying questions populated)."""
        user_input = "fix this"
        brief = build_triage_brief(user_input, git_diff="", log_snippet="")

        self.assertTrue(brief.is_ambiguous)
        self.assertIsNone(brief.target_hint)
        self.assertIsNone(brief.verification_cmd)
        self.assertGreaterEqual(len(brief.clarifying_questions), 1)
        self.assertLessEqual(len(brief.clarifying_questions), 2)
        # Ensure questions are actionable
        self.assertTrue(any("file" in q.lower() or "module" in q.lower() for q in brief.clarifying_questions))
        self.assertTrue(any("error" in q.lower() or "traceback" in q.lower() for q in brief.clarifying_questions))

    def test_pluggable_planner_callback(self):
        """Test optional pluggable model/planner callback override."""
        def custom_planner(brief: TriageBrief) -> TriageBrief:
            brief.hypothesis = "Custom model refined hypothesis"
            brief.target_hint = "custom/module.py"
            brief.verification_cmd = "pytest tests/custom_test.py"
            brief.is_ambiguous = False
            return brief

        brief = build_triage_brief("fix this", planner_fn=custom_planner)
        self.assertFalse(brief.is_ambiguous)
        self.assertEqual(brief.hypothesis, "Custom model refined hypothesis")
        self.assertEqual(brief.target_hint, "custom/module.py")
        self.assertEqual(brief.verification_cmd, "pytest tests/custom_test.py")

    def test_to_dict_serialization(self):
        """Ensure TriageBrief can serialize cleanly to a dictionary."""
        brief = build_triage_brief("fix this")
        brief_dict = brief.to_dict()
        self.assertIsInstance(brief_dict, dict)
        self.assertEqual(brief_dict["raw_input"], "fix this")
        self.assertTrue(brief_dict["is_ambiguous"])
        self.assertIn("clarifying_questions", brief_dict)


if __name__ == "__main__":
    unittest.main()
