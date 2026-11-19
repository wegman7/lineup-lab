#!/usr/bin/env bash
# Deploy to Cloud Run from source (Cloud Build builds the root Dockerfile).
# Prereqs (once): gcloud auth login; gcloud config set project <id>;
#   enable run, cloudbuild, artifactregistry, secretmanager APIs;
#   printf %s "$KEY" | gcloud secrets create anthropic-api-key --data-file=-
#   and grant the Cloud Run service account roles/secretmanager.secretAccessor on it.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${REGION:-us-east1}"
test -f data/stats.duckdb || { echo "data/stats.duckdb missing: run the stats build first" >&2; exit 1; }

# max-instances=1: the PoC keeps the rate limit and daily spending cap in memory (tech spec §7).
gcloud run deploy lineup-lab \
  --source . \
  --region "$REGION" \
  --max-instances 1 \
  --memory 1Gi \
  --allow-unauthenticated \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest \
  --set-env-vars "DAILY_CAP_USD=${DAILY_CAP_USD:-5}"
