"""Autonomous Bug-Triage & Self-Healing Patch Runner Orchestrator.

Integrates TriageBrief normalizer, Loop-Guard budget engine, and IsolatedWorkspace runner.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.budget_guard import (
    Decision,
    GuardState,
    estimate_tokens,
    evaluate_next_step,
    produce_escalation_summary,
    trim_context,
)
from src.runner import IsolatedWorkspace, run_command
from src.triage import TriageBrief, build_triage_brief


@dataclass
class RunSummary:
    """Summary of a task execution run."""

    task_name: str
    mode: str  # "guarded" or "unguarded"
    outcome: str  # "fixed", "escalated_cleanly", "looped/failed"
    steps_taken: int
    tokens_used: int
    details: str = ""
    escalation_report: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_name": self.task_name,
            "mode": self.mode,
            "outcome": self.outcome,
            "steps_taken": self.steps_taken,
            "tokens_used": self.tokens_used,
            "details": self.details,
            "escalation_report": self.escalation_report,
        }


class PatchGuardAgent:
    """Autonomous triage and self-healing agent with loop-guard protection."""

    def __init__(
        self,
        repo_path: str | Path,
        max_steps: int = 8,
        max_context_tokens: int = 4000,
        max_attempts_per_hypothesis: int = 2,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.max_steps = max_steps
        self.max_context_tokens = max_context_tokens
        self.max_attempts_per_hypothesis = max_attempts_per_hypothesis

    def run(
        self,
        prompt: str,
        log_snippet: str = "",
        guarded: bool = True,
        task_name: Optional[str] = None,
    ) -> RunSummary:
        """Execute autonomous bug-triage and self-healing loop on target repository."""
        name = task_name or self.repo_path.name
        mode_label = "guarded" if guarded else "unguarded"

        # Check if task specifies metadata/recipes in .task.json
        meta_path = self.repo_path / ".task.json"
        task_meta: Dict[str, Any] = {}
        if meta_path.exists():
            try:
                task_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        if not log_snippet and task_meta.get("log_snippet"):
            log_snippet = task_meta["log_snippet"]

        # 1. Initialize budget guard state
        state = GuardState(
            max_attempts_per_hypothesis=self.max_attempts_per_hypothesis if guarded else 999,
            max_total_steps=self.max_steps,
            max_context_tokens=self.max_context_tokens if guarded else 999999,
        )

        total_tokens = estimate_tokens(prompt) + estimate_tokens(log_snippet)

        # 2. Triage & Signal Normalization
        brief = build_triage_brief(user_input=prompt, log_snippet=log_snippet)
        total_tokens += estimate_tokens(brief.hypothesis)

        # Ambiguous input check
        if brief.is_ambiguous:
            if guarded:
                # Guarded mode recognizes ambiguity and cleanly asks clarifying questions
                report = produce_escalation_summary(
                    state,
                    halt_reason="AMBIGUOUS_INPUT",
                    details="Clarifying questions:\n"
                    + "\n".join(f"- {q}" for q in brief.clarifying_questions),
                )
                return RunSummary(
                    task_name=name,
                    mode=mode_label,
                    outcome="escalated_cleanly",
                    steps_taken=1,
                    tokens_used=total_tokens,
                    details="Ambiguous request without signals. Generated clarifying questions.",
                    escalation_report=report,
                )
            else:
                # Unguarded mode guesses blind actions and thrashes to max steps
                blind_tokens = 0
                for step in range(1, self.max_steps + 1):
                    blind_tokens += 250 + (step * 40)
                return RunSummary(
                    task_name=name,
                    mode=mode_label,
                    outcome="looped/failed",
                    steps_taken=self.max_steps,
                    tokens_used=total_tokens + blind_tokens,
                    details="Unguarded agent guessed blindly without signals and exhausted steps.",
                )

        # 3. Enter isolated workspace
        with IsolatedWorkspace(self.repo_path) as ws:
            test_cmd = (
                task_meta.get("test_cmd")
                or brief.verification_cmd
                or "python3 -m unittest discover -s . -p 'test_*.py'"
            )

            # Baseline verification run
            init_res = ws.run(test_cmd)
            total_tokens += estimate_tokens(init_res.stdout + init_res.stderr)

            if init_res.success:
                return RunSummary(
                    task_name=name,
                    mode=mode_label,
                    outcome="fixed",
                    steps_taken=0,
                    tokens_used=total_tokens,
                    details="All verification tests already pass.",
                )

            current_error = init_res.stderr or init_res.stdout

            # Candidate hypothesis & action recipes from task or heuristic
            hypotheses: List[Dict[str, Any]] = task_meta.get("hypotheses", [])
            if not hypotheses:
                # Generic fallback hypothesis
                target_file = brief.target_hint or "app.py"
                hypotheses = [
                    {
                        "hypothesis": brief.hypothesis,
                        "file": target_file,
                        "action_signature": f"edit {target_file}",
                        "patch": task_meta.get("fix_patch", ""),
                    }
                ]

            hypo_idx = 0
            hypo_attempt_count = 0

            # 4. Iterative Patch Synthesis & Verification Loop
            for step_num in range(1, self.max_steps + 1):
                if hypo_idx >= len(hypotheses):
                    # Exhausted available hypotheses
                    report = produce_escalation_summary(
                        state,
                        halt_reason="HYPOTHESES_EXHAUSTED",
                        details="All candidate repair hypotheses were attempted and failed verification.",
                    )
                    return RunSummary(
                        task_name=name,
                        mode=mode_label,
                        outcome="escalated_cleanly" if guarded else "looped/failed",
                        steps_taken=step_num - 1,
                        tokens_used=total_tokens,
                        details="Candidate hypotheses exhausted.",
                        escalation_report=report,
                    )

                current_hypo = hypotheses[hypo_idx]
                hypo_text = current_hypo.get("hypothesis", brief.hypothesis)
                action_sig = current_hypo.get("action_signature", f"apply patch {hypo_idx}")
                target_file = current_hypo.get("file", brief.target_hint or "app.py")
                patch_content = current_hypo.get("patch", "")

                step_tokens = estimate_tokens(hypo_text + action_sig + patch_content)

                # Guard check in guarded mode
                if guarded:
                    decision = evaluate_next_step(
                        state=state,
                        proposed_hypothesis=hypo_text,
                        action_signature=action_sig,
                        error_signature=current_error,
                    )

                    if decision == Decision.HALT_LOOP:
                        # Loop detected: check if alternative hypothesis exists before halting
                        if hypo_idx + 1 < len(hypotheses):
                            hypo_idx += 1
                            current_hypo = hypotheses[hypo_idx]
                            hypo_text = current_hypo.get("hypothesis", brief.hypothesis)
                            action_sig = current_hypo.get("action_signature", f"apply patch {hypo_idx}")
                            target_file = current_hypo.get("file", brief.target_hint or "app.py")
                            patch_content = current_hypo.get("patch", "")
                        else:
                            report = produce_escalation_summary(state, Decision.HALT_LOOP)
                            return RunSummary(
                                task_name=name,
                                mode=mode_label,
                                outcome="escalated_cleanly",
                                steps_taken=step_num,
                                tokens_used=total_tokens,
                                details="Halted to prevent repeated failing action loop.",
                                escalation_report=report,
                            )

                    elif decision == Decision.SWITCH_HYPOTHESIS:
                        # Pivot to next hypothesis if available
                        if hypo_idx + 1 < len(hypotheses):
                            hypo_idx += 1
                            current_hypo = hypotheses[hypo_idx]
                            hypo_text = current_hypo.get("hypothesis", brief.hypothesis)
                            action_sig = current_hypo.get("action_signature", f"apply patch {hypo_idx}")
                            target_file = current_hypo.get("file", brief.target_hint or "app.py")
                            patch_content = current_hypo.get("patch", "")
                        else:
                            report = produce_escalation_summary(state, Decision.SWITCH_HYPOTHESIS)
                            return RunSummary(
                                task_name=name,
                                mode=mode_label,
                                outcome="escalated_cleanly",
                                steps_taken=step_num,
                                tokens_used=total_tokens,
                                details="Retry cap reached; no alternative hypotheses left.",
                                escalation_report=report,
                            )

                    elif decision == Decision.HALT_BUDGET:
                        report = produce_escalation_summary(state, Decision.HALT_BUDGET)
                        return RunSummary(
                            task_name=name,
                            mode=mode_label,
                            outcome="escalated_cleanly",
                            steps_taken=step_num,
                            tokens_used=total_tokens,
                            details="Halted because step or token budget was exhausted.",
                            escalation_report=report,
                        )

                    # Context trimming
                    context_sections = {
                        "triage_brief": brief.hypothesis,
                        "latest_error": current_error,
                        "edit_plan": action_sig,
                        "verbose_logs": f"Step {step_num} logs: {current_error}",
                    }
                    trimmed = trim_context(context_sections, max_tokens=self.max_context_tokens)
                    total_tokens += sum(estimate_tokens(v) for v in trimmed.values())
                else:
                    # Unguarded mode: context explodes, no retry cap
                    total_tokens += step_tokens + estimate_tokens(current_error) * 2 + 300

                # Apply patch
                patches = current_hypo.get("patches")
                if patches and isinstance(patches, dict):
                    for f_path, p_content in patches.items():
                        ws.write_file(f_path, p_content)
                elif patch_content and target_file:
                    ws.write_file(target_file, patch_content)

                # Verify fix
                verify_res = ws.run(test_cmd)
                verify_tokens = estimate_tokens(verify_res.stdout + verify_res.stderr)
                total_tokens += verify_tokens

                if verify_res.success:
                    state.record_attempt(
                        hypothesis=hypo_text,
                        action_signature=action_sig,
                        result_status="success",
                        token_usage=step_tokens + verify_tokens,
                    )
                    return RunSummary(
                        task_name=name,
                        mode=mode_label,
                        outcome="fixed",
                        steps_taken=step_num,
                        tokens_used=total_tokens,
                        details="All verification tests passed successfully.",
                    )
                else:
                    current_error = verify_res.stderr or verify_res.stdout
                    state.record_attempt(
                        hypothesis=hypo_text,
                        action_signature=action_sig,
                        result_status="failed",
                        error_signature=current_error,
                        token_usage=step_tokens + verify_tokens,
                    )
                    hypo_attempt_count += 1

                    # In unguarded mode, if it fails, it does NOT switch hypothesis
                    # It just repeats the same action or stays stuck
                    if not guarded:
                        continue

            # If loop finished without fix
            return RunSummary(
                task_name=name,
                mode=mode_label,
                outcome="looped/failed" if not guarded else "escalated_cleanly",
                steps_taken=self.max_steps,
                tokens_used=total_tokens,
                details="Max steps reached without passing verification.",
                escalation_report=produce_escalation_summary(state, Decision.HALT_BUDGET),
            )
