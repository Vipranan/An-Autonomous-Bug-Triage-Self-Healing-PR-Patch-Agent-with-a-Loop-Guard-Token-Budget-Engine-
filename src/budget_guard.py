"""Loop-Guard and Token Budget Controller for PatchGuard.

Provides session and task state tracking, retry capping per hypothesis,
action-loop detection, token estimation, context trimming, and escalation reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence, Union


class Decision(str, Enum):
    """Decision output by evaluate_next_step."""

    ALLOW = "ALLOW"
    SWITCH_HYPOTHESIS = "SWITCH_HYPOTHESIS"
    HALT_LOOP = "HALT_LOOP"
    HALT_BUDGET = "HALT_BUDGET"


def hash_signature(content: str) -> str:
    """Compute a normalized short hash for an error or action signature."""
    if not content:
        return ""
    normalized = " ".join(content.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def estimate_tokens(text: str) -> int:
    """Estimate token count for text using standard ~4 chars/token heuristic.

    In typical code and mixed English LLM tokenizers (tiktoken, sentencepiece),
    1 token is approximately 4 characters (or ~0.75 words).
    """
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4.0))


@dataclass
class AttemptRecord:
    """Record of a single patch or verification attempt."""

    hypothesis: str
    action_signature: str
    result_status: str  # e.g., "failed", "success", "error"
    error_hash: str
    step_index: int = 0
    token_usage: int = 0
    raw_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis": self.hypothesis,
            "action_signature": self.action_signature,
            "result_status": self.result_status,
            "error_hash": self.error_hash,
            "step_index": self.step_index,
            "token_usage": self.token_usage,
            "raw_error": self.raw_error,
        }


@dataclass
class GuardState:
    """Tracks state and budget constraints for a bug triage and repair session."""

    max_attempts_per_hypothesis: int = 2
    max_total_steps: int = 8
    max_context_tokens: int = 4000
    attempt_history: List[AttemptRecord] = field(default_factory=list)
    current_step: int = 0
    total_tokens_consumed: int = 0

    def record_attempt(
        self,
        hypothesis: str,
        action_signature: str,
        result_status: str,
        error_signature: str = "",
        token_usage: int = 0,
    ) -> AttemptRecord:
        """Log an execution attempt and advance step counter and token totals."""
        self.current_step += 1
        self.total_tokens_consumed += token_usage

        record = AttemptRecord(
            hypothesis=hypothesis,
            action_signature=action_signature,
            result_status=result_status,
            error_hash=hash_signature(error_signature),
            step_index=self.current_step,
            token_usage=token_usage,
            raw_error=error_signature,
        )
        self.attempt_history.append(record)
        return record


def trim_context(
    sections: Dict[str, str],
    max_tokens: int = 4000,
) -> Dict[str, str]:
    """Trim context sections to fit within max_tokens.

    Preserves high-priority protected sections ('triage_brief', 'latest_error', 'edit_plan')
    while truncating or dropping lower-priority verbose logs and old tool outputs first.

    Args:
        sections: Mapping of section name to text content.
        max_tokens: Maximum allowed total token budget.

    Returns:
        New dictionary with trimmed or preserved section contents.
    """
    if not sections:
        return {}

    # Define protected sections that must be preserved
    protected_keys = {"triage_brief", "latest_error", "edit_plan"}

    # Calculate initial token counts
    section_tokens = {k: estimate_tokens(v) for k, v in sections.items()}
    total_tokens = sum(section_tokens.values())

    if total_tokens <= max_tokens:
        return dict(sections)

    trimmed: Dict[str, str] = dict(sections)

    # 1. Identify deprioritized keys (verbose logs, old tool outputs)
    deprioritized_keys = [k for k in sections if k not in protected_keys]

    # Calculate tokens reserved by protected sections
    protected_tokens = sum(section_tokens[k] for k in protected_keys if k in sections)
    available_for_deprioritized = max(0, max_tokens - protected_tokens)

    # If even protected alone exceed max_tokens, drop all deprioritized and truncate protected
    if available_for_deprioritized == 0:
        for k in deprioritized_keys:
            trimmed[k] = "[Dropped to preserve token budget]"

        # Distribute remaining budget among protected sections
        scale = max_tokens / max(1, protected_tokens)
        for k in protected_keys:
            if k in trimmed:
                target_chars = int(len(trimmed[k]) * scale)
                if target_chars < len(trimmed[k]):
                    trimmed[k] = trimmed[k][:target_chars] + "\n...[truncated]"
        return trimmed

    # 2. Progressively truncate/drop deprioritized sections
    num_deprioritized = len(deprioritized_keys)
    if num_deprioritized > 0:
        per_section_budget = available_for_deprioritized // num_deprioritized
        max_chars_per_section = per_section_budget * 4

        for k in deprioritized_keys:
            text = trimmed[k]
            if len(text) > max_chars_per_section:
                if max_chars_per_section <= 40:
                    trimmed[k] = "[Dropped to preserve token budget]"
                else:
                    head_chars = max_chars_per_section // 2
                    tail_chars = max_chars_per_section - head_chars
                    trimmed[k] = (
                        text[:head_chars]
                        + "\n...[verbose output truncated]...\n"
                        + text[-tail_chars:]
                    )

    return trimmed


def evaluate_next_step(
    state: GuardState,
    proposed_hypothesis: str,
    action_signature: str,
    error_signature: str = "",
) -> Decision:
    """Evaluate whether the next execution step is permitted or violates guardrails.

    Decisions:
        HALT_BUDGET: Total steps or token budget exceeded.
        HALT_LOOP: Repeating the exact same failing action_signature + error_signature.
        SWITCH_HYPOTHESIS: Same error or hypothesis attempted max_attempts_per_hypothesis times.
        ALLOW: Within step/retry limits and budget.
    """
    # 1. Budget Checks (Total steps or Token budget)
    if state.current_step >= state.max_total_steps:
        return Decision.HALT_BUDGET

    if state.total_tokens_consumed >= state.max_context_tokens:
        return Decision.HALT_BUDGET

    err_hash = hash_signature(error_signature)
    action_hash = hash_signature(action_signature)

    # 2. Action-Loop Detection: Repeating exact failing action + error combination
    for record in state.attempt_history:
        if record.result_status != "success":
            record_action_hash = hash_signature(record.action_signature)
            if (
                record_action_hash == action_hash
                and record.error_hash == err_hash
                and err_hash != ""
            ):
                return Decision.HALT_LOOP

    # 3. Hypothesis Retry Cap Check
    # Count failed attempts under the exact same proposed hypothesis
    attempts_under_hypothesis = [
        r
        for r in state.attempt_history
        if r.hypothesis == proposed_hypothesis and r.result_status != "success"
    ]
    if len(attempts_under_hypothesis) >= state.max_attempts_per_hypothesis:
        return Decision.SWITCH_HYPOTHESIS

    # Also check if the same error has been seen max_attempts_per_hypothesis times
    if err_hash:
        same_error_attempts = [
            r
            for r in state.attempt_history
            if r.error_hash == err_hash and r.result_status != "success"
        ]
        if len(same_error_attempts) >= state.max_attempts_per_hypothesis:
            return Decision.SWITCH_HYPOTHESIS

    return Decision.ALLOW


def produce_escalation_summary(
    state: GuardState,
    halt_reason: Union[Decision, str],
    details: Optional[str] = None,
) -> str:
    """Generate a clean escalation report when halting execution."""
    reason_str = halt_reason.value if isinstance(halt_reason, Decision) else str(halt_reason)

    lines = [
        "# PatchGuard Escalation Report",
        "",
        f"**Termination Reason**: `{reason_str}`",
        f"**Steps Executed**: {state.current_step} / {state.max_total_steps}",
        f"**Total Tokens Consumed**: {state.total_tokens_consumed} / {state.max_context_tokens}",
        "",
        "## What Was Tried",
    ]

    if not state.attempt_history:
        lines.append("- No attempts were recorded prior to halting.")
    else:
        for idx, rec in enumerate(state.attempt_history, start=1):
            status_badge = "FAILED" if rec.result_status != "success" else "PASSED"
            lines.append(
                f"- **Step {idx}** [{status_badge}]: Hypothesis: *{rec.hypothesis}*"
            )
            lines.append(f"  - Action: `{rec.action_signature}`")
            if rec.raw_error:
                err_preview = rec.raw_error.strip().splitlines()[0][:100]
                lines.append(f"  - Failure Signal: `{err_preview}`")

    lines.extend([
        "",
        "## What Failed",
    ])

    distinct_errors = set(
        r.raw_error.strip().splitlines()[0]
        for r in state.attempt_history
        if r.raw_error and r.result_status != "success"
    )
    if distinct_errors:
        for err in distinct_errors:
            lines.append(f"- `{err}`")
    else:
        lines.append(
            "- Execution was stopped due to budget limits or repetitive loop detection."
        )

    lines.extend([
        "",
        "## Recommended Next Steps",
        "1. Inspect the latest failure traceback and verify if assumptions in the current hypothesis hold.",
        "2. Formulate a fundamentally different fix hypothesis or check for missing dependencies/configuration.",
        "3. Run the targeted verification command manually to isolate test flakiness.",
    ])

    if details:
        lines.extend(["", "## Additional Diagnostics", details])

    return "\n".join(lines)
