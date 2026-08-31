import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from starter.semantic_enrichment import (
    BuildClock, EnrichmentBuilder, EnrichmentConfig, build_request,
    GeminiHTTPTransport, build_manifest, cache_fingerprint, catalog_digest,
    load_cache, project_product, save_cache, validate_tags,
)
from starter.agent import Agent


class SemanticEnrichmentTest(unittest.TestCase):
    def product(self):
        return {"parent_asin": "SECRET", "title": "Blue SECRET cotton shirt", "categories": ["Shirts"],
                "features": ["Cotton https://example.com/private", "Soft", "Long", "Extra"],
                "details": {"closure": "Pull On", "department": "Women", "brand": "Hidden", "x": "ignored"},
                "user_profile": "never send"}

    def test_projection_is_minimized_and_never_contains_identifier(self):
        projected = project_product(self.product(), 3)
        self.assertEqual(set(projected), {"item_index", "title", "categories", "features", "details"})
        self.assertNotIn("SECRET", json.dumps(projected))
        self.assertNotIn("example.com", json.dumps(projected))
        self.assertEqual(len(projected["features"]), 3)
        self.assertEqual(len(projected["details"]), 4)

    def test_config_hard_clamps_loose_values(self):
        config = EnrichmentConfig(batch_size=99, max_requests_run=99, max_requests_day=99,
                                  min_interval_seconds=0, max_prompt_chars=99999,
                                  max_output_tokens=99999, timeout_seconds=99, max_retries=99)
        self.assertEqual((config.batch_size, config.max_requests_run, config.max_requests_day), (8, 10, 20))
        self.assertEqual((config.min_interval_seconds, config.max_prompt_chars, config.max_output_tokens, config.max_retries), (30.0, 6000, 512, 1))

    def test_validation_rejects_unknown_or_malformed_response(self):
        self.assertEqual(validate_tags([{ "item_index": 0, "unknown": ["x"] }], 1), {})
        self.assertEqual(validate_tags([{ "item_index": 4, "feature": ["x"] }], 1), {})
        self.assertEqual(validate_tags([{ "item_index": 0, "feature": ["X\n"] }], 1), {})
        self.assertEqual(validate_tags([{ "item_index": 0, "feature": ["soft"] }], 1)[0]["feature"], ("soft",))

    def test_builder_batches_retries_and_persists_cache_without_network(self):
        calls = []
        def transport(payload, **kwargs):
            calls.append((payload, kwargs))
            return {"candidates": [{"content": {"parts": [{"text": json.dumps([{"item_index": 0, "feature": ["soft"]}])}]}}],
                    "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2, "totalTokenCount": 7}}
        clock = BuildClock(now=lambda: 1000.0, sleep=lambda seconds: None)
        config = EnrichmentConfig(batch_size=1, max_requests_run=2, min_interval_seconds=30)
        result = EnrichmentBuilder("key", config, transport, clock).build([self.product()])
        self.assertEqual(result.successful_requests, 1)
        self.assertEqual(result.prompt_tokens, 4)
        self.assertEqual(result.total_tokens, 7)
        self.assertNotIn("SECRET", calls[0][0].decode())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            save_cache(path, result.entries, config)
            self.assertEqual(load_cache(path, {"x": self.product()}, config), result.entries)
            calls.clear()
            resumed = EnrichmentBuilder("key", config, transport, clock).build(
                [self.product()], load_cache(path, {"x": self.product()}, config)
            )
            self.assertEqual(calls, [])
            self.assertEqual(resumed.entries, result.entries)

    def test_cache_stale_fingerprint_and_request_envelope(self):
        config = EnrichmentConfig(catalog_digest="digest-a")
        request = json.loads(build_request([self.product()], config))
        self.assertIn("contents", request)
        self.assertEqual(request["generationConfig"]["temperature"], 0)
        self.assertEqual(request["generationConfig"]["maxOutputTokens"], 512)
        schema = request["generationConfig"]["responseSchema"]
        self.assertEqual(schema["items"]["required"], ["item_index"])
        self.assertFalse(schema["items"]["additionalProperties"])
        self.assertEqual(set(schema["items"]["properties"]), {"item_index", "material", "color", "style", "use_case", "feature", "fit", "budget", "brand"})
        self.assertLessEqual(len(json.dumps(request).encode()), 6000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            save_cache(path, {}, config)
            self.assertEqual(load_cache(path, {"x": self.product()}, EnrichmentConfig(catalog_digest="digest-b")), {})
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(load_cache(path, {"x": self.product()}, config), {})

    def test_agent_cached_mode_is_network_free_and_uses_valid_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.jsonl"
            catalog.write_text(json.dumps(self.product()) + "\n", encoding="utf-8")
            config = EnrichmentConfig(catalog_digest=catalog_digest(catalog))
            cache = root / "semantic.json"
            save_cache(cache, {cache_fingerprint(self.product(), config): {"feature": ("soft",)}}, config)
            old_mode, old_cache = os.environ.get("SHOPPING_ENRICHMENT_MODE"), os.environ.get("SHOPPING_ENRICHMENT_CACHE")
            try:
                os.environ["SHOPPING_ENRICHMENT_MODE"] = "cached"
                os.environ["SHOPPING_ENRICHMENT_CACHE"] = str(cache)
                with mock.patch("urllib.request.urlopen", side_effect=AssertionError("runtime network call")):
                    agent = Agent(catalog)
                self.assertEqual(dict(agent._semantic_tags), {"SECRET": frozenset({"soft"})})
            finally:
                if old_mode is None: os.environ.pop("SHOPPING_ENRICHMENT_MODE", None)
                else: os.environ["SHOPPING_ENRICHMENT_MODE"] = old_mode
                if old_cache is None: os.environ.pop("SHOPPING_ENRICHMENT_CACHE", None)
                else: os.environ["SHOPPING_ENRICHMENT_CACHE"] = old_cache

    @staticmethod
    def response(tags=None, usage=None):
        tags = tags if tags is not None else [{"item_index": 0, "feature": ["soft"]}]
        return {
            "candidates": [{"content": {"parts": [{"text": json.dumps(tags)}]}}],
            "usageMetadata": usage or {
                "promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 6
            },
        }

    def test_failure_circuits_are_sanitized_and_non_fatal(self):
        cases = [
            (urllib.error.HTTPError("https://redacted", 401, "secret", {}, None), "authentication"),
            (urllib.error.HTTPError("https://redacted", 403, "secret", {}, None), "authentication"),
            (urllib.error.HTTPError("https://redacted", 429, "secret", {}, None), "quota"),
        ]
        for failure, expected in cases:
            with self.subTest(expected=expected, code=failure.code):
                result = EnrichmentBuilder(
                    "key", EnrichmentConfig(max_retries=1), lambda *args, **kwargs: (_ for _ in ()).throw(failure)
                ).build([self.product()])
                self.assertEqual(result.stop_reason, expected)
                self.assertEqual(result.errors, [expected])
                self.assertEqual(result.attempted_requests, 1)
                self.assertEqual(result.entries, {})

        malformed = EnrichmentBuilder(
            "key", EnrichmentConfig(max_retries=0), lambda *args, **kwargs: {"candidates": []}
        ).build([self.product()])
        self.assertEqual(malformed.errors, ["malformed"])
        self.assertEqual(malformed.entries, {})

    def test_transient_retry_obeys_spacing_and_budget_boundaries(self):
        class Clock:
            value = 1000.0
            sleeps = []

            @classmethod
            def now(cls):
                return cls.value

            @classmethod
            def sleep(cls, seconds):
                cls.sleeps.append(seconds)
                cls.value += seconds

        for failure, error in [
            (TimeoutError(), "timeout"),
            (urllib.error.HTTPError("https://redacted", 500, "secret", {}, None), "server"),
        ]:
            with self.subTest(error=error):
                Clock.value, Clock.sleeps = 1000.0, []
                outcomes = iter([failure, self.response()])

                def transport(*args, **kwargs):
                    outcome = next(outcomes)
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome

                result = EnrichmentBuilder(
                    "key", EnrichmentConfig(max_requests_run=2), transport,
                    BuildClock(now=Clock.now, sleep=Clock.sleep),
                ).build([self.product()])
                self.assertEqual(result.attempted_requests, 2)
                self.assertEqual(result.successful_requests, 1)
                self.assertEqual(result.errors, [error])
                self.assertEqual(Clock.sleeps, [30.0])

        calls = []
        day_limited = EnrichmentBuilder(
            "key", EnrichmentConfig(), lambda *args, **kwargs: calls.append(1),
            BuildClock(now=lambda: 1000.0, sleep=lambda seconds: None),
        ).build([self.product()], request_timestamps=[999.0] * 20)
        self.assertEqual(day_limited.stop_reason, "day_budget")
        self.assertEqual(calls, [])

        calls = []
        retry_blocked = EnrichmentBuilder(
            "key", EnrichmentConfig(), lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
            BuildClock(now=lambda: 1000.0, sleep=lambda seconds: None),
        ).build([self.product()], request_timestamps=[999.0] * 19)
        self.assertEqual(retry_blocked.attempted_requests, 1)
        self.assertEqual(retry_blocked.stop_reason, "day_budget")

    def test_run_budget_and_invalid_usage_never_create_entries(self):
        products = [dict(self.product(), title=f"item {index}") for index in range(11)]
        result = EnrichmentBuilder(
            "key", EnrichmentConfig(batch_size=1), lambda *args, **kwargs: self.response(),
            BuildClock(now=lambda: 1000.0, sleep=lambda seconds: None),
        ).build(products)
        self.assertEqual(result.attempted_requests, 10)
        self.assertEqual(result.stop_reason, "run_budget")

        invalid_usage = EnrichmentBuilder(
            "key", EnrichmentConfig(max_retries=0),
            lambda *args, **kwargs: self.response(usage={"promptTokenCount": -1}),
        ).build([self.product()])
        self.assertEqual(invalid_usage.successful_requests, 0)
        self.assertEqual(invalid_usage.entries, {})
        self.assertEqual(invalid_usage.errors, ["malformed"])

    def test_transport_uses_header_auth_not_query_parameter(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b"{}"

        with mock.patch("urllib.request.urlopen", return_value=Response()) as opened:
            GeminiHTTPTransport()(b"{}", model="gemini-test", api_key="top-secret", timeout=1)
        request = opened.call_args.args[0]
        self.assertNotIn("top-secret", request.full_url)
        self.assertNotIn("?key=", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "top-secret")

    def test_resume_spacing_checkpoint_and_manifest_are_complete(self):
        class Clock:
            value = 1000.0
            sleeps = []

            @classmethod
            def now(cls): return cls.value

            @classmethod
            def sleep(cls, seconds):
                cls.sleeps.append(seconds)
                cls.value += seconds

        checkpoints = []
        outcomes = iter([self.response(), TimeoutError()])

        def transport(*args, **kwargs):
            outcome = next(outcomes)
            if isinstance(outcome, Exception): raise outcome
            return outcome

        products = [self.product(), dict(self.product(), title="second product")]
        result = EnrichmentBuilder(
            "key", EnrichmentConfig(batch_size=1, max_retries=0), transport,
            BuildClock(now=Clock.now, sleep=Clock.sleep),
        ).build(products, request_timestamps=[990.0], checkpoint=lambda state: checkpoints.append(build_manifest(state)))
        self.assertEqual(Clock.sleeps, [20.0, 30.0])
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0]["enriched_products"], 1)
        manifest = build_manifest(result)
        required = {"attempted_requests", "successful_requests", "failed_requests", "retries", "stop_reason",
                    "errors", "prompt_tokens", "completion_tokens", "total_tokens", "request_timestamps",
                    "cache_hits", "cache_misses", "enriched_products", "skipped_products",
                    "latency_ms_total", "latency_ms_max", "budget_stop"}
        self.assertEqual(set(manifest), required)
        self.assertEqual(manifest["skipped_products"], 1)


if __name__ == "__main__":
    unittest.main()
