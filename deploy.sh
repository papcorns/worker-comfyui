#!/bin/bash

# Cloud Run deployment script for ComfyUI worker
# Usage: ./deploy.sh [PROJECT_ID] [REGION] [IMAGE_TAG]

set -e

# Default values
PROJECT_ID=${1:-"papcorns-internal"}
REGION=${2:-"us-central1"}
IMAGE_TAG=${3:-"latest"}
SERVICE_NAME="comfyui"
REPOSITORY="comfyui"

echo "Deploying ComfyUI to Cloud Run..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Image Tag: $IMAGE_TAG"

# Construct image URL
IMAGE_URL="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/comfyui:$IMAGE_TAG"

echo "Image URL: $IMAGE_URL"

# Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME \
  --image=$IMAGE_URL \
  --region=$REGION \
  --platform=managed \
  --gpu=1 \
  --gpu-type=l4 \
  --memory=32Gi \
  --cpu=8 \
  --allow-unauthenticated \
  --timeout=900 \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=3 \
  --set-env-vars="COMFY_LOG_LEVEL=INFO" \
  --project=$PROJECT_ID

echo "Deployment completed!"

# Get the service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)")
echo "Service URL: $SERVICE_URL"

# Test health endpoint
echo "Testing health endpoint..."
curl -f "$SERVICE_URL/healthz" || echo "Health check failed - service may still be starting up"

echo "Deployment script completed!"
