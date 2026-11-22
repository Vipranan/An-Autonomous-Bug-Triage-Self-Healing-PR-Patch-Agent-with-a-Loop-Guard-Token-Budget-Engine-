"""Workspace and Verification Runner for PatchGuard.

Provides isolated workspace execution (via copy or git worktrees),
path-traversal protection, sandboxed file operations, and safe subprocess execution
with output truncation and timeout guards.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import List, Optional, Sequence, Union


class PathTraversalError(PermissionError):
    """Raised when an operation attempts to access a path outside the workspace boundary."""


@dataclass
class CommandResult:
    """Execution output from run_command."""

    command: Union[str, List[str]]
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float = 0.0
    timed_out: bool = False
    truncated: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def resolve_safe_path(workspace_root: Union[str, Path], target_path: Union[str, Path]) -> Path:
    """Resolve target_path within workspace_root and prevent path traversal.

    Args:
        workspace_root: Absolute or relative root directory of the workspace.
        target_path: Relative or absolute path to check.

    Returns:
        Resolved absolute Path guaranteed to reside inside workspace_root.

    Raises:
        PathTraversalError: If target_path resolves outside workspace_root.
    """
    root_resolved = Path(workspace_root).resolve()
    target = Path(target_path)

    if target.is_absolute():
        resolved = target.resolve()
    else:
        resolved = (root_resolved / target).resolve()

    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise PathTraversalError(
            f"Path traversal detected: '{target_path}' resolves outside workspace '{root_resolved}'"
        )

    return resolved


def safe_read_file(workspace_root: Union[str, Path], file_path: Union[str, Path]) -> str:
    """Read file content safely within the workspace boundary."""
    safe_path = resolve_safe_path(workspace_root, file_path)
    if not safe_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    return safe_path.read_text(encoding="utf-8")


def safe_write_file(
    workspace_root: Union[str, Path], file_path: Union[str, Path], content: str
) -> Path:
    """Write file content safely within the workspace boundary, creating parent directories."""
    safe_path = resolve_safe_path(workspace_root, file_path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_text(content, encoding="utf-8")
    return safe_path


def _truncate_output(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text symmetrically around the center if it exceeds max_chars."""
    if not text or len(text) <= max_chars:
        return text, False

    excess = len(text) - max_chars
    half = max_chars // 2
    separator = f"\n... [truncated {excess} characters] ...\n"
    truncated_text = text[:half] + separator + text[-half:]
    return truncated_text, True


def run_command(
    cmd: Union[str, Sequence[str]],
    cwd: Optional[Union[str, Path]] = None,
    timeout_sec: float = 30.0,
    max_output_chars: int = 8000,
) -> CommandResult:
    """Execute command with timeout, capturing stdout/stderr and truncating oversized outputs.

    Args:
        cmd: Shell command string or argument list.
        cwd: Working directory for execution.
        timeout_sec: Maximum execution duration in seconds.
        max_output_chars: Maximum characters retained per output stream.

    Returns:
        CommandResult with captured output, timing, and truncation flags.
    """
    use_shell = isinstance(cmd, str)
    start_time = time.monotonic()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        duration = time.monotonic() - start_time

        stdout, stdout_trunc = _truncate_output(proc.stdout or "", max_output_chars)
        stderr, stderr_trunc = _truncate_output(proc.stderr or "", max_output_chars)

        return CommandResult(
            command=cmd,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_sec=duration,
            timed_out=False,
            truncated=(stdout_trunc or stderr_trunc),
        )

    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start_time
        raw_stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        raw_stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")

        stdout, stdout_trunc = _truncate_output(raw_stdout, max_output_chars)
        timeout_msg = f"Command timed out after {timeout_sec:.1f} seconds."
        stderr = (raw_stderr + "\n" + timeout_msg).strip() if raw_stderr else timeout_msg
        stderr, stderr_trunc = _truncate_output(stderr, max_output_chars)

        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            duration_sec=duration,
            timed_out=True,
            truncated=(stdout_trunc or stderr_trunc),
        )


class IsolatedWorkspace:
    """Manages an isolated working copy for autonomous triage and patch experiments.

    Ensures that modifications and experimental test runs never dirty the active
    source repository until explicitly committed or exported.
    """

    def __init__(
        self,
        source_dir: Union[str, Path],
        prefix: str = "patchguard_ws_",
        use_git_worktree: bool = True,
    ):
        self.source_dir = Path(source_dir).resolve()
        self.prefix = prefix
        self.use_git_worktree = use_git_worktree
        self.workspace_dir: Optional[Path] = None
        self._is_worktree = False

    def create(self) -> Path:
        """Create the isolated workspace directory."""
        if self.workspace_dir is not None and self.workspace_dir.exists():
            return self.workspace_dir

        temp_dir = Path(tempfile.mkdtemp(prefix=self.prefix))
        self.workspace_dir = temp_dir.resolve()

        # Attempt git worktree if enabled and source has git repository
        git_dir = self.source_dir / ".git"
        if self.use_git_worktree and git_dir.exists():
            # Check if repo has commits to branch/worktree from
            cmd = ["git", "-C", str(self.source_dir), "rev-parse", "--verify", "HEAD"]
            check = subprocess.run(cmd, capture_output=True, text=True)
            if check.returncode == 0:
                # Remove empty temp dir so git worktree add can initialize it
                shutil.rmtree(temp_dir, ignore_errors=True)
                wt_cmd = [
                    "git",
                    "-C",
                    str(self.source_dir),
                    "worktree",
                    "add",
                    "--detach",
                    str(temp_dir),
                    "HEAD",
                ]
                wt_run = subprocess.run(wt_cmd, capture_output=True, text=True)
                if wt_run.returncode == 0:
                    self._is_worktree = True
                    return self.workspace_dir

        # Fallback to copy-based isolation
        self._is_worktree = False
        # Remove empty temp dir to allow copytree to populate it
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.copytree(
            self.source_dir,
            temp_dir,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "venv"),
        )
        return self.workspace_dir

    def cleanup(self) -> None:
        """Clean up and tear down the isolated workspace."""
        if not self.workspace_dir or not self.workspace_dir.exists():
            return

        if self._is_worktree:
            # Safely remove git worktree
            wt_cmd = [
                "git",
                "-C",
                str(self.source_dir),
                "worktree",
                "remove",
                "--force",
                str(self.workspace_dir),
            ]
            subprocess.run(wt_cmd, capture_output=True, text=True)

        # Ensure directory is fully removed
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir, ignore_errors=True)

        self.workspace_dir = None
        self._is_worktree = False

    def read_file(self, rel_path: Union[str, Path]) -> str:
        """Read a file safely within this workspace."""
        if not self.workspace_dir:
            raise RuntimeError("Workspace has not been created.")
        return safe_read_file(self.workspace_dir, rel_path)

    def write_file(self, rel_path: Union[str, Path], content: str) -> Path:
        """Write a file safely within this workspace."""
        if not self.workspace_dir:
            raise RuntimeError("Workspace has not been created.")
        return safe_write_file(self.workspace_dir, rel_path, content)

    def run(
        self,
        cmd: Union[str, Sequence[str]],
        timeout_sec: float = 30.0,
        max_output_chars: int = 8000,
    ) -> CommandResult:
        """Run a command inside the isolated workspace."""
        if not self.workspace_dir:
            raise RuntimeError("Workspace has not been created.")
        return run_command(
            cmd=cmd,
            cwd=self.workspace_dir,
            timeout_sec=timeout_sec,
            max_output_chars=max_output_chars,
        )

    def __enter__(self) -> IsolatedWorkspace:
        self.create()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()
