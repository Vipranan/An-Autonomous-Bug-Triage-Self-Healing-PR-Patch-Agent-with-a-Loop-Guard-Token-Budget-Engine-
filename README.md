# PatchGuard 🛡️

> **Autonomous CLI bug-triage and self-healing patch runner equipped with an active Loop-Guard Engine and Token Budget Controller.**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Zero External Dependencies](https://img.shields.io/badge/Dependencies-Standard%20Library-green.svg)](pyproject.toml)
[![Tests Passing](https://img.shields.io/badge/Tests-25%2F25%20Passing-brightgreen.svg)](tests/)
[![WSL Ready](https://img.shields.io/badge/WSL-Ubuntu%2FLinux-purple.svg)](AGENTS.md)

---

## ⚡ 30-Second Elevator Pitch

Autonomous code-repair agents frequently enter **destructive retry loops** when hypotheses fail, burning through context window budgets and corrupting codebases.

**PatchGuard** solves this by inserting a deterministic runtime governor between the reasoning layer and the workspace:
- 🔁 **Loop-Guard Engine**: Detects repeated action/error signatures (`HALT_LOOP`) and enforces a strict **max-2 retry cap per hypothesis** before forcing an escalation or hypothesis switch.
- 💰 **Context Budget Controller**: Uses proactive context trimming to preserve critical plans and triage briefs while truncating verbose tool noise (reducing token overhead by **80.8%**).
- 🧪 **Ephemeral Isolated Workspaces**: Executes all edits and regression verification commands in temporary sandboxes—never dirtying git branches unless verified.
- 🛑 **Safe Triage on Ambiguity**: When given vague requests like `"fix this"` without signals, PatchGuard halts in 1 step with targeted clarifying questions instead of hallucinating random file edits.

---

## 🏗️ Architecture

```
                       +-----------------------------+
                       |   User Prompt / CI Trigger  |
                       +--------------+--------------+
                                      |
                                      v
                        +---------------------------+
                        | Input Normalizer & Triage | (src/triage.py)
                        |       Brief Engine        |
                        +-------------+-------------+
                                      |
                                      v
          +-------------------------------------------------------+
          |               PatchGuard Orchestrator                 | (src/agent.py)
          |                                                       |
          |  +--------------------+       +--------------------+  |
          |  |     Loop-Guard     | <---> | Isolated Workspace |  | (src/budget_guard.py
          |  |   & Budget Engine  |       |     & Runner       |  |  & src/runner.py)
          |  +--------------------+       +--------------------+  |
          +-------------------------------------------------------+
                                      |
                                      v
             +------------------------+------------------------+
             |                                                 |
             v                                                 v
    [ Fixed & Verified ]                            [ Clean Escalation Report ]
```

### Module Breakdown
- **[`src/triage.py`](src/triage.py)**: Deterministically parses tracebacks, pytest/unittest patterns, and git diffs to generate a structured `TriageBrief` without requiring paid API keys.
- **[`src/budget_guard.py`](src/budget_guard.py)**: Tracks session step budgets, enforces the hypothesis retry cap, manages `trim_context()`, and produces structured escalation reports.
- **[`src/runner.py`](src/runner.py)**: Manages isolated sandboxes (`IsolatedWorkspace`), enforces strict path traversal protection, and guards subprocess execution with timeout and output truncation.
- **[`src/agent.py`](src/agent.py)** & **[`src/cli.py`](src/cli.py)**: CLI and orchestrator supporting `--guarded`, `--unguarded`, and side-by-side `--compare` modes.

---

## ⚙️ Quickstart (WSL / Linux)

PatchGuard is self-contained and runs on Linux/WSL using standard library Python (zero external pip packages required).

```bash
# 1. Clone repository and navigate to root
git clone <repo_url> && cd <repo_name>

# 2. Run test suite (25 tests across all modules)
python3 -m unittest discover -s tests -p "test_*.py" -v

# 3. Run benchmark evaluation suite (Guarded vs. Unguarded comparison)
python3 benchmarks/run_eval.py
```

### CLI Commands
```bash
# Run self-healing triage on a target repo in Guarded mode (default)
python3 -m src.cli run --repo benchmarks/tasks/01_broken_assertion --prompt "Fix failing assertion in calc.py"

# Run side-by-side comparison on a task to observe loop prevention
python3 -m src.cli compare --repo benchmarks/tasks/04_impossible_loop --prompt "Fix failing test"
```

---

## 📊 Benchmark Evaluation: Guarded vs. Unguarded

Evaluated across 6 self-contained synthetic fixtures in [`benchmarks/tasks/`](benchmarks/tasks/) under `max_steps=8`:

| Task Name                 | Problem Archetype           | Guarded Outcome     | Unguarded Outcome | Guarded Steps | Guarded Tokens | Unguarded Tokens | Token Savings |
|---------------------------|-----------------------------|---------------------|-------------------|---------------|----------------|------------------|---------------|
| **01_broken_assertion**   | Arithmetic bug in logic     | `fixed`             | `fixed`           | 1             | 454            | 752              | **39.6%**     |
| **02_wrong_import**       | Symbol export mismatch      | `fixed`             | `fixed`           | 1             | 894            | 1,192            | **25.0%**     |
| **03_bad_config**         | Negative config value       | `fixed`             | `fixed`           | 1             | 597            | 886              | **32.6%**     |
| **04_impossible_loop**    | Contradictory requirement   | `escalated_cleanly` | `looped/failed`   | 2             | 759            | 6,654            | **88.6%**     |
| **05_flaky_hypothesis**   | Multi-hypothesis pivot      | `fixed`             | `looped/failed`   | 2             | 939            | 6,086            | **84.6%**     |
| **06_ambiguous_fix_this** | Vague prompt w/o signals    | `escalated_cleanly` | `looped/failed`   | 1             | 19             | 3,459            | **99.5%**     |
| **TOTALS**                |                             |                     |                   | **8 steps**   | **3,662**      | **19,029**       | **80.8%**     |

### Why This Matters:
1. **80.8% Token Conservation**: Context trimming and proactive loop detection reduced cumulative context window bloat from 19,029 tokens to 3,662 tokens.
2. **100% Loop Prevention**: When faced with impossible requirements or vague prompts, Guarded mode halts immediately with an escalation report rather than thrashing to max steps.
3. **Hypothesis Pivoting**: In `05_flaky_hypothesis`, Guarded mode detected hypothesis 1's failure and cleanly pivoted to hypothesis 2, fixing the bug within 2 steps while Unguarded mode remained locked in a failing retry cycle.

---

## 📋 Sample Escalation Output

When halting on a loop or exhausted hypothesis budget, PatchGuard generates a clear, actionable human handover report:

```markdown
# PatchGuard Escalation Report
**Termination Reason**: `HALT_LOOP`
**Steps Executed**: 2 / 8
**Total Tokens Consumed**: 759 / 4000

## What Was Tried
- **Step 1** [FAILED]: Hypothesis: *Return string A in logic.py*
  - Action: `edit logic.py: set return to 'A'`
  - Failure Signal: `AssertionError: False is not true : Contradictory requirement`

## What Failed
- `AssertionError: False is not true : Contradictory requirement`

## Recommended Next Steps
1. Inspect the latest failure traceback and verify if assumptions in the current hypothesis hold.
2. Formulate a fundamentally different fix hypothesis or check for missing dependencies/configuration.
3. Run the targeted verification command manually to isolate test flakiness.
```

---

## 🔒 Security & Guardrails

- **Zero Path Traversal**: Rejects relative (`../`) or absolute path traversal beyond the workspace root with `PathTraversalError`.
- **Zero Secret Exposure**: Strict rules forbidding inspection, logging, or committing `.env` or credential files.
- **Subprocess Isolation**: Enforces timeout limits (default 30s) and symmetric log truncation so runaway outputs never freeze the harness or blow up token limits.
- **Zero External API Lock-in**: Entire core operates deterministically out of the box with standard Python libraries.
