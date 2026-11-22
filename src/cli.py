"""CLI entrypoint for PatchGuard.

Usage:
    patchguard run --repo <path> --prompt "<text>" [--log <path>] [--guarded | --unguarded]
    patchguard compare --repo <path> --prompt "<text>" [--log <path>]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Optional

from src.agent import PatchGuardAgent, RunSummary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patchguard",
        description="PatchGuard: CLI bug-triage and self-healing patch runner with loop protection.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run command
    run_parser = subparsers.add_parser("run", help="Run triage and patch repair on a repository.")
    run_parser.add_argument("--repo", required=True, help="Path to target repository.")
    run_parser.add_argument("--prompt", required=True, help="User issue description or prompt.")
    run_parser.add_argument("--log", default="", help="Optional path to error log / stack trace.")
    
    guard_group = run_parser.add_mutually_exclusive_group()
    guard_group.add_argument(
        "--guarded",
        action="store_true",
        default=True,
        help="Enable Loop-Guard, hypothesis retry cap, and context trimming (default).",
    )
    guard_group.add_argument(
        "--unguarded",
        action="store_true",
        help="Disable Loop-Guard and context limits to simulate unconstrained agent execution.",
    )
    run_parser.add_argument(
        "--compare",
        action="store_true",
        help="Run both guarded and unguarded modes side-by-side on this repository.",
    )

    # compare command
    cmp_parser = subparsers.add_parser("compare", help="Compare guarded vs. unguarded runs on a repository.")
    cmp_parser.add_argument("--repo", required=True, help="Path to target repository.")
    cmp_parser.add_argument("--prompt", required=True, help="User issue description or prompt.")
    cmp_parser.add_argument("--log", default="", help="Optional path to error log / stack trace.")

    return parser


def format_summary_card(summary: RunSummary) -> str:
    lines = [
        "========================================",
        f" Task:        {summary.task_name}",
        f" Mode:        {summary.mode.upper()}",
        f" Outcome:     {summary.outcome}",
        f" Steps Taken: {summary.steps_taken}",
        f" Est. Tokens: {summary.tokens_used}",
        f" Details:     {summary.details}",
        "========================================",
    ]
    if summary.escalation_report:
        lines.append("\n" + summary.escalation_report)
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_path = Path(args.repo).resolve()
    if not repo_path.exists():
        print(f"Error: Repository path '{args.repo}' does not exist.", file=sys.stderr)
        return 1

    log_snippet = ""
    if args.log:
        log_file = Path(args.log).resolve()
        if log_file.is_file():
            log_snippet = log_file.read_text(encoding="utf-8")
        else:
            log_snippet = args.log

    agent = PatchGuardAgent(repo_path=repo_path)

    if args.command == "compare" or (getattr(args, "compare", False)):
        print(f"\n[PatchGuard Comparison] Running task on {repo_path.name}...\n")
        guarded_res = agent.run(prompt=args.prompt, log_snippet=log_snippet, guarded=True)
        unguarded_res = agent.run(prompt=args.prompt, log_snippet=log_snippet, guarded=False)

        print("\n=== GUARDED RUN ===")
        print(format_summary_card(guarded_res))

        print("\n=== UNGUARDED RUN ===")
        print(format_summary_card(unguarded_res))
        return 0

    elif args.command == "run":
        is_guarded = not args.unguarded
        res = agent.run(prompt=args.prompt, log_snippet=log_snippet, guarded=is_guarded)
        print(format_summary_card(res))
        return 0 if res.outcome in ("fixed", "escalated_cleanly") else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
