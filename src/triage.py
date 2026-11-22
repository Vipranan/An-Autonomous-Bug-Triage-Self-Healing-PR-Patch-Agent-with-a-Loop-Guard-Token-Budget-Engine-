"""Input Normalizer and Triage Brief module for PatchGuard.

Provides structured triage brief generation from ambiguous user prompts,
git diffs, and log/traceback snippets without external API dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Union


@dataclass
class TriageBrief:
    """Structured representation of a triaged bug report or user request."""

    raw_input: str
    signals: Dict[str, Any] = field(default_factory=dict)
    target_hint: Optional[str] = None
    hypothesis: str = ""
    verification_cmd: Optional[str] = None
    is_ambiguous: bool = False
    clarifying_questions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert brief to a serializable dictionary."""
        return {
            "raw_input": self.raw_input,
            "signals": self.signals,
            "target_hint": self.target_hint,
            "hypothesis": self.hypothesis,
            "verification_cmd": self.verification_cmd,
            "is_ambiguous": self.is_ambiguous,
            "clarifying_questions": list(self.clarifying_questions),
        }


def _extract_git_diff_signals(
    git_diff: str, known_files: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """Parse git diff output to identify modified files and line changes."""
    signals: Dict[str, Any] = {
        "modified_files": [],
        "diff_summary": "",
    }
    if not git_diff or not git_diff.strip():
        return signals

    # Match git diff headers like "diff --git a/path b/path" or "--- a/path" / "+++ b/path"
    git_file_pattern = re.compile(r"diff --git a/(?P<old_path>.+?) b/(?P<new_path>.+)")
    alt_file_pattern = re.compile(r"\+\+\+ b/(?P<new_path>.+)")

    modified_files: List[str] = []
    for line in git_diff.splitlines():
        match = git_file_pattern.match(line)
        if match:
            path = match.group("new_path").strip()
            if path != "/dev/null" and path not in modified_files:
                modified_files.append(path)
            continue

        match_alt = alt_file_pattern.match(line)
        if match_alt:
            path = match_alt.group("new_path").strip()
            if path != "/dev/null" and path not in modified_files:
                modified_files.append(path)

    # Sort files by known_files relevance if available
    if known_files:
        modified_files.sort(key=lambda f: (f not in known_files, f))

    signals["modified_files"] = modified_files
    if modified_files:
        signals["diff_summary"] = (
            f"Modified {len(modified_files)} file(s): {', '.join(modified_files[:3])}"
            + ("..." if len(modified_files) > 3 else "")
        )

    return signals


def _extract_log_signals(
    log_snippet: str, known_files: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """Extract tracebacks, failing test identifiers, and error types from logs."""
    signals: Dict[str, Any] = {
        "error_type": None,
        "error_message": None,
        "failing_test": None,
        "traceback_files": [],
        "log_summary": "",
    }
    if not log_snippet or not log_snippet.strip():
        return signals

    # 1. Detect pytest failures: FAILED tests/test_foo.py::test_bar - ErrorType: msg
    pytest_match = re.search(
        r"FAILED\s+([^\s:]+)::([^\s\-\n]+)(?:\s*-\s*([A-Za-z0-9_.]+(?:Error|Exception)):\s*(.*))?",
        log_snippet,
    )
    if pytest_match:
        test_file = pytest_match.group(1)
        test_name = pytest_match.group(2)
        signals["failing_test"] = f"{test_file}::{test_name}"
        if pytest_match.group(3):
            signals["error_type"] = pytest_match.group(3)
        if pytest_match.group(4):
            signals["error_message"] = pytest_match.group(4).strip()

    # 2. Detect standard unittest failures: FAIL: test_bar (tests.test_foo.TestCase)
    unittest_match = re.search(
        r"(?:FAIL|ERROR):\s+([a-zA-Z0-9_]+)\s+\((?:([a-zA-Z0-9_.]+)\.)?([a-zA-Z0-9_]+)\)",
        log_snippet,
    )
    if unittest_match and not signals["failing_test"]:
        test_func = unittest_match.group(1)
        module = unittest_match.group(2)
        test_class = unittest_match.group(3)
        signals["failing_test"] = (
            f"{module}.{test_class}.{test_func}" if module else f"{test_class}.{test_func}"
        )

    # 3. Detect Python tracebacks: File "/path/to/file.py", line 123, in func
    traceback_files: List[str] = []
    file_matches = re.findall(
        r'File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+([a-zA-Z0-9_<>]+))?',
        log_snippet,
    )
    for path, line_no, func in file_matches:
        # Exclude standard library/virtualenv paths if project files exist
        if "/lib/python" not in path and "/site-packages/" not in path:
            norm_path = os.path.normpath(path)
            if norm_path not in traceback_files:
                traceback_files.append(norm_path)

    # If all were site-packages, keep all matches
    if not traceback_files and file_matches:
        traceback_files = [os.path.normpath(m[0]) for m in file_matches]

    signals["traceback_files"] = traceback_files

    # 4. Detect general Exception/Error lines
    error_match = re.search(
        r"\b([A-Z][a-zA-Z0-9_]*(?:Error|Exception|Failure))\b(?::\s*([^\n\r]+))?",
        log_snippet,
    )
    if error_match:
        if not signals["error_type"]:
            signals["error_type"] = error_match.group(1)
        if not signals["error_message"] and error_match.group(2):
            signals["error_message"] = error_match.group(2).strip()

    # Create summary
    parts = []
    if signals["error_type"]:
        parts.append(signals["error_type"])
    if signals["failing_test"]:
        parts.append(f"in test {signals['failing_test']}")
    elif signals["traceback_files"]:
        parts.append(f"in {signals['traceback_files'][-1]}")
    signals["log_summary"] = " ".join(parts) if parts else "Error log detected"

    return signals


def _extract_input_mentions(
    user_input: str, known_files: Optional[Set[str]] = None
) -> Optional[str]:
    """Detect if the user prompt explicitly references a file or command."""
    if not user_input:
        return None

    # Check for known_files mentioned in input
    if known_files:
        for f in known_files:
            if f in user_input:
                return f

    # Search for file path patterns (e.g. src/foo.py, tests/test_bar.py, etc.)
    match = re.search(r"\b([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9_]+)\b", user_input)
    if match:
        potential_file = match.group(1)
        if "." in os.path.basename(potential_file):
            return potential_file

    return None


def build_triage_brief(
    user_input: str,
    git_diff: str = "",
    log_snippet: str = "",
    known_files: Optional[Sequence[str] | Set[str]] = None,
    planner_fn: Optional[Callable[..., Any]] = None,
) -> TriageBrief:
    """Build a deterministic TriageBrief from input, diffs, and log signals.

    Args:
        user_input: Raw prompt/description from user.
        git_diff: Optional git diff string showing recent local modifications.
        log_snippet: Optional error log, traceback, or test output snippet.
        known_files: Optional collection of recognized repository file paths.
        planner_fn: Optional pluggable model/planner callback to override or refine brief.

    Returns:
        TriageBrief instance populated with signals, target hint, hypothesis, and verification command.
    """
    known_set = set(known_files) if known_files else set()

    diff_signals = _extract_git_diff_signals(git_diff, known_set)
    log_signals = _extract_log_signals(log_snippet, known_set)
    input_mention = _extract_input_mentions(user_input, known_set)

    combined_signals: Dict[str, Any] = {}
    if diff_signals.get("diff_summary"):
        combined_signals["git_diff"] = diff_signals
    if log_signals.get("log_summary"):
        combined_signals["log"] = log_signals
    if input_mention:
        combined_signals["user_mentioned_target"] = input_mention

    target_hint: Optional[str] = None
    hypothesis: str = ""
    verification_cmd: Optional[str] = None
    is_ambiguous: bool = False
    clarifying_questions: List[str] = []

    # Heuristic 1: Log snippet / traceback / test failure present
    if log_signals.get("failing_test") or log_signals.get("traceback_files") or log_signals.get("error_type"):
        failing_test = log_signals.get("failing_test")
        err_type = log_signals.get("error_type") or "Failure"
        err_msg = log_signals.get("error_message")

        # Determine target file hint
        if log_signals.get("traceback_files"):
            # The last file in the traceback is typically where the exception was raised
            target_hint = log_signals["traceback_files"][-1]
        elif failing_test:
            # Check if failing test contains a file path
            if "::" in failing_test:
                target_hint = failing_test.split("::")[0]
            else:
                target_hint = input_mention or (diff_signals["modified_files"][0] if diff_signals.get("modified_files") else None)
        else:
            target_hint = input_mention

        # Verification command
        if failing_test:
            if "::" in failing_test:
                verification_cmd = f"pytest {failing_test}"
            else:
                verification_cmd = f"python3 -m unittest {failing_test}"
        elif target_hint and target_hint.endswith(".py"):
            if "test" in target_hint:
                verification_cmd = f"python3 -m unittest {target_hint}"
            else:
                verification_cmd = "python3 -m unittest discover -s tests -p 'test_*.py'"
        else:
            verification_cmd = "python3 -m unittest discover -s tests -p 'test_*.py'"

        # Formulate hypothesis
        details = f": {err_msg}" if err_msg else ""
        loc_str = f" in {target_hint}" if target_hint else ""
        hypothesis = f"Fix {err_type}{loc_str}{details} causing regression or test failure."

    # Heuristic 2: Git diff present without explicit error log
    elif diff_signals.get("modified_files"):
        modified = diff_signals["modified_files"]
        target_hint = modified[0]

        # Check if one of the modified files is a test
        test_file = next((f for f in modified if "test" in f and f.endswith(".py")), None)
        if test_file:
            verification_cmd = f"python3 -m unittest {test_file}"
        else:
            verification_cmd = "python3 -m unittest discover -s tests -p 'test_*.py'"

        hypothesis = (
            f"Resolve regression or unexpected behavior introduced by recent changes in {target_hint}."
        )

    # Heuristic 3: User explicitly specified target in prompt
    elif input_mention:
        target_hint = input_mention
        hypothesis = f"Investigate and address issue reported in {target_hint}."
        if "test" in target_hint and target_hint.endswith(".py"):
            verification_cmd = f"python3 -m unittest {target_hint}"
        else:
            verification_cmd = "python3 -m unittest discover -s tests -p 'test_*.py'"

    # Heuristic 4: Ambiguous / insufficient information
    else:
        is_ambiguous = True
        target_hint = None
        hypothesis = "Insufficient signals to diagnose root cause or identify target file."
        verification_cmd = None
        clarifying_questions = [
            "Which file, module, or test command is encountering the issue?",
            "Can you provide the error message, traceback, or a reproducer command?",
        ]

    brief = TriageBrief(
        raw_input=user_input,
        signals=combined_signals,
        target_hint=target_hint,
        hypothesis=hypothesis,
        verification_cmd=verification_cmd,
        is_ambiguous=is_ambiguous,
        clarifying_questions=clarifying_questions,
    )

    # Optional pluggable planner/model callback
    if planner_fn is not None:
        try:
            custom_result = planner_fn(brief)
        except TypeError:
            custom_result = planner_fn(
                user_input=user_input,
                git_diff=git_diff,
                log_snippet=log_snippet,
                known_files=known_files,
            )
        if isinstance(custom_result, TriageBrief):
            brief = custom_result

    return brief
