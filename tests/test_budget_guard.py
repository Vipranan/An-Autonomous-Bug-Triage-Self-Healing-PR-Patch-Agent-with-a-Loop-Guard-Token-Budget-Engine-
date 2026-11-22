"""Unit tests for the Loop-Guard and Token Budget Controller."""

import unittest
from src.budget_guard import (
    Decision,
    GuardState,
    estimate_tokens,
    evaluate_next_step,
    produce_escalation_summary,
    trim_context,
)


class TestBudgetGuard(unittest.TestCase):
    """Test suite covering loop guard, token budget, and context controls."""

    def test_estimate_tokens(self):
        """Verify token estimation heuristic (~4 chars per token)."""
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("a"), 1)
        self.assertEqual(estimate_tokens("1234"), 1)
        self.assertEqual(estimate_tokens("12345678"), 2)
        # 100 characters should estimate to ~25 tokens
        sample = "a" * 100
        self.assertEqual(estimate_tokens(sample), 25)

    def test_retry_cap_enforcement(self):
        """Verify capping at max_attempts_per_hypothesis triggers SWITCH_HYPOTHESIS."""
        state = GuardState(max_attempts_per_hypothesis=2, max_total_steps=8)
        hypothesis = "Fix ZeroDivisionError by adding check in calculate()"

        # First attempt: ALLOW
        decision = evaluate_next_step(state, hypothesis, "edit calculate.py:line 10", "ZeroDivisionError")
        self.assertEqual(decision, Decision.ALLOW)

        state.record_attempt(
            hypothesis=hypothesis,
            action_signature="edit calculate.py:line 10",
            result_status="failed",
            error_signature="ZeroDivisionError",
        )

        # Second attempt with different edit action under same hypothesis: ALLOW
        decision = evaluate_next_step(state, hypothesis, "edit calculate.py:line 15", "ZeroDivisionError")
        self.assertEqual(decision, Decision.ALLOW)

        state.record_attempt(
            hypothesis=hypothesis,
            action_signature="edit calculate.py:line 15",
            result_status="failed",
            error_signature="ZeroDivisionError",
        )

        # Third attempt under same hypothesis: SWITCH_HYPOTHESIS triggered
        decision = evaluate_next_step(state, hypothesis, "edit calculate.py:line 20", "ZeroDivisionError")
        self.assertEqual(decision, Decision.SWITCH_HYPOTHESIS)

        # If switching to a new hypothesis: ALLOW
        new_hypothesis = "Fix ZeroDivisionError by guarding caller in main.py"
        decision = evaluate_next_step(state, new_hypothesis, "edit main.py:line 5", "ZeroDivisionError_caller")
        self.assertEqual(decision, Decision.ALLOW)

    def test_repeated_action_loop_detection(self):
        """Verify repeating exact failing action + error combination triggers HALT_LOOP."""
        state = GuardState(max_attempts_per_hypothesis=3, max_total_steps=8)
        hypothesis = "Hypothesis A"
        action = "patch src/utils.py with hunk_a"
        error = "TypeError: unsupported operand type(s)"

        # Record a failed attempt
        state.record_attempt(
            hypothesis=hypothesis,
            action_signature=action,
            result_status="failed",
            error_signature=error,
        )

        # Attempting the exact same action and experiencing the exact same error -> HALT_LOOP
        decision = evaluate_next_step(state, hypothesis, action, error)
        self.assertEqual(decision, Decision.HALT_LOOP)

    def test_budget_exhaustion_steps(self):
        """Verify exceeding max_total_steps triggers HALT_BUDGET."""
        state = GuardState(max_total_steps=3)

        for i in range(3):
            state.record_attempt(
                hypothesis=f"Hypothesis {i}",
                action_signature=f"action_{i}",
                result_status="failed",
                error_signature=f"error_{i}",
            )

        decision = evaluate_next_step(
            state,
            proposed_hypothesis="Hypothesis 4",
            action_signature="action_4",
            error_signature="error_4",
        )
        self.assertEqual(decision, Decision.HALT_BUDGET)

    def test_budget_exhaustion_tokens(self):
        """Verify exceeding max_context_tokens triggers HALT_BUDGET."""
        state = GuardState(max_context_tokens=1000)
        state.record_attempt(
            hypothesis="Hypothesis 1",
            action_signature="action_1",
            result_status="failed",
            token_usage=1050,
        )

        decision = evaluate_next_step(
            state,
            proposed_hypothesis="Hypothesis 2",
            action_signature="action_2",
            error_signature="error_2",
        )
        self.assertEqual(decision, Decision.HALT_BUDGET)

    def test_context_trimming_preserves_protected_sections(self):
        """Verify verbose logs/old outputs are dropped/truncated first while protected items are preserved."""
        sections = {
            "triage_brief": "Active TriageBrief: Bug in src/parser.py line 40",
            "latest_error": "SyntaxError: invalid syntax at parser.py:40",
            "edit_plan": "Plan: replace token match with ast node parser",
            "verbose_logs": "TRACE log " * 500,  # ~5000 chars => ~1250 tokens
            "old_tool_outputs": "OUTPUT " * 500,   # ~3500 chars => ~875 tokens
        }

        # Budget of 300 tokens: protected tokens ~40 tokens, so verbose logs must be truncated
        trimmed = trim_context(sections, max_tokens=300)

        # Protected keys must be completely intact
        self.assertEqual(trimmed["triage_brief"], sections["triage_brief"])
        self.assertEqual(trimmed["latest_error"], sections["latest_error"])
        self.assertEqual(trimmed["edit_plan"], sections["edit_plan"])

        # Verbose sections should be truncated or dropped
        self.assertLess(len(trimmed["verbose_logs"]), len(sections["verbose_logs"]))
        self.assertLess(len(trimmed["old_tool_outputs"]), len(sections["old_tool_outputs"]))

    def test_escalation_summary_generation(self):
        """Verify escalation summary captures attempts, failure reason, and next steps."""
        state = GuardState(max_total_steps=5)
        state.record_attempt(
            hypothesis="Hypothesis 1",
            action_signature="edit file_a.py",
            result_status="failed",
            error_signature="AssertionError: expected 5 got 0",
        )
        state.record_attempt(
            hypothesis="Hypothesis 2",
            action_signature="edit file_b.py",
            result_status="failed",
            error_signature="KeyError: 'timeout'",
        )

        summary = produce_escalation_summary(state, Decision.HALT_LOOP)

        self.assertIn("PatchGuard Escalation Report", summary)
        self.assertIn("HALT_LOOP", summary)
        self.assertIn("Hypothesis 1", summary)
        self.assertIn("Hypothesis 2", summary)
        self.assertIn("AssertionError: expected 5 got 0", summary)
        self.assertIn("KeyError: 'timeout'", summary)
        self.assertIn("Recommended Next Steps", summary)


if __name__ == "__main__":
    unittest.main()
