from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from app.config import Settings

_tracer: Any | None = None
_provider: Any | None = None
_last_error: str | None = None
_disabled_after_error = False
_arize_ax_tracer: Any | None = None
_arize_ax_provider: Any | None = None
_arize_ax_last_error: str | None = None
_arize_ax_disabled_after_error = False


def phoenix_package_installed() -> bool:
    return importlib.util.find_spec("phoenix.otel") is not None


def phoenix_status(settings: Settings) -> dict[str, Any]:
    endpoint = _collector_endpoint(settings)
    auth_enabled = _auth_enabled(settings, endpoint)
    connection_check = _connection_check(settings, endpoint, auth_enabled)
    return {
        "enabled": settings.phoenix_tracing_enabled,
        "package_installed": phoenix_package_installed(),
        "endpoint": endpoint,
        "application_url": _application_url(endpoint),
        "project": settings.phoenix_project_name,
        "deployment": _deployment_kind(endpoint),
        "storage_backend": settings.phoenix_storage_backend,
        "cloud_space_configured": bool(settings.phoenix_cloud_space_name),
        "auth_enabled": auth_enabled,
        "api_key_configured": bool(settings.phoenix_api_key),
        "connection_check": connection_check,
        "configuration_hint": _configuration_hint(settings, endpoint, connection_check),
        "arize_ax": arize_ax_status(settings),
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
        use_auth = _auth_enabled(settings, endpoint)
        if use_auth:
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
            api_key=settings.phoenix_api_key if use_auth else None,
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


def _connection_check(settings: Settings, endpoint: str, auth_enabled: bool) -> dict[str, Any]:
    if not settings.phoenix_tracing_enabled:
        return {"status": "skipped", "reason": "Phoenix tracing is disabled."}
    base_url = _application_url(endpoint)
    headers = {}
    if auth_enabled and settings.phoenix_api_key:
        headers["Authorization"] = f"Bearer {settings.phoenix_api_key}"
    try:
        request = urllib.request.Request(f"{base_url}/v1/projects", headers=headers)
        with urllib.request.urlopen(request, timeout=settings.phoenix_status_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        projects = [item.get("name") for item in payload.get("data", []) if item.get("name")]
        return {"status": "ok", "http_status": 200, "projects": projects[:10]}
    except urllib.error.HTTPError as exc:
        return {"status": "failed", "http_status": exc.code, "error": "Phoenix REST check failed."}
    except Exception as exc:  # pragma: no cover - network/provider dependent
        return {"status": "failed", "error": str(exc)}


def _collector_endpoint(settings: Settings) -> str:
    endpoint = settings.phoenix_collector_endpoint.rstrip("/")
    if settings.phoenix_cloud_space_name and endpoint in {"https://app.phoenix.arize.com", "https://app.phoenix.arize.com/v1/traces"}:
        space = settings.phoenix_cloud_space_name.strip().strip("/")
        return f"https://app.phoenix.arize.com/s/{space}/v1/traces"
    if endpoint == "https://app.phoenix.arize.com":
        return f"{endpoint}/v1/traces"
    if endpoint.startswith("https://app.phoenix.arize.com") and not endpoint.endswith("/v1/traces"):
        return f"{endpoint}/v1/traces"
    return endpoint


def _application_url(endpoint: str) -> str:
    return endpoint.removesuffix("/v1/traces").rstrip("/")


def _deployment_kind(endpoint: str) -> str:
    if _is_local_endpoint(endpoint):
        return "local"
    if _is_phoenix_cloud_endpoint(endpoint):
        return "phoenix_cloud"
    return "self_hosted"


def _auth_enabled(settings: Settings, endpoint: str) -> bool:
    if not settings.phoenix_api_key:
        return False
    if _is_local_endpoint(endpoint):
        return False
    if _is_phoenix_cloud_endpoint(endpoint):
        return True
    return settings.phoenix_auth_enabled


def _is_phoenix_cloud_endpoint(endpoint: str) -> bool:
    return endpoint.startswith("https://app.phoenix.arize.com")


def _is_local_endpoint(endpoint: str) -> bool:
    return "localhost" in endpoint or "127.0.0.1" in endpoint


def _configuration_hint(settings: Settings, endpoint: str, connection_check: dict[str, Any]) -> str | None:
    if not _is_phoenix_cloud_endpoint(endpoint):
        return None
    if not settings.phoenix_api_key:
        return "Set PHOENIX_API_KEY before using Phoenix Cloud."
    if connection_check.get("http_status") == 401:
        return "Phoenix Cloud returned 401. Provide a valid Phoenix Cloud API key and, if your account uses spaces, set PHOENIX_CLOUD_SPACE_NAME or a space-specific PHOENIX_COLLECTOR_ENDPOINT."
    return None


def arize_ax_status(settings: Settings) -> dict[str, Any]:
    configured = bool(settings.arize_space_id and settings.arize_api_key)
    return {
        "enabled": settings.arize_ax_tracing_enabled,
        "configured": configured,
        "endpoint": settings.arize_collector_endpoint,
        "project": settings.arize_project_name,
        "space_id_configured": bool(settings.arize_space_id),
        "api_key_configured": bool(settings.arize_api_key),
        "connection_check": _arize_ax_connection_check(settings) if configured else {"status": "skipped", "reason": "ARIZE_SPACE_ID and ARIZE_API_KEY are not configured."},
        "last_error": _arize_ax_last_error,
        "disabled_after_error": _arize_ax_disabled_after_error,
    }


def _arize_ax_connection_check(settings: Settings) -> dict[str, Any]:
    try:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

        payload = ExportTraceServiceRequest().SerializeToString()
        request = urllib.request.Request(
            settings.arize_collector_endpoint,
            data=payload,
            headers={
                "Content-Type": "application/x-protobuf",
                "space_id": settings.arize_space_id or "",
                "api_key": settings.arize_api_key or "",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=settings.phoenix_status_timeout_seconds) as response:
            response.read()
            return {"status": "ok", "http_status": response.status}
    except urllib.error.HTTPError as exc:
        return {"status": "failed", "http_status": exc.code, "error": "Arize AX OTLP check failed."}
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return {"status": "failed", "error": str(exc)[:300]}


def _get_arize_ax_tracer(settings: Settings) -> Any | None:
    global _arize_ax_disabled_after_error, _arize_ax_last_error, _arize_ax_provider, _arize_ax_tracer
    if not settings.arize_ax_tracing_enabled or not settings.arize_space_id or not settings.arize_api_key:
        return None
    if _arize_ax_disabled_after_error:
        return None
    if _arize_ax_tracer is not None:
        return _arize_ax_tracer
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        resource = Resource.create({
            "service.name": "fireguard-api",
            "model_id": settings.arize_project_name,
            "project.name": settings.arize_project_name,
        })
        exporter = OTLPSpanExporter(
            endpoint=settings.arize_collector_endpoint,
            headers={
                "space_id": settings.arize_space_id,
                "api_key": settings.arize_api_key,
            },
        )
        _arize_ax_provider = TracerProvider(resource=resource)
        _arize_ax_provider.add_span_processor(SimpleSpanProcessor(exporter))
        _arize_ax_tracer = _arize_ax_provider.get_tracer("fireguard-arize-ax")
        _arize_ax_last_error = None
        return _arize_ax_tracer
    except Exception as exc:  # pragma: no cover - optional provider path
        _arize_ax_last_error = str(exc)
        _arize_ax_disabled_after_error = True
        return None


def trace_arize_ax_span(
    settings: Settings,
    incident_id: str,
    event_id: str,
    step: str,
    tool: str,
    inputs: dict[str, Any],
    output: Any,
    evidence_ids: list[str],
    assumption_ids: list[str] | None = None,
) -> str | None:
    global _arize_ax_disabled_after_error, _arize_ax_last_error
    tracer = _get_arize_ax_tracer(settings)
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
            span.set_attribute("fireguard.assumption_ids", json.dumps(assumption_ids or []))
            span.set_attribute("fireguard.inputs", json.dumps(inputs, default=str)[:4000])
            span.set_attribute("fireguard.output_type", type(output).__name__)
            span.set_attribute("openinference.span.kind", "TOOL")
            span.set_attribute("model_id", settings.arize_project_name)
            span_context = trace_api.get_current_span().get_span_context()
            if span_context.is_valid:
                return f"{span_context.trace_id:032x}:{span_context.span_id:016x}"
    except Exception as exc:  # pragma: no cover - exporter/runtime dependent
        _arize_ax_last_error = str(exc)
        _arize_ax_disabled_after_error = True
    return None


def trace_tool_span(
    settings: Settings,
    incident_id: str,
    event_id: str,
    step: str,
    tool: str,
    inputs: dict[str, Any],
    output: Any,
    evidence_ids: list[str],
    assumption_ids: list[str] | None = None,
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
            span.set_attribute("fireguard.assumption_ids", json.dumps(assumption_ids or []))
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


def annotate_trace_eval(settings: Settings, phoenix_trace_id: str | None, result: dict[str, Any]) -> dict[str, Any] | None:
    if not phoenix_trace_id:
        return None
    trace_id = phoenix_trace_id.split(":", 1)[0]
    endpoint = _collector_endpoint(settings)
    auth_enabled = _auth_enabled(settings, endpoint)
    base_url = _application_url(endpoint)
    headers = {"Content-Type": "application/json"}
    if auth_enabled and settings.phoenix_api_key:
        headers["Authorization"] = f"Bearer {settings.phoenix_api_key}"
    payload = {
        "data": [
            {
                "trace_id": trace_id,
                "name": "fireguard_eval",
                "annotator_kind": "CODE",
                "result": {
                    "label": result.get("status"),
                    "score": result.get("score"),
                    "explanation": "Deterministic FireGuard eval checks for grounding, route safety, freshness, approval enforcement, trace completeness, and clarity.",
                },
                "metadata": {
                    "incident_id": result.get("incident_id"),
                    "eval_id": result.get("eval_id"),
                    "checks": result.get("checks", {}),
                },
                "identifier": result.get("eval_id"),
            }
        ]
    }
    last_error: str | None = None
    for attempt, delay_seconds in enumerate([0.0, 0.25, 0.5, 1.0, 2.0], start=1):
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            request = urllib.request.Request(
                f"{base_url}/v1/trace_annotations?sync=true",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=settings.phoenix_status_timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            inserted = response_payload.get("data", [])
            if inserted:
                return {"annotation_id": inserted[0].get("id"), "trace_id": trace_id, "attempt": attempt}
            return {"trace_id": trace_id, "attempt": attempt}
        except urllib.error.HTTPError as exc:  # pragma: no cover - provider/network dependent
            last_error = f"HTTP Error {exc.code}: {exc.reason}"
            if exc.code != 404:
                break
        except Exception as exc:  # pragma: no cover - provider/network dependent
            last_error = str(exc)
            break
    return {"trace_id": trace_id, "error": last_error or "annotation failed"}
