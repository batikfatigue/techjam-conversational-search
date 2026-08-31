"""Bounded, offline Gemini enrichment with a validated local cache.

The module deliberately uses urllib instead of a vendor SDK.  The transport and
clock are injectable so all policy can be tested without making network calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


SCHEMA_VERSION = "semantic-enrichment-v1"
PROMPT_VERSION = "minimized-product-tags-v1"
ALLOWED_GROUPS = frozenset({"material", "color", "style", "use_case", "feature", "fit", "budget", "brand"})
MAX_TAGS_PER_GROUP = 8
MAX_TAG_LENGTH = 80
MAX_BATCH = 8
MAX_REQUESTS_RUN = 10
MAX_REQUESTS_DAY = 20
MIN_INTERVAL_SECONDS = 30.0
MAX_PROMPT_CHARS = 6000
MAX_OUTPUT_TOKENS = 512
MAX_TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 1
ERRORS = frozenset({"authentication", "quota", "timeout", "server", "malformed", "transport", "budget", "cache"})
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|co|edu|gov)\b(?:/\S*)?", re.I)


class Transport(Protocol):
    def __call__(self, payload: bytes, *, model: str, api_key: str, timeout: float) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class EnrichmentConfig:
    model: str = "gemini-3.1-flash-lite"
    batch_size: int = MAX_BATCH
    max_requests_run: int = MAX_REQUESTS_RUN
    max_requests_day: int = MAX_REQUESTS_DAY
    min_interval_seconds: float = MIN_INTERVAL_SECONDS
    max_prompt_chars: int = MAX_PROMPT_CHARS
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    timeout_seconds: float = MAX_TIMEOUT_SECONDS
    max_retries: int = MAX_RETRIES
    schema_version: str = SCHEMA_VERSION
    prompt_version: str = PROMPT_VERSION
    catalog_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "batch_size", max(1, min(MAX_BATCH, int(self.batch_size))))
        object.__setattr__(self, "max_requests_run", max(0, min(MAX_REQUESTS_RUN, int(self.max_requests_run))))
        object.__setattr__(self, "max_requests_day", max(0, min(MAX_REQUESTS_DAY, int(self.max_requests_day))))
        object.__setattr__(self, "min_interval_seconds", max(MIN_INTERVAL_SECONDS, float(self.min_interval_seconds)))
        object.__setattr__(self, "max_prompt_chars", max(1, min(MAX_PROMPT_CHARS, int(self.max_prompt_chars))))
        object.__setattr__(self, "max_output_tokens", max(1, min(MAX_OUTPUT_TOKENS, int(self.max_output_tokens))))
        object.__setattr__(self, "timeout_seconds", max(0.1, min(MAX_TIMEOUT_SECONDS, float(self.timeout_seconds))))
        object.__setattr__(self, "max_retries", max(0, min(MAX_RETRIES, int(self.max_retries))))


def _norm(value: object) -> str:
    return " ".join(str(value or "").lower().split())


def _truncate(value: object, limit: int) -> str:
    return _norm(value)[:limit].rstrip()


def project_product(product: Mapping[str, Any], index: int) -> dict[str, Any]:
    """Return the only product data permitted in an enrichment request."""
    identifier = _norm(product.get("parent_asin"))

    def safe(value: object, limit: int) -> str:
        projected = _truncate(value, limit)
        projected = projected.replace(identifier, "[identifier]") if identifier else projected
        return URL_RE.sub("[url]", projected)

    features = product.get("features")
    if isinstance(features, list):
        features = features[:3]
    else:
        features = [] if features in (None, "") else [features]
    details = product.get("details")
    if isinstance(details, dict):
        details = list(details.values())[:4]
    else:
        details = [] if details in (None, "") else [details]
    categories = product.get("categories")
    if not isinstance(categories, list):
        categories = [] if categories in (None, "") else [categories]
    return {
        "item_index": int(index),
        "title": safe(product.get("title"), 240),
        "categories": [safe(v, 100) for v in categories],
        "features": [safe(v, 180) for v in features],
        "details": [safe(v, 120) for v in details],
    }


def product_fingerprint(product: Mapping[str, Any]) -> str:
    payload = json.dumps(project_product(product, 0), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def catalog_digest(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_fingerprint(product: Mapping[str, Any], config: EnrichmentConfig) -> str:
    payload = {
        "schema": config.schema_version,
        "model": config.model,
        "prompt": config.prompt_version,
        "catalog": config.catalog_digest,
        "product": product_fingerprint(product),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_request(products: list[Mapping[str, Any]], config: EnrichmentConfig) -> bytes:
    items = [project_product(product, index) for index, product in enumerate(products)]
    prompt = json.dumps({"items": items, "allowed_groups": sorted(ALLOWED_GROUPS),
                         "max_tags_per_group": MAX_TAGS_PER_GROUP,
                         "max_tag_length": MAX_TAG_LENGTH}, ensure_ascii=True, separators=(",", ":"))
    tag_properties = {
        group: {
            "type": "array", "maxItems": MAX_TAGS_PER_GROUP,
            "items": {"type": "string", "maxLength": MAX_TAG_LENGTH},
        }
        for group in sorted(ALLOWED_GROUPS)
    }
    body = {
        "contents": [{"parts": [{"text": "Return JSON only with semantic tags. " + prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": config.max_output_tokens,
                             "responseMimeType": "application/json",
                             "responseSchema": {
                                 "type": "array", "minItems": 1, "maxItems": len(items),
                                 "items": {
                                     "type": "object", "required": ["item_index"],
                                     "additionalProperties": False,
                                     "properties": {
                                         "item_index": {"type": "integer", "minimum": 0, "maximum": max(0, len(items) - 1)},
                                         **tag_properties,
                                     },
                                 },
                             }},
    }
    encoded = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()
    if len(encoded) > config.max_prompt_chars:
        raise ValueError("minimized enrichment request exceeds prompt limit")
    return encoded


def validate_tags(payload: object, item_count: int) -> dict[int, dict[str, tuple[str, ...]]]:
    """Strictly validate provider output; any malformed item invalidates the response."""
    if isinstance(payload, dict):
        payload = payload.get("items")
    if not isinstance(payload, list):
        return {}
    result: dict[int, dict[str, tuple[str, ...]]] = {}
    for item in payload:
        if not isinstance(item, dict) or set(item) - {"item_index", *ALLOWED_GROUPS}:
            return {}
        index = item.get("item_index")
        if not isinstance(index, int) or not 0 <= index < item_count or index in result:
            return {}
        groups: dict[str, tuple[str, ...]] = {}
        for group, values in item.items():
            if group == "item_index":
                continue
            if not isinstance(values, list) or len(values) > MAX_TAGS_PER_GROUP:
                return {}
            tags = []
            for value in values:
                if not isinstance(value, str) or not value or len(value) > MAX_TAG_LENGTH:
                    return {}
                normalized = _norm(value)
                if normalized != value.lower().strip() or any(ord(c) < 32 for c in value):
                    return {}
                tags.append(normalized)
            groups[group] = tuple(dict.fromkeys(tags))
        result[index] = groups
    return result


class GeminiHTTPTransport:
    def __call__(self, payload: bytes, *, model: str, api_key: str, timeout: float) -> Mapping[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        request = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def extract_provider_payload(response: Mapping[str, Any]) -> object:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    content = candidates[0].get("content", {})
    parts = content.get("parts", []) if isinstance(content, dict) else []
    text = parts[0].get("text") if parts and isinstance(parts[0], dict) else None
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


@dataclass
class BuildClock:
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep


@dataclass
class BuildResult:
    entries: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    attempted_requests: int = 0
    successful_requests: int = 0
    retries: int = 0
    stop_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    errors: list[str] = field(default_factory=list)
    request_timestamps: list[float] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    enriched_products: int = 0
    skipped_products: int = 0
    latency_ms_total: float = 0.0
    latency_ms_max: float = 0.0


def load_cache(path: str | Path, products: Mapping[str, Mapping[str, Any]], config: EnrichmentConfig) -> dict[str, dict[str, tuple[str, ...]]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        if (data.get("schema") != config.schema_version or data.get("model") != config.model
                or data.get("prompt") != config.prompt_version or data.get("catalog", "") != config.catalog_digest):
            return {}
        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            return {}
        valid: dict[str, dict[str, tuple[str, ...]]] = {}
        fingerprints = {cache_fingerprint(product, config) for product in products.values()}
        for key, value in entries.items():
            if key in fingerprints and isinstance(value, dict):
                checked = validate_tags([{"item_index": 0, **value}], 1)
                if checked:
                    valid[key] = checked[0]
        return valid
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_cache(path: str | Path, entries: Mapping[str, Mapping[str, tuple[str, ...]]], config: EnrichmentConfig, metadata: Mapping[str, Any] | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": config.schema_version, "model": config.model, "prompt": config.prompt_version,
            "catalog": config.catalog_digest, "entries": entries, "manifest": dict(metadata or {})}
    lock = target.with_suffix(target.suffix + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
    except FileExistsError as exc:
        raise RuntimeError("cache lock unavailable") from exc
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True, separators=(",", ":"))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
        lock.unlink(missing_ok=True)


class EnrichmentBuilder:
    def __init__(self, api_key: str, config: EnrichmentConfig | None = None, transport: Transport | None = None, clock: BuildClock | None = None) -> None:
        if not api_key:
            raise ValueError("an API key is required for build mode")
        self.api_key = api_key
        self.config = config or EnrichmentConfig()
        self.transport = transport or GeminiHTTPTransport()
        self.clock = clock or BuildClock()

    def build(self, products: list[Mapping[str, Any]], existing: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None, request_timestamps: list[float] | None = None, checkpoint: Callable[[BuildResult], None] | None = None) -> BuildResult:
        result = BuildResult(entries=dict(existing or {}))
        prior = [float(value) for value in (request_timestamps or []) if self.clock.now() - float(value) < 86400]
        result.request_timestamps.extend(prior)
        last_request = max(prior, default=-float("inf"))
        pending = [product for product in products if cache_fingerprint(product, self.config) not in result.entries]
        result.cache_hits = len(products) - len(pending)
        result.cache_misses = len(pending)
        for start in range(0, len(pending), self.config.batch_size):
            if result.attempted_requests >= self.config.max_requests_run:
                result.stop_reason = "run_budget"; break
            if len(result.request_timestamps) >= self.config.max_requests_day:
                result.stop_reason = "day_budget"; break
            now = self.clock.now()
            if now - last_request < self.config.min_interval_seconds:
                self.clock.sleep(self.config.min_interval_seconds - (now - last_request))
            batch = pending[start:start + self.config.batch_size]
            try:
                request = build_request(batch, self.config)
            except Exception as exc:
                result.errors.append(type(exc).__name__); result.stop_reason = "request_invalid"; break
            retries = 0
            while True:
                if len(result.request_timestamps) >= self.config.max_requests_day:
                    result.stop_reason = "day_budget"
                    return result
                now = self.clock.now()
                if now - last_request < self.config.min_interval_seconds:
                    self.clock.sleep(self.config.min_interval_seconds - (now - last_request))
                result.attempted_requests += 1
                last_request = self.clock.now()
                result.request_timestamps.append(last_request)
                latency_recorded = False
                try:
                    request_started = self.clock.now()
                    response = self.transport(request, model=self.config.model, api_key=self.api_key, timeout=self.config.timeout_seconds)
                    latency_ms = max(0.0, (self.clock.now() - request_started) * 1000.0)
                    result.latency_ms_total += latency_ms
                    result.latency_ms_max = max(result.latency_ms_max, latency_ms)
                    latency_recorded = True
                    usage = response.get("usageMetadata", {}) if isinstance(response, dict) else {}
                    prompt_tokens = usage.get("promptTokenCount", 0) if isinstance(usage, dict) else 0
                    completion_tokens = usage.get("candidatesTokenCount", 0) if isinstance(usage, dict) else 0
                    total_tokens = usage.get("totalTokenCount", prompt_tokens + completion_tokens) if isinstance(usage, dict) else 0
                    if (not isinstance(prompt_tokens, int) or prompt_tokens < 0
                            or not isinstance(completion_tokens, int) or completion_tokens < 0
                            or not isinstance(total_tokens, int) or total_tokens < 0):
                        raise ValueError("invalid_usage")
                    result.prompt_tokens += prompt_tokens
                    result.completion_tokens += completion_tokens
                    result.total_tokens += total_tokens
                    tags = validate_tags(extract_provider_payload(response), len(batch))
                    if not tags:
                        raise ValueError("invalid_response")
                    for index, value in tags.items():
                        result.entries[cache_fingerprint(batch[index], self.config)] = value
                    result.successful_requests += 1
                    result.enriched_products += len(tags)
                    if checkpoint is not None:
                        try:
                            checkpoint(result)
                        except Exception:
                            result.errors.append("cache")
                            result.stop_reason = "cache_unavailable"
                            result.skipped_products = max(0, result.cache_misses - result.enriched_products)
                            return result
                    break
                except Exception as exc:
                    if not latency_recorded:
                        latency_ms = max(0.0, (self.clock.now() - request_started) * 1000.0)
                        result.latency_ms_total += latency_ms
                        result.latency_ms_max = max(result.latency_ms_max, latency_ms)
                    status = getattr(exc, "code", None)
                    if status in (401, 403): error = "authentication"
                    elif status == 429: error = "quota"
                    elif status is not None and status >= 500: error = "server"
                    elif isinstance(exc, TimeoutError): error = "timeout"
                    elif isinstance(exc, ValueError) and str(exc) in ("invalid_response", "invalid_usage"): error = "malformed"
                    else: error = "transport"
                    result.errors.append(error)
                    if error == "authentication": result.stop_reason = error; return result
                    if error == "quota": result.stop_reason = error; return result
                    if retries >= self.config.max_retries or result.attempted_requests >= self.config.max_requests_run:
                        result.stop_reason = "request_failed"; return result
                    retries += 1; result.retries += 1
        result.skipped_products = max(0, result.cache_misses - result.enriched_products)
        return result


def build_manifest(result: BuildResult) -> dict[str, Any]:
    """Return aggregate-only, JSON-safe build accounting."""
    return {
        "attempted_requests": result.attempted_requests,
        "successful_requests": result.successful_requests,
        "failed_requests": len(result.errors),
        "retries": result.retries,
        "stop_reason": result.stop_reason,
        "errors": list(result.errors),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "request_timestamps": list(result.request_timestamps),
        "cache_hits": result.cache_hits,
        "cache_misses": result.cache_misses,
        "enriched_products": result.enriched_products,
        "skipped_products": max(result.skipped_products, result.cache_misses - result.enriched_products),
        "latency_ms_total": result.latency_ms_total,
        "latency_ms_max": result.latency_ms_max,
        "budget_stop": result.stop_reason in ("run_budget", "day_budget"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build bounded offline Gemini semantic tags")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    args = parser.parse_args()
    key = os.environ.get(args.api_key_env, "")
    if not key:
        parser.error(f"{args.api_key_env} is required for build mode")
    products = [json.loads(line) for line in Path(args.catalog).open(encoding="utf-8") if line.strip()]
    config = EnrichmentConfig(catalog_digest=catalog_digest(args.catalog))
    old = {}
    timestamps = []
    if Path(args.cache).exists():
        old = load_cache(args.cache, {str(i): p for i, p in enumerate(products)}, config)
        try:
            prior = json.loads(Path(args.cache).read_text(encoding="utf-8")).get("manifest", {})
            timestamps = prior.get("request_timestamps", []) if isinstance(prior, dict) else []
        except (OSError, ValueError, TypeError):
            timestamps = []
    def checkpoint(result: BuildResult) -> None:
        save_cache(args.cache, result.entries, config, build_manifest(result))

    result = EnrichmentBuilder(key, config=config).build(products, old, timestamps, checkpoint)
    save_cache(args.cache, result.entries, config, build_manifest(result))
    print(json.dumps({"attempted_requests": result.attempted_requests, "successful_requests": result.successful_requests, "stop_reason": result.stop_reason, "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens, "total_tokens": result.total_tokens}))


if __name__ == "__main__":
    main()
