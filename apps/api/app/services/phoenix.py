from __future__ import annotations

import importlib.util
import json
import os
import urllib.error
import urllib.request
from typing import Any

from app.config import Settings

_tracer: Any | None = None
_provider: Any | None = None
_last_error: str | None = None
_disabled_after_error = False


def phoenix_package_installed() -> bool:
    return importlib.util.find_spec("phoenix.otel") is not None


def phoenix_status(settings: Settings) -> dict[str, Any]:
    endpoint = _collector_endpoint(settings)
    return {
        "enabled": settings.phoenix_tracing_enabled,
        "package_installed": phoenix_package_installed(),
        "endpoint": endpoint,
        "project": settings.phoenix_project_name,
        "hosted": bool(settings.phoenix_api_key and not _is_local_endpoint(endpoint)),
        "last_error": _last_error,
        "disabled_after_error": _disabled_after_error,
    }


def _get_tracer(settings: Settings) -> Any | None:
    global _last_error, _provider, _tracer, _disabled_after_error
    if not settings.phoenix_tracing_enabled:
        return None
    if _disabled_after_error:
        return None
    if _tracer is not None:
        return _tracer
    if not _collector_reachable(settings):
        return None
    try:
        from opentelemetry import trace as trace_api
        from phoenix.otel import register

        endpoint = _collector_endpoint(settings)
        use_hosted_auth = bool(settings.phoenix_api_key and not _is_local_endpoint(endpoint))
        if use_hosted_auth:
            # phoenix.otel also accepts api_key directly, but setting the env var keeps
            # hosted Phoenix auth behavior aligned with the package defaults.
            os.environ["PHOENIX_API_KEY"] = settings.phoenix_api_key
        else:
            os.environ.pop("PHOENIX_API_KEY", None)
        os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = endpoint
        os.environ["PHOENIX_PROJECT_NAME"] = settings.phoenix_project_name
        _provider = register(
            endpoint=endpoint,
            project_name=settings.phoenix_project_name,
            api_key=settings.phoenix_api_key if use_hosted_auth else None,
            protocol="http/protobuf" if endpoint.endswith("/v1/traces") else None,
            batch=False,
            verbose=False,
        )
        _tracer = trace_api.get_tracer("fireguard")
        _last_error = None
        return _tracer
    except Exception as exc:  # pragma: no cover - depends on optional Phoenix runtime
        _last_error = str(exc)
        _disabled_after_error = True
        return None


def _collector_reachable(settings: Settings) -> bool:
    global _last_error
    endpoint = _collector_endpoint(settings)
    if settings.phoenix_api_key:
        return True
    if "localhost" not in endpoint and "127.0.0.1" not in endpoint:
        return True
    base_url = endpoint.split("/v1/traces")[0]
    try:
        urllib.request.urlopen(base_url, timeout=0.25).close()
        return True
    except (OSError, urllib.error.URLError) as exc:
        _last_error = f"Phoenix collector not reachable at {base_url}: {exc}"
        return False


def _collector_endpoint(settings: Settings) -> str:
    endpoint = settings.phoenix_collector_endpoint.rstrip("/")
    if endpoint == "https://app.phoenix.arize.com":
        return f"{endpoint}/v1/traces"
    if endpoint.startswith("https://app.phoenix.arize.com") and not endpoint.endswith("/v1/traces"):
        return f"{endpoint}/v1/traces"
    return endpoint


def _is_local_endpoint(endpoint: str) -> bool:
    return "localhost" in endpoint or "127.0.0.1" in endpoint


def trace_tool_span(
    settings: Settings,
    incident_id: str,
    event_id: str,
    step: str,
    tool: str,
    inputs: dict[str, Any],
    output: Any,
    evidence_ids: list[str],
) -> str | None:
    global _last_error, _disabled_after_error
    tracer = _get_tracer(settings)
    if tracer is None:
        return None
    try:
        from opentelemetry import trace as trace_api

        with tracer.start_as_current_span(f"fireguard.{tool}") as span:
            span.set_attribute("fireguard.incident_id", incident_id)
            span.set_attribute("fireguard.event_id", event_id)
            span.set_attribute("fireguard.step", step)
            span.set_attribute("fireguard.tool", tool)
            span.set_attribute("fireguard.evidence_ids", json.dumps(evidence_ids))
            span.set_attribute("fireguard.inputs", json.dumps(inputs, default=str)[:4000])
            span.set_attribute("fireguard.output_type", type(output).__name__)
            span.set_attribute("openinference.span.kind", "TOOL")
            span_context = trace_api.get_current_span().get_span_context()
            if span_context.is_valid:
                return f"{span_context.trace_id:032x}:{span_context.span_id:016x}"
    except Exception as exc:  # pragma: no cover - exporter/runtime dependent
        _last_error = str(exc)
        _disabled_after_error = True
    return None
