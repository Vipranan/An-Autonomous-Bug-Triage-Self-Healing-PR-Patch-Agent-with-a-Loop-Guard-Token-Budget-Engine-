---
name: cross-platform
description: Guidelines and run commands for running PatchGuard seamlessly across WSL, macOS, and Windows PowerShell.
---

# Cross-Platform Execution Skill

Follow these conventions when invoking commands, inspecting paths, or running tests across environments:

## 1. Runtime Invocations
- **WSL / Linux** (`~/projects/...`): Use `python3 -m unittest ...` or `python3 -m src.cli ...`
- **macOS** (`/Users/.../projects/...`): Use `python3 -m unittest ...` or `python3 -m src.cli ...`
- **Windows PowerShell** (`C:\dev\...`): Use `python -m unittest ...` or `python -m src.cli ...`

## 2. Path Handling
- Always use `pathlib.Path` or `os.path.join()` rather than raw `/tmp` or backslash concatenations.
- Use `tempfile.mkdtemp()` or `tempfile.gettempdir()` for scratch directories.
- In test assertions, normalize paths via `.resolve()` or `.as_posix()`.

## 3. Shell Command Portability
- Pass command arguments as lists (`[sys.executable, "-c", "..."]`) rather than shell strings with nested quotes when possible to prevent `cmd.exe` / `powershell` quote escaping issues.
