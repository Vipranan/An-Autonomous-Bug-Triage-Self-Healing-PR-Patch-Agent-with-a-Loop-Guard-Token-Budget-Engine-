# AGENTS.md

## Project Goals
**PatchGuard** is a cross-platform CLI autonomous bug-triage and self-healing patch runner equipped with:
- Automated bug triage and hypothesis generation from issue reports, diffs, and test traces.
- Iterative, self-healing patch synthesis and validation against regression test suites.
- Built-in **Loop Guard** engine capping retries (max 2 attempts per hypothesis) and stopping repetitive thrashing.
- Token and context budget tracking to avoid unbounded LLM usage and cost runaways.

## Cross-Platform Conventions (WSL, macOS, Windows)
- **WSL (Ubuntu / Linux)**: Standard POSIX paths (`~/projects/patchguard`). Shell: `bash` / `zsh`.
- **macOS (Terminal / iTerm2)**: Unix paths (`/Users/<user>/projects/patchguard`). Shell: `zsh` / `bash`.
- **Windows (PowerShell / Windows Terminal)**: Native Windows paths (`C:\dev\patchguard`). Shell: `powershell.exe` / `pwsh`.
- **Path Portability**: Always use `pathlib.Path` or `os.path` rather than hardcoding `/tmp` or backslashes.
- **Line Endings**: Enforce standard `LF` line endings across all platforms (`git config core.autocrlf input`).
- **Python Executable**: Python 3.10+ invoked via `python3` (WSL/macOS) or `python` (Windows PowerShell).

## Exact Test & Benchmark Commands
- **WSL & macOS**:
  ```bash
  python3 -m unittest discover -s tests -p "test_*.py"
  python3 benchmarks/run_eval.py
  ```
- **Windows (PowerShell)**:
  ```powershell
  python -m unittest discover -s tests -p "test_*.py"
  python benchmarks/run_eval.py
  ```
- **Lint & Format Check**:
  ```bash
  ruff check .
  ruff format --check .
  ```

## Guardrails
- **Scoped Edits**: Keep changes minimal and laser-focused on the targeted bug. Never perform unsolicited broad refactoring.
- **Secrets & Sensitive Data**: NEVER inspect, read, modify, or commit secrets, credentials, API keys, `.env`, or `.env.*` files.
- **Narrow Checks**: Prefer targeted file reads and isolated unit test runs over broad full-repo scans.
- **Loop Guard Compliance**: Adhere strictly to the hypothesis retry cap (max 2 attempts per hypothesis) and token budget limits defined in `.agents/rules/loop-guard.md`.
