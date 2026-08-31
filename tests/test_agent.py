from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starter.agent import Agent, normalize


def catalog_file() -> Path:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    rows = [
        {
            "parent_asin": "A",
            "title": "Blue cotton shirt",
            "features": ["soft cotton fabric"],
            "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts", "T-Shirts"],
            "average_rating": 4.0,
            "rating_number": 20,
        },
        {
            "parent_asin": "B",
            "title": "Blue polyester shirt",
            "features": ["durable polyester fabric"],
            "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts", "T-Shirts"],
            "average_rating": 5.0,
            "rating_number": 100,
        },
        {
            "parent_asin": "C",
            "title": "Leather black shoes",
            "features": ["formal footwear"],
            "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Loafers & Slip-Ons"],
            "average_rating": 5.0,
            "rating_number": 100,
        },
    ]
    for row in rows:
        handle.write(json.dumps(row) + "\n")
    handle.close()
    return Path(handle.name)


class AgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = catalog_file()
        self.agent = Agent(self.path)

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_normalization_and_documented_parsers(self) -> None:
        self.assertEqual(normalize(" Color: Blue!  "), "color blue")
        self.assertEqual(
            self.agent._parse("I'm looking for Shirts T-Shirts. A key requirement is: blue cotton."),
            ("Shirts T-Shirts", ["blue cotton"], False, False),
        )
        self.assertEqual(
            self.agent._parse("For that, what matters is: blue; soft cotton."),
            (None, ["blue", "soft cotton"], False, False),
        )
        self.assertEqual(
            self.agent._parse("Actually, ignore my earlier preference. What I need is: leather."),
            (None, ["leather"], False, True),
        )
        self.assertEqual(
            self.agent._parse("I don't have a preference for other; please use your judgment."),
            (None, None, False, False),
        )
        self.assertEqual(
            self.agent._parse("I don't have an additional preference for other."),
            (None, [], True, False),
        )

    def test_category_evidence_and_quality_tie_break(self) -> None:
        self.agent.reset("s", {})
        result = self.agent.respond(
            "s", "I'm looking for Shirts T-Shirts. A key requirement is: blue cotton.", 1, 2
        )
        self.assertEqual([item["parent_asin"] for item in result["recommendations"]], ["A", "B"])
        self.assertEqual(result["ask_attribute"], "other")
        self.assertNotIn("C", [item["parent_asin"] for item in result["recommendations"]])

    def test_sessions_override_and_exhaustion_are_isolated(self) -> None:
        self.agent.reset("first", {})
        self.agent.reset("second", {})
        self.agent.respond("first", "I'm looking for Shirts T-Shirts. A key requirement is: cotton.", 1, 1)
        self.agent.respond("second", "I'm looking for Loafers & Slip-Ons, but I'm still exploring.", 1, 1)
        overridden = self.agent.respond(
            "first", "Actually, ignore my earlier preference. What I need is: blue.", 2, 1
        )
        self.assertEqual(overridden["recommendations"][0]["parent_asin"], "B")
        exhausted = self.agent.respond("second", "I don't have an additional preference for other.", 2, 1)
        self.assertIsNone(exhausted["ask_attribute"])
        self.assertEqual(exhausted["recommendations"][0]["parent_asin"], "C")
        self.assertEqual(self.agent.respond("first", "unknown text", 3, 1)["ask_attribute"], "other")

    def test_exception_guard_returns_valid_cached_fallback(self) -> None:
        self.agent.reset("s", {})
        self.agent.respond("s", "I'm looking for Shirts T-Shirts, but I'm still exploring.", 1, 1)
        original = self.agent._parse
        self.agent._parse = lambda message: (_ for _ in ()).throw(RuntimeError("forced"))
        try:
            result = self.agent.respond("s", "anything", 2, 1)
        finally:
            self.agent._parse = original
        self.assertEqual(result["recommendations"][0]["parent_asin"], "B")
        self.assertIsInstance(result["message"], str)
        self.assertEqual(result["ask_attribute"], "other")

    def test_boundary_deferral_keeps_clarification_without_changing_recommendations(self) -> None:
        self.agent.reset("boundary", {})
        initial = self.agent.respond(
            "boundary", "I'm looking for Shirts T-Shirts, but I'm still exploring.", 1, 2
        )
        deferred = self.agent.respond(
            "boundary", "I don't have a preference for other; please use your judgment.", 2, 2
        )
        exhausted = self.agent.respond(
            "boundary", "I don't have an additional preference for other.", 3, 2
        )
        self.assertEqual(deferred["ask_attribute"], "other")
        self.assertEqual(exhausted["ask_attribute"], None)
        self.assertEqual(deferred["recommendations"], initial["recommendations"])
        self.assertEqual(exhausted["recommendations"], initial["recommendations"])


if __name__ == "__main__":
    unittest.main()
