#!/usr/bin/env python3
"""Estimate what an InspectablePlan will cost before a human approves it.

A plan is cheap to read and expensive to run. This tool answers the
question an approver actually asks — "what will saying yes cost me?" —
from the plan file alone, before anything executes.

Each step may carry an estimate: {"minutes": 20, "usd": 0.40}.
A step with no estimate is unknown, not zero: the tool refuses to
pretend an unpriced step is free, and an irreversible step with no
estimate is flagged as blind — the worst case for an approver.

Usage:
    python3 plan_cost_estimate.py examples/plan.json
    python3 plan_cost_estimate.py examples/plan.json --budget-minutes 30 --budget-usd 1
    python3 plan_cost_estimate.py examples/plan.json --json

Exit codes: 0 within budget and fully estimated, 1 problems found,
2 input error.
"""

import argparse
import json
import sys

DEFAULT_BUDGET_MINUTES = 120.0
DEFAULT_BUDGET_USD = 5.0
DEFAULT_MAX_STEP_MINUTES = 60.0


class PlanError(ValueError):
    """The plan file is not a usable InspectablePlan."""


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_plan(path):
    """Load and validate a plan file. Returns the plan dict."""
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except OSError as exc:
        raise PlanError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(plan, dict):
        raise PlanError("plan must be a JSON object")
    steps = plan.get("steps")
    if not isinstance(steps, list):
        raise PlanError("plan must have a 'steps' list")
    seen_ids = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlanError(f"step {i} must be an object")
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            raise PlanError(f"step {i} must have a non-empty string 'id'")
        if step_id in seen_ids:
            raise PlanError(f"duplicate step id: {step_id}")
        seen_ids.add(step_id)
        if not isinstance(step.get("action"), str) or not step.get("action"):
            raise PlanError(f"step {step_id} must have a non-empty 'action'")
        estimate = step.get("estimate")
        if estimate is not None:
            if not isinstance(estimate, dict):
                raise PlanError(f"step {step_id}: 'estimate' must be an object")
            for key in ("minutes", "usd"):
                if key in estimate:
                    value = estimate[key]
                    if not _is_number(value) or value < 0:
                        raise PlanError(
                            f"step {step_id}: estimate.{key} must be a "
                            f"non-negative number, got {value!r}"
                        )
        if "irreversible" in step and not isinstance(step["irreversible"], bool):
            raise PlanError(f"step {step_id}: 'irreversible' must be true/false")
    return plan


