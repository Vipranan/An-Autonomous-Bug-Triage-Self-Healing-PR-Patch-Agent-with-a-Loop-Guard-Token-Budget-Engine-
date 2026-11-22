---
trigger: always_on
description: Loop protection, hypothesis retry capping, and context budget guardrails
---

# Loop Guard & Context Budget Rules

1. **Hypothesis Retry Limit**:
   - Cap consecutive retry attempts for any single bug-fix hypothesis at **2 attempts max**.
   - If an applied patch fails validation twice under the same hypothesis, immediately halt the current cycle, discard the assumption, and pivot to an alternative hypothesis or report a triage failure with a concise diagnosis.

2. **Targeted Reads and Narrow Checks**:
   - Always prefer targeted, localized file reads (e.g., specific line ranges, classes, or functions) over reading entire files.
   - Run minimal, isolated test cases that specifically target the failure before running broad or long-running test suites.
   - Avoid executing redundant or exploratory commands that bloat the context window.

3. **Status Update Conciseness**:
   - Keep status updates, progress summaries, and diagnostic reports brief, factual, and actionable.
   - Avoid verbose chain-of-thought narration, speculative ramblings, or redundant repetitions of file contents.

4. **Context & Token Budget Conservation**:
   - Continuously protect context window headroom.
   - Refuse recursive self-healing loops without explicit exit criteria and bounded iterations.
