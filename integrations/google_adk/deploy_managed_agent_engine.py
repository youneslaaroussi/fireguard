"""
Deploy FireGuard's managed Vertex AI Agent Engine proof runtime.

This deployment intentionally uses a custom Agent Engine object instead of ADK
`LlmAgent` because the regional ADK runtime resolves model names against the
Agent Engine region. The custom runtime still runs on managed Vertex AI Agent
Engine, calls Vertex global Gemini 3.1, and calls the official Elastic MCP
Cloud Run service from inside the managed runtime.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get("AGENT_ENGINE_BUCKET")

if not PROJECT:
    sys.exit("ERROR: GOOGLE_CLOUD_PROJECT is not set.")
if not STAGING_BUCKET:
    sys.exit("ERROR: AGENT_ENGINE_BUCKET is not set.")

import vertexai
from google.oauth2.credentials import Credentials
from vertexai import agent_engines

from fireguard_managed_agent import FireGuardManagedAgent

print(f"Initialising Vertex AI  project={PROJECT}  location={LOCATION}")
credentials = None
gcloud_account = os.environ.get("AGENT_ENGINE_GCLOUD_AUTH_ACCOUNT", "").strip()
if gcloud_account:
    token = subprocess.check_output(
        [
            "gcloud",
            "auth",
            "print-access-token",
            f"--account={gcloud_account}",
            "--quiet",
        ],
        text=True,
    ).strip()
    credentials = Credentials(
        token=token,
        expiry=datetime.utcnow() + timedelta(minutes=50),
    )

vertexai.init(
    project=PROJECT,
    location=LOCATION,
    staging_bucket=STAGING_BUCKET,
    credentials=credentials,
)

agent = FireGuardManagedAgent()
env_vars = {
    "FIREGUARD_GOOGLE_CLOUD_PROJECT": PROJECT,
    "GOOGLE_GENAI_USE_VERTEXAI": "1",
    "FIREGUARD_AGENT_MODEL_LOCATION": os.environ.get(
        "FIREGUARD_AGENT_MODEL_LOCATION", "global"
    ),
    "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
}

for key in (
    "FIREGUARD_ELASTIC_MCP_URL",
    "FIREGUARD_ELASTIC_MCP_AUTH",
    "FIREGUARD_ELASTIC_MCP_ID_TOKEN_AUDIENCE",
    "FIREGUARD_ELASTIC_MCP_REQUIRED",
    "FIREGUARD_ELASTIC_MCP_TIMEOUT_SECONDS",
):
    if os.environ.get(key):
        env_vars[key] = os.environ[key]

deploy_kwargs = {
    "requirements": [
        "google-cloud-aiplatform>=1.150.0",
        "google-genai>=1.51.0",
        "mcp>=1.13.0",
        "google-auth>=2.0.0",
        "requests>=2.32.0",
    ],
    "extra_packages": ["fireguard_managed_agent.py"],
    "env_vars": env_vars,
    "display_name": "FireGuard Managed Gemini 3.1 MCP Agent",
    "description": (
        "Managed Vertex AI Agent Engine proof runtime for FireGuard. Calls "
        "Vertex global Gemini 3.1 and the official Elastic MCP server."
    ),
}

if os.environ.get("AGENT_ENGINE_SERVICE_ACCOUNT"):
    deploy_kwargs["service_account"] = os.environ["AGENT_ENGINE_SERVICE_ACCOUNT"]

resource_name = os.environ.get("AGENT_ENGINE_RESOURCE")
if resource_name:
    print(f"Updating Vertex AI Agent Engine {resource_name}...")
    remote_app = agent_engines.update(
        resource_name=resource_name,
        agent_engine=agent,
        **deploy_kwargs,
    )
else:
    print("Deploying new Vertex AI Agent Engine...")
    remote_app = agent_engines.create(agent, **deploy_kwargs)

print("\nDeployment complete.")
print(f"  Resource name : {remote_app.resource_name}")