def estimate(plan, budget_minutes=DEFAULT_BUDGET_MINUTES,
             budget_usd=DEFAULT_BUDGET_USD,
             max_step_minutes=DEFAULT_MAX_STEP_MINUTES):
    """Price a validated plan. Returns a result dict with totals, rows and problems."""
    rows = []
    problems = []
    total_minutes = 0.0
    total_usd = 0.0
    unknown_minutes = 0
    unknown_usd = 0
    no_estimate = 0
    blind_irreversible = 0
    long_steps = 0

    for step in plan.get("steps", []):
        est = step.get("estimate") or {}
        minutes = est.get("minutes")
        usd = est.get("usd")
        flags = []
        if not est:
            no_estimate += 1
            flags.append("no estimate")
        else:
            if minutes is None:
                flags.append("no time estimate")
            if usd is None:
                flags.append("no cost estimate")
        if minutes is None:
            unknown_minutes += 1
        else:
            total_minutes += minutes
            if minutes > max_step_minutes:
                long_steps += 1
                flags.append(f"long step ({minutes:g} min > {max_step_minutes:g} min)")
        if usd is None:
            unknown_usd += 1
        else:
            total_usd += usd
        if step.get("irreversible") and (minutes is None or usd is None):
            blind_irreversible += 1
            flags.append("blind irreversible")
        rows.append({
            "id": step["id"],
            "action": step["action"],
            "minutes": minutes,
            "usd": usd,
            "irreversible": bool(step.get("irreversible")),
            "flags": flags,
        })

    if no_estimate:
        problems.append(f"{no_estimate} step(s) have no estimate — price unknown, not zero")
    partial = sum(1 for r in rows if r["flags"] and "no estimate" not in r["flags"]
                  and any(f.startswith("no ") for f in r["flags"]))
    if partial:
        problems.append(f"{partial} step(s) only partially estimated")
    if blind_irreversible:
        problems.append(
            f"{blind_irreversible} irreversible step(s) with no estimate — approving blind"
        )
    if long_steps:
        problems.append(
            f"{long_steps} step(s) longer than {max_step_minutes:g} min per step"
        )
    if budget_minutes is not None and total_minutes > budget_minutes:
        problems.append(
            f"over time budget: {total_minutes:g} min known > {budget_minutes:g} min"
        )
    if budget_usd is not None and total_usd > budget_usd:
        problems.append(
            f"over money budget: ${total_usd:.2f} known > ${budget_usd:.2f}"
        )

    return {
        "plan_id": plan.get("id"),
        "version": plan.get("version"),
        "steps": rows,
        "total_minutes": total_minutes,
        "total_usd": round(total_usd, 2),
        "minutes_complete": unknown_minutes == 0,
        "usd_complete": unknown_usd == 0,
        "unknown_minutes_steps": unknown_minutes,
        "unknown_usd_steps": unknown_usd,
        "budget_minutes": budget_minutes,
        "budget_usd": budget_usd,
        "problems": problems,
        "verdict": "ok" if not problems else "problems",
    }


def render_text(result):
    """Render the estimate as a human-readable report."""
    lines = [f"Cost estimate for plan {result['plan_id']} (v{result['version']})", ""]
    for row in result["steps"]:
        minutes = f"{row['minutes']:g} min" if row["minutes"] is not None else "?"
        usd = f"${row['usd']:.2f}" if row["usd"] is not None else "?"
        suffix = " [irreversible]" if row["irreversible"] else ""
        flag_text = f"  <-- {'; '.join(row['flags'])}" if row["flags"] else ""
        lines.append(f"  {row['id']}: {row['action']} — {minutes}, {usd}{suffix}{flag_text}")
    lines.append("")
    minutes_note = "" if result["minutes_complete"] else (
        f" (+ {result['unknown_minutes_steps']} step(s) unpriced)")
    usd_note = "" if result["usd_complete"] else (
        f" (+ {result['unknown_usd_steps']} step(s) unpriced)")
    lines.append(f"Total time: {result['total_minutes']:g} min{minutes_note}")
    lines.append(f"Total cost: ${result['total_usd']:.2f}{usd_note}")
    if result["budget_minutes"] is not None:
        lines.append(f"Time budget: {result['budget_minutes']:g} min")
    if result["budget_usd"] is not None:
        lines.append(f"Money budget: ${result['budget_usd']:.2f}")
    lines.append("")
    if result["verdict"] == "ok":
        lines.append("Verdict: OK — fully estimated and within budget.")
    else:
        lines.append("Verdict: PROBLEMS — do not approve as priced:")
        for problem in result["problems"]:
            lines.append(f"  - {problem}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Estimate what an InspectablePlan will cost before approval.")
    parser.add_argument("plan", help="plan JSON file")
    parser.add_argument("--budget-minutes", type=float, default=DEFAULT_BUDGET_MINUTES,
                        help="time budget in minutes (default 120)")
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD,
                        help="money budget in USD (default 5)")
    parser.add_argument("--max-step-minutes", type=float, default=DEFAULT_MAX_STEP_MINUTES,
                        help="flag any single step longer than this (default 60)")
    parser.add_argument("--json", action="store_true",
                        help="print the machine-readable result instead of the report")
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = estimate(plan, budget_minutes=args.budget_minutes,
                      budget_usd=args.budget_usd,
                      max_step_minutes=args.max_step_minutes)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_text(result), end="")
    return 0 if result["verdict"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
