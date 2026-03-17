"""Structured logging helpers for external API calls.

Every outbound API call should use these helpers so we can see
exactly what goes in and what comes back in docker logs (stdout).

Usage:
    from app.services.api_logger import log_api_request, log_api_response

    log_api_request(logger, "fal-image", "fal-ai/instant-character", arguments)
    result = _fal.subscribe(...)
    log_api_response(logger, "fal-image", "fal-ai/instant-character", "ok", result, elapsed_ms)
"""

import json
import logging
import time
from contextlib import contextmanager
from typing import Any

# Keys whose values should be masked in logs
_SENSITIVE_KEYS = {"key", "token", "secret", "password", "authorization", "api_key"}
_MAX_VALUE_LEN = 500
_MAX_RESPONSE_LEN = 2000


def _mask_sensitive(data: Any, depth: int = 0) -> Any:
    """Recursively mask sensitive keys and truncate long values."""
    if depth > 5:
        return "..."
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if any(s in k.lower() for s in _SENSITIVE_KEYS):
                result[k] = "***MASKED***"
            else:
                result[k] = _mask_sensitive(v, depth + 1)
        return result
    if isinstance(data, list):
        return [_mask_sensitive(item, depth + 1) for item in data[:10]]
    if isinstance(data, str) and len(data) > _MAX_VALUE_LEN:
        return data[:_MAX_VALUE_LEN] + f"... ({len(data)} chars total)"
    return data


def _safe_json(data: Any, max_len: int = _MAX_RESPONSE_LEN) -> str:
    """Convert to JSON string, truncate if needed."""
    try:
        s = json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(data)
    if len(s) > max_len:
        return s[:max_len] + f"... ({len(s)} chars total)"
    return s


def log_api_request(
    logger: logging.Logger,
    service: str,
    endpoint: str,
    payload: dict | None = None,
    **extra: Any,
) -> None:
    """Log an outbound API request."""
    masked = _mask_sensitive(payload) if payload else {}
    parts = [f"[API:{service}] REQUEST {endpoint}"]
    if extra:
        parts.append(f"extras={_safe_json(extra, 500)}")
    parts.append(f"payload={_safe_json(masked)}")
    logger.info(" | ".join(parts))


def log_api_response(
    logger: logging.Logger,
    service: str,
    endpoint: str,
    status: str,
    response_data: Any = None,
    elapsed_ms: int = 0,
) -> None:
    """Log an API response."""
    parts = [f"[API:{service}] RESPONSE {endpoint}", f"status={status}", f"elapsed={elapsed_ms}ms"]
    if response_data is not None:
        parts.append(f"data={_safe_json(_mask_sensitive(response_data))}")
    logger.info(" | ".join(parts))


@contextmanager
def api_call(
    logger: logging.Logger,
    service: str,
    endpoint: str,
    payload: dict | None = None,
):
    """Context manager that logs request on entry, response on exit with timing.

    Usage:
        with api_call(logger, "fal-image", "instant-character", args) as ctx:
            result = _fal.subscribe(...)
            ctx["response"] = result
            ctx["status"] = "ok"
    """
    log_api_request(logger, service, endpoint, payload)
    ctx = {"status": "ok", "response": None}
    start = time.monotonic()
    try:
        yield ctx
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log_api_response(logger, service, endpoint, f"ERROR: {type(e).__name__}: {e}", elapsed_ms=elapsed_ms)
        raise
    else:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log_api_response(logger, service, endpoint, ctx["status"], ctx.get("response"), elapsed_ms)
