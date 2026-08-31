from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starter.agent import Agent, _canonical_signature, _flatten_values, normalize


def catalog_file() -> Path:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    rows = [
        {
            "parent_asin": "A",
            "title": "Blue cotton shirt",
            "features": ["blue cotton", "soft cotton fabric"],
            "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts", "T-Shirts"],
            "average_rating": 4.0,
            "rating_number": 20,
        },
        {
            "parent_asin": "B",
            "title": "Blue cotton polyester shirt",
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

    def test_canonical_signature_flattens_all_structured_values(self) -> None:
        self.assertEqual(_flatten_values(["Blue", "Blue"]), ["Blue", "Blue"])
        self.assertEqual(_flatten_values({"Material": "Cotton", "Empty": ""}), ["Material: Cotton"])
        self.assertEqual(_flatten_values("Leather"), ["Leather"])
        self.assertEqual(_flatten_values(None), [])
        signature = _canonical_signature({
            "title": "Blue cotton shirt",
            "features": ["90% Cotton", "Machine Wash", "90% Cotton"],
            "details": {"Closure": "Pull On", "Department": "Womens"},
            "description": ["Soft blue fabric"],
            "categories": ["Clothing", "Shirts"],
            "store": "Example",
            "price": 19.99,
        })
        self.assertIsInstance(signature, frozenset)
        self.assertIn("90 cotton", signature)
        self.assertIn("closure pull on", signature)
        self.assertIn("cotton", signature)
        self.assertIn("color blue", signature)
        self.assertIn("budget around 19 99", signature)

    def test_signature_evidence_precedes_flattened_and_quality_ties(self) -> None:
        self.assertIn("blue cotton", self.agent._by_id["A"].signature)
        self.assertNotIn("blue cotton", self.agent._by_id["B"].signature)
        self.assertIn("blue cotton", self.agent._by_id["B"].text)
        self.agent.reset("signature", {})
        result = self.agent.respond(
            "signature", "I'm looking for Shirts T-Shirts. blue cotton.", 1, 2
        )
        self.assertEqual(result["recommendations"][0]["parent_asin"], "A")
        self.assertEqual(result, self.agent.respond(
            "signature", "unknown text", 2, 2
        ))

    def test_semantic_evidence_only_breaks_full_deterministic_ties(self) -> None:
        pool = (self.agent._by_id["A"], self.agent._by_id["B"])
        baseline = self.agent._rank(pool, ["novel"], 2)
        semantic = self.agent._rank(pool, ["novel"], 2, {"A": frozenset({"novel"})})
        self.assertEqual([item["parent_asin"] for item in baseline], ["B", "A"])
        self.assertEqual([item["parent_asin"] for item in semantic], ["A", "B"])

        literal_wins = self.agent._rank(pool, ["polyester"], 2, {"A": frozenset({"polyester"})})
        canonical_wins = self.agent._rank(pool, ["blue cotton"], 2, {"B": frozenset({"blue cotton"})})
        self.assertEqual(literal_wins[0]["parent_asin"], "B")
        self.assertEqual(canonical_wins[0]["parent_asin"], "A")
        self.assertEqual({item["parent_asin"] for item in semantic}, {"A", "B"})

    def test_normalization_and_documented_parsers(self) -> None:
        self.assertEqual(normalize(" Color: Blue!  "), "color blue")
        self.assertEqual(
            self.agent._parse("I'm looking for Shirts T-Shirts. A key requirement is: blue cotton."),
            ("Shirts T-Shirts", ["blue cotton"], False, False, None),
        )
        self.assertEqual(
            self.agent._parse("For that, what matters is: blue; soft cotton."),
            (None, ["blue", "soft cotton"], False, False, None),
        )
        self.assertEqual(
            self.agent._parse("Actually, ignore my earlier preference. What I need is: leather."),
            (None, ["leather"], False, True, "leather"),
        )
        self.assertEqual(
            self.agent._parse("I don't have a preference for other; please use your judgment."),
            (None, None, False, False, None),
        )
        self.assertEqual(
            self.agent._parse("I don't have an additional preference for other."),
            (None, [], True, False, None),
        )

        self.assertEqual(
            self.agent._parse("I'm looking for a jacket. a loose fit"),
            ("a jacket", ["a loose fit"], False, False, "a loose fit"),
        )

    def test_category_evidence_and_quality_tie_break(self) -> None:
        self.agent.reset("s", {})
        result = self.agent.respond(
            "s", "I'm looking for Shirts T-Shirts. A key requirement is: blue cotton.", 1, 2
        )
        self.assertEqual([item["parent_asin"] for item in result["recommendations"]], ["A"])
        self.assertEqual(result["ask_attribute"], "other")
        self.assertNotIn("C", [item["parent_asin"] for item in result["recommendations"]])

    def test_confidence_gated_breadth_widens_at_four_constraints_or_exhaustion(self) -> None:
        self.agent.reset("breadth", {})
        sparse = self.agent.respond(
            "breadth", "I'm looking for Shirts T-Shirts. A key requirement is: blue cotton.", 1, 2
        )
        self.assertEqual(len(sparse["recommendations"]), 1)
        self.agent.respond("breadth", "For that, what matters is: soft; imported.", 2, 2)
        sufficient = self.agent.respond("breadth", "For that, what matters is: machine wash.", 3, 2)
        self.assertEqual(len(sufficient["recommendations"]), 2)

        self.agent.reset("exhausted", {})
        exhausted = self.agent.respond(
            "exhausted", "I'm looking for Shirts T-Shirts. but I'm still exploring.", 1, 2
        )
        self.assertEqual(len(exhausted["recommendations"]), 1)
        widened = self.agent.respond(
            "exhausted", "I don't have an additional preference for other.", 2, 2
        )
        self.assertEqual(len(widened["recommendations"]), 2)
        self.assertEqual(self.agent.respond("exhausted", "anything", 3, 0)["recommendations"], [])

    def test_sessions_override_and_exhaustion_are_isolated(self) -> None:
        self.agent.reset("first", {})
        self.agent.reset("second", {})
        self.agent.respond("first", "I'm looking for Shirts T-Shirts. cotton", 1, 1)
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

    def test_override_preserves_unrelated_constraints_and_repeats_without_duplicates(self) -> None:
        self.agent.reset("override", {})
        self.agent.respond("override", "I'm looking for Shirts T-Shirts. Pull On closure", 1, 2)
        self.agent.respond("override", "For that, what matters is: cotton; imported.", 2, 2)
        response = self.agent.respond(
            "override", "Actually, ignore my earlier preference. What I need is: leather.", 3, 2
        )
        state = self.agent._sessions["override"]
        self.assertEqual(state.constraints, ["cotton", "imported", "leather"])
        self.assertEqual(state.replaceable_preference, "leather")
        self.assertNotIn("Pull On closure", state.constraints)
        self.assertIsInstance(response["recommendations"], list)
        self.agent.respond(
            "override", "Actually, ignore my earlier preference. What I need is: nylon.", 4, 2
        )
        self.assertEqual(self.agent._sessions["override"].constraints, ["cotton", "imported", "nylon"])
        self.agent.respond(
            "override", "Actually, ignore my earlier preference. What I need is: cotton.", 5, 2
        )
        self.assertEqual(self.agent._sessions["override"].constraints, ["cotton", "imported"])
        self.assertIsNone(self.agent._sessions["override"].replaceable_preference)
        self.agent.respond(
            "override", "Actually, ignore my earlier preference. What I need is: wool.", 6, 2
        )
        self.assertEqual(self.agent._sessions["override"].constraints, ["cotton", "imported", "wool"])
        self.assertEqual(self.agent._sessions["override"].replaceable_preference, "wool")

    def test_override_without_prior_preference_adds_once(self) -> None:
        self.agent.reset("no-prior", {})
        self.agent.respond("no-prior", "I'm looking for Shirts T-Shirts, but I'm still exploring.", 1, 1)
        self.agent.respond(
            "no-prior", "Actually, ignore my earlier preference. What I need is: cotton.", 2, 1
        )
        self.agent.respond(
            "no-prior", "Actually, ignore my earlier preference. What I need is: cotton.", 3, 1
        )
        self.assertEqual(self.agent._sessions["no-prior"].constraints, ["cotton"])

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
        self.assertEqual(exhausted["recommendations"][0], initial["recommendations"][0])
        self.assertEqual(len(exhausted["recommendations"]), 2)


if __name__ == "__main__":
    unittest.main()
