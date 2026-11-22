"""Unit tests for the Agent orchestrator and CLI entrypoint."""

from pathlib import Path
import unittest

from src.agent import PatchGuardAgent
from src.cli import main


class TestAgentAndCLI(unittest.TestCase):
    """Test suite covering end-to-end agent execution and CLI commands."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.task1 = self.repo_root / "benchmarks" / "tasks" / "01_broken_assertion"
        self.task4 = self.repo_root / "benchmarks" / "tasks" / "04_impossible_loop"
        self.task6 = self.repo_root / "benchmarks" / "tasks" / "06_ambiguous_fix_this"

    def test_agent_guarded_broken_assertion(self):
        agent = PatchGuardAgent(self.task1)
        res = agent.run("Fix failing assertion in calc.py", guarded=True)
        self.assertEqual(res.outcome, "fixed")
        self.assertEqual(res.steps_taken, 1)

    def test_agent_guarded_impossible_loop_escalation(self):
        agent = PatchGuardAgent(self.task4)
        res = agent.run("Fix failing assertion in test_logic.py", guarded=True)
        self.assertEqual(res.outcome, "escalated_cleanly")
        self.assertIsNotNone(res.escalation_report)
        self.assertIn("HALT_LOOP", res.escalation_report)

    def test_agent_guarded_ambiguous_input(self):
        agent = PatchGuardAgent(self.task6)
        res = agent.run("fix this", guarded=True)
        self.assertEqual(res.outcome, "escalated_cleanly")
        self.assertEqual(res.steps_taken, 1)

    def test_cli_run_command_success(self):
        ret = main(["run", "--repo", str(self.task1), "--prompt", "Fix failing assertion in calc.py"])
        self.assertEqual(ret, 0)

    def test_cli_compare_command(self):
        ret = main(["compare", "--repo", str(self.task1), "--prompt", "Fix failing assertion in calc.py"])
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
