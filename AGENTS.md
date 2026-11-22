# AGENTS.md

## Project Goals
**PatchGuard** is a CLI-based autonomous bug-triage and self-healing patch runner equipped with:
- Automated bug triage and hypothesis generation from issue reports and test failures.
- Iterative, self-healing patch synthesis and validation against regression test suites.
- Built-in **Loop Guard** engine capping retry attempts and preventing recursive agent thrashing.
- Token and context budget tracking to avoid unbounded LLM usage and cost runaways.

## WSL Development Conventions
- **Environment**: Linux environment hosted on WSL (Ubuntu). All scripts and operations must use standard Unix paths and bash utilities.
- **Line Endings & Formatting**: Enforce Unix line endings (`LF`). Do not commit Windows `CRLF` line endings.
- **File Permissions**: Maintain standard Linux file permissions; ensure executable scripts have appropriate permissions (`chmod +x`).
- **Python Runtime**: Python 3.10+ (using `python3` or virtual environments in `.venv`).

## Exact Test & Lint Commands
- **Run Tests (Standard Library - zero external dependencies required)**:
  ```bash
  python3 -m unittest discover -s tests -p "test_*.py"
  ```
- **Run Tests (pytest - when dev dependencies are installed)**:
  ```bash
  pytest tests/
  ```
- **Lint & Format Check**:
  ```bash
  ruff check .
  ruff format --check .
  ```

## Guardrails
- **Scoped Edits**: Keep changes minimal and laser-focused on the targeted bug or task. Never perform unsolicited broad refactoring.
- **Secrets & Sensitive Data**: NEVER inspect, read, modify, or commit secrets, credentials, API keys, `.env`, or `.env.*` files.
- **Narrow Checks**: Prefer targeted file reads (specific line ranges) and isolated unit/regression test runs over broad full-repo scans or heavy test suites.
- **Loop Guard Compliance**: Adhere strictly to the hypothesis retry cap (max 2 attempts per hypothesis) and token budget limits defined in `.agents/rules/loop-guard.md`.
