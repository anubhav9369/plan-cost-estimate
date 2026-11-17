# plan-cost-estimate

Price an InspectablePlan before a human approves it — the question an
approver actually asks is "what will saying yes cost me?", and it
should be answered from the plan file alone, before anything executes.
Part of the trustworthy-agentic-ai pipeline (BRJP26100123). Week 2:
human-in-the-loop approval.

`plan-approve` records the decision; this prices it. Each step may
carry an estimate: `{"minutes": 20, "usd": 0.40}`. A step with no
estimate is unknown, not zero — the tool refuses to pretend an
unpriced step is free, and an irreversible step with no estimate is
flagged as blind, the worst case for an approver.

## Usage

```bash
python3 plan_cost_estimate.py examples/plan.json
python3 plan_cost_estimate.py examples/plan.json --budget-minutes 30 --budget-usd 1
python3 plan_cost_estimate.py examples/plan.json --json
```

Defaults: time budget 120 min, money budget $5, any single step over
60 min is flagged as long. Exit codes: 0 within budget and fully
estimated, 1 problems found, 2 input error.

## What it flags

- **no estimate** — a step with no price at all (unknown, not zero)
- **partially estimated** — minutes but no cost, or cost but no time
- **blind irreversible** — an irreversible step with no estimate
- **long step** — one step over `--max-step-minutes`
- **over budget** — known totals above `--budget-minutes` / `--budget-usd`

## Examples

- `examples/plan.json` — a 4-step demo plan, fully priced: 35 min,
  $1.90, inside the default budgets. Exits 0.
- `examples/expensive-plan.json` — a 90-minute sweep, a step with
  minutes but no cost, and an irreversible step with no estimate at
  all. Try it against a tight budget:

```bash
python3 plan_cost_estimate.py examples/expensive-plan.json --budget-minutes 60 --budget-usd 2; echo "exit: $?"
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

14 stdlib tests, no dependencies. Run from the repo root.
