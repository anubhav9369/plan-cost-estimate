"""Tests for plan_cost_estimate.py (stdlib only). Run from the repo root:

    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plan_cost_estimate import PlanError, estimate, load_plan, main  # noqa: E402

CLEAN = {
    "id": "plan-test",
    "version": 1,
    "steps": [
        {"id": "s1", "action": "Fetch papers", "estimate": {"minutes": 5, "usd": 0.10}},
        {"id": "s2", "action": "Summarise", "estimate": {"minutes": 15, "usd": 1.20}},
    ],
}


def with_estimate(plan, step_id, estimate):
    plan = json.loads(json.dumps(plan))
    for step in plan["steps"]:
        if step["id"] == step_id:
            step["estimate"] = estimate
    return plan


class TestEstimate(unittest.TestCase):
    def test_clean_plan_totals(self):
        result = estimate(CLEAN)
        self.assertEqual(result["total_minutes"], 20)
        self.assertEqual(result["total_usd"], 1.30)
        self.assertTrue(result["minutes_complete"])
        self.assertTrue(result["usd_complete"])
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(result["problems"], [])

    def test_missing_estimate_flagged(self):
        plan = json.loads(json.dumps(CLEAN))
        del plan["steps"][1]["estimate"]
        result = estimate(plan)
        self.assertEqual(result["verdict"], "problems")
        self.assertIn("no estimate", result["steps"][1]["flags"])
        self.assertFalse(result["usd_complete"])
        self.assertTrue(any("no estimate" in p for p in result["problems"]))

    def test_partial_estimate_flagged(self):
        plan = with_estimate(CLEAN, "s2", {"minutes": 15})
        result = estimate(plan)
        self.assertEqual(result["verdict"], "problems")
        self.assertIn("no cost estimate", result["steps"][1]["flags"])
        self.assertFalse(result["usd_complete"])
        self.assertTrue(result["minutes_complete"])

    def test_blind_irreversible_flagged(self):
        plan = json.loads(json.dumps(CLEAN))
        plan["steps"][1]["irreversible"] = True
        del plan["steps"][1]["estimate"]
        result = estimate(plan)
        self.assertEqual(result["verdict"], "problems")
        self.assertIn("blind irreversible", result["steps"][1]["flags"])
        self.assertTrue(any("approving blind" in p for p in result["problems"]))

    def test_irreversible_with_estimate_is_fine(self):
        plan = json.loads(json.dumps(CLEAN))
        plan["steps"][1]["irreversible"] = True
        result = estimate(plan)
        self.assertEqual(result["verdict"], "ok")
        self.assertTrue(result["steps"][1]["irreversible"])

    def test_over_time_budget(self):
        result = estimate(CLEAN, budget_minutes=10)
        self.assertEqual(result["verdict"], "problems")
        self.assertTrue(any("over time budget" in p for p in result["problems"]))

    def test_over_money_budget(self):
        result = estimate(CLEAN, budget_usd=1.0)
        self.assertEqual(result["verdict"], "problems")
        self.assertTrue(any("over money budget" in p for p in result["problems"]))

    def test_long_step_flagged(self):
        plan = with_estimate(CLEAN, "s2", {"minutes": 90, "usd": 1.20})
        result = estimate(plan, max_step_minutes=60)
        self.assertEqual(result["verdict"], "problems")
        self.assertTrue(any(f.startswith("long step") for f in result["steps"][1]["flags"]))

    def test_empty_plan_ok(self):
        result = estimate({"id": "empty", "version": 1, "steps": []})
        self.assertEqual(result["total_minutes"], 0)
        self.assertEqual(result["total_usd"], 0)
        self.assertEqual(result["verdict"], "ok")


class TestLoadPlan(unittest.TestCase):
    def test_duplicate_step_id_rejected(self):
        plan = json.loads(json.dumps(CLEAN))
        plan["steps"].append({"id": "s1", "action": "Again"})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            path = f.name
        try:
            with self.assertRaises(PlanError):
                load_plan(path)
        finally:
            os.unlink(path)

    def test_negative_estimate_rejected(self):
        plan = with_estimate(CLEAN, "s1", {"minutes": -5, "usd": 0.10})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            path = f.name
        try:
            with self.assertRaises(PlanError):
                load_plan(path)
        finally:
            os.unlink(path)


class TestMain(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_main_clean_exits_zero(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "examples", "plan.json")
        code, out = self._run([path])
        self.assertEqual(code, 0)
        self.assertIn("Total time: 35 min", out)
        self.assertIn("Total cost: $1.90", out)
        self.assertIn("Verdict: OK", out)

    def test_main_expensive_exits_one(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "examples", "expensive-plan.json")
        code, out = self._run([path, "--budget-minutes", "60", "--budget-usd", "2"])
        self.assertEqual(code, 1)
        self.assertIn("blind irreversible", out)
        self.assertIn("over time budget", out)

    def test_main_json_output_parses(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "examples", "plan.json")
        code, out = self._run([path, "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["total_minutes"], 35)
        self.assertEqual(parsed["total_usd"], 1.90)
        self.assertEqual(parsed["verdict"], "ok")


if __name__ == "__main__":
    unittest.main()
