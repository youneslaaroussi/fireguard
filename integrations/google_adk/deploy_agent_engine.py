"""
Deploy the FireGuard ADK agent to Vertex AI Agent Engine.

Agent Engine is the managed runtime for ADK agents within Google Cloud Agent Builder.
Running this script registers the agent and returns a resource name you can reference
in your Devpost submission as proof of Agent Builder deployment.

Usage:
    pip install google-cloud-aiplatform[agent_engines]>=1.93.0
    python deploy_agent_engine.py

Required env vars (set in fireguard_agent/.env or your shell):
    GOOGLE_CLOUD_PROJECT      e.g. my-gcp-project
    GOOGLE_CLOUD_LOCATION     e.g. global or us-central1
    FIREGUARD_API_BASE_URL    e.g. https://fireguard-api-dovhkdlznq-uc.a.run.app
    FIREGUARD_ELASTIC_MCP_URL optional streamable HTTP Elastic MCP endpoint
    AGENT_ENGINE_BUCKET       e.g. gs://my-gcp-project-agent-engine  (staging bucket, must exist)
    AGENT_ENGINE_RESOURCE     optional existing reasoningEngine resource to update
    AGENT_ENGINE_SERVICE_ACCOUNT optional runtime service account
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / "fireguard_agent" / ".env")
AGENT_PACKAGE_DIR = Path(__file__).parent / "fireguard_agent"

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get("AGENT_ENGINE_BUCKET")

if not PROJECT:
    sys.exit("ERROR: GOOGLE_CLOUD_PROJECT is not set.")
if not STAGING_BUCKET:
    sys.exit(
        "ERROR: AGENT_ENGINE_BUCKET is not set.\n"
        "Create a GCS bucket and set AGENT_ENGINE_BUCKET=gs://<bucket-name>"
    )

import vertexai
from vertexai import agent_engines
from vertexai.agent_engines import AdkApp

from fireguard_agent import root_agent

print(f"Initialising Vertex AI  project={PROJECT}  location={LOCATION}")
vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=STAGING_BUCKET)

print("Wrapping root_agent in AdkApp...")
app = AdkApp(agent=root_agent, enable_tracing=False)

deploy_kwargs = {
    "requirements": [
        "google-adk>=1.11.0",
        "python-dotenv>=1.0.0",
    ],
    "extra_packages": [str(AGENT_PACKAGE_DIR)],
    "env_vars": {
        "GOOGLE_GENAI_USE_VERTEXAI": os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "1"),
        "FIREGUARD_AGENT_MODEL_LOCATION": os.environ.get(
            "FIREGUARD_AGENT_MODEL_LOCATION", "global"
        ),
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
        "FIREGUARD_API_BASE_URL": os.environ.get(
            "FIREGUARD_API_BASE_URL", "https://fireguard-api-dovhkdlznq-uc.a.run.app"
        ),
    },
    "display_name": "FireGuard Evacuation Coordinator",
    "description": (
        "AI-powered wildfire evacuation coordinator. "
        "Uses Gemini to orchestrate multi-step planning across Elastic-backed "
        "operational memory, deterministic route/risk services, and human approval gates."
    ),
}

if os.environ.get("AGENT_ENGINE_SERVICE_ACCOUNT"):
    deploy_kwargs["service_account"] = os.environ["AGENT_ENGINE_SERVICE_ACCOUNT"]

for key in (
    "FIREGUARD_ELASTIC_MCP_URL",
    "FIREGUARD_ELASTIC_MCP_AUTH",
    "FIREGUARD_ELASTIC_MCP_ID_TOKEN_AUDIENCE",
    "FIREGUARD_ELASTIC_MCP_REQUIRED",
    "FIREGUARD_ELASTIC_MCP_TOOLS",
):
    if os.environ.get(key):
        deploy_kwargs["env_vars"][key] = os.environ[key]

resource_name = os.environ.get("AGENT_ENGINE_RESOURCE")
if resource_name:
    print(f"Updating Vertex AI Agent Engine {resource_name} (this takes a few minutes)...")
    remote_app = agent_engines.update(
        resource_name=resource_name,
        agent_engine=app,
        **deploy_kwargs,
    )
else:
    print("Deploying to Vertex AI Agent Engine (this takes a few minutes)...")
    remote_app = agent_engines.create(app, **deploy_kwargs)

print("\nDeployment complete.")
print(f"  Resource name : {remote_app.resource_name}")
print(f"  Display name  : FireGuard Evacuation Coordinator")
print(
    f"\nView in Cloud Console:\n"
    f"  https://console.cloud.google.com/vertex-ai/agents?project={PROJECT}"
)
print("\nSave the resource name above — add it to your Devpost submission write-up.")
