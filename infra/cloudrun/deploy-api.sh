#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
: "${GOOGLE_CLOUD_LOCATION:=us-central1}"

IMAGE="${GOOGLE_CLOUD_LOCATION}-docker.pkg.dev/${GOOGLE_CLOUD_PROJECT}/fireguard/fireguard-api:latest"

gcloud artifacts repositories create fireguard \
  --repository-format=docker \
  --location="${GOOGLE_CLOUD_LOCATION}" \
  --project="${GOOGLE_CLOUD_PROJECT}" || true

gcloud builds submit ../.. \
  --tag "${IMAGE}" \
  --file infra/cloudrun/api.Dockerfile \
  --project "${GOOGLE_CLOUD_PROJECT}"

gcloud run deploy fireguard-api \
  --image "${IMAGE}" \
  --region "${GOOGLE_CLOUD_LOCATION}" \
  --project "${GOOGLE_CLOUD_PROJECT}" \
  --allow-unauthenticated \
  --set-env-vars APP_ENV=production,DEMO_MODE=true
