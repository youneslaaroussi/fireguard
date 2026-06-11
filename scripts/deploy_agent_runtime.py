from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path

import google.auth
import vertexai
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class GcloudCredentials(Credentials):
    def __init__(self) -> None:
        super().__init__()
        self.expiry = _utcnow_naive()

    def refresh(self, request) -> None:  # type: ignore[no-untyped-def]
        del request
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            text=True,
        ).strip()
        self.token = token
        self.expiry = _utcnow_naive() + timedelta(minutes=45)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _credentials() -> Credentials:
    try:
        credentials, _ = google.auth.default()
        return credentials
    except DefaultCredentialsError:
        credentials = GcloudCredentials()
        credentials.refresh(None)
        return credentials


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy FireGuard to Agent Platform Runtime.")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "vidovaai"))
    parser.add_argument("--location", default=os.environ.get("AGENT_RUNTIME_LOCATION", "us-central1"))
    parser.add_argument("--model-location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))
    parser.add_argument(
        "--staging-bucket",
        default=os.environ.get("AGENT_RUNTIME_STAGING_BUCKET", "gs://vidovaai-vertex-files"),
    )
    parser.add_argument(
        "--fireguard-public-base-url",
        default=os.environ.get("FIREGUARD_PUBLIC_BASE_URL", "http://127.0.0.1:8100"),
    )
    parser.add_argument("--gemini-model", default=os.environ.get("AGENT_RUNTIME_GEMINI_MODEL", "gemini-3.1-pro-preview"))
    args = parser.parse_args()

    credentials = _credentials()
    vertexai.init(project=args.project, location=args.location, credentials=credentials)

    os.environ["GOOGLE_CLOUD_PROJECT"] = args.project
    os.environ["GOOGLE_CLOUD_LOCATION"] = args.model_location
    os.environ["AGENT_RUNTIME_LOCATION"] = args.model_location
    os.environ["AGENT_RUNTIME_GEMINI_MODEL"] = args.gemini_model
    os.environ["FIREGUARD_PUBLIC_BASE_URL"] = args.fireguard_public_base_url

    from app.agent_runtime.fireguard_agent import adk_app

    client = vertexai.Client(project=args.project, location=args.location, credentials=credentials)
    remote_agent = client.agent_engines.create(
        agent=adk_app,
        config={
            "display_name": "FireGuard Agent Platform",
            "description": "FireGuard ADK agent using Gemini and FireGuard operational tools.",
            "requirements": [
                "google-cloud-aiplatform[agent_engines,adk]==1.157.0",
                "google-adk==2.2.0",
                "cloudpickle==3.1.2",
                "pydantic==2.13.4",
                "requests==2.34.2",
            ],
            "extra_packages": ["app/agent_runtime"],
            "staging_bucket": args.staging_bucket,
            "env_vars": {
                "FIREGUARD_PUBLIC_BASE_URL": args.fireguard_public_base_url,
                "AGENT_RUNTIME_GEMINI_MODEL": args.gemini_model,
                "AGENT_RUNTIME_LOCATION": args.model_location,
                "GOOGLE_CLOUD_LOCATION": args.model_location,
                "GOOGLE_GENAI_USE_VERTEXAI": "True",
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
                "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
            },
        },
    )
    print(remote_agent)


if __name__ == "__main__":
    main()
