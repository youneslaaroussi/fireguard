# FireGuard Google ADK Agent

This directory is the code-first Google Agent Development Kit entrypoint for FireGuard.

The hosted FastAPI backend remains the safety and execution layer. The ADK agent uses the backend OpenAPI tool surface to observe context, retrieve Elastic-backed memory, compute deterministic risk/routes, draft a plan, request approval, and execute only approved actions.

## Run Locally

```bash
cd integrations/google_adk
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp fireguard_agent/.env.example fireguard_agent/.env
```

Edit `fireguard_agent/.env` if needed, then run:

```bash
adk run fireguard_agent
```

For the ADK dev UI:

```bash
adk web --port 8081
```

## Hosted Tool Target

By default the agent points at:

```text
https://fireguard-api-dovhkdlznq-uc.a.run.app
```

Set `FIREGUARD_API_BASE_URL` in `fireguard_agent/.env` to use a local or alternate hosted API.

## Proof Boundary

- Real: ADK `root_agent` package, Gemini/Vertex model configuration, OpenAPI toolset, and FireGuard tool endpoints.
- Real: tool calls hit the same deployed FastAPI service used by the web app.
- Guarded: public-facing actions still require backend approval state and Twilio allowlist enforcement.
- Not claimed: this is not a configured low-code Agent Builder console agent until manually registered in Google Cloud UI.
