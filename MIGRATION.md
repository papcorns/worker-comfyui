# Migration Guide: RunPod to Google Cloud Run

This document outlines the changes made to migrate the ComfyUI worker from RunPod to Google Cloud Run with L4 GPU support.

## Summary of Changes

### 1. Architecture Changes
- **From**: RunPod serverless framework
- **To**: Google Cloud Run with Functions Framework
- **GPU**: L4 GPU support with CUDA 12.2

### 2. Code Changes

#### New Files Created:
- `main.py` - Cloud Run entrypoint with Functions Framework
- `service.py` - Refactored service layer (removed RunPod dependencies)
- `cloudbuild.yaml` - Cloud Build configuration
- `deploy.sh` - Deployment script
- `.github/workflows/deploy-cloud-run.yml` - GitHub Actions workflow
- `test_local.py` - Local testing script

#### Modified Files:
- `requirements.txt` - Replaced `runpod` with `functions-framework` and `flask`
- `Dockerfile` - Updated to use Cloud Run GPU base image
- `README.md` - Updated documentation for Cloud Run deployment

### 3. API Changes

#### Endpoints:
- **Old**: `/run`, `/runsync`, `/health` (RunPod standard)
- **New**: `/predict`, `/healthz`, `/`, `/models` (Cloud Run compatible)

#### Request Format:
```json
// Old (RunPod)
{
  "input": {
    "workflow": {...},
    "images": [...]
  }
}

// New (Cloud Run)
{
  "workflow": {...},
  "images": [...]
}
```

#### Response Format:
```json
// Old (RunPod)
{
  "id": "uuid",
  "status": "COMPLETED",
  "output": {
    "images": [...]
  }
}

// New (Cloud Run)
{
  "status": "success",
  "prompt_id": "uuid",
  "images": [...],
  "outputs": {...}
}
```

### 4. Deployment Changes

#### Infrastructure:
- **From**: RunPod pods/templates
- **To**: Google Cloud Run services with L4 GPU

#### Build Process:
- **From**: Docker Hub images
- **To**: Google Artifact Registry with Cloud Build

#### Configuration:
- **From**: RunPod environment variables
- **To**: Cloud Run environment variables

## Migration Steps

### Prerequisites
1. Google Cloud Project with billing enabled
2. Required APIs enabled (Cloud Run, Artifact Registry, Compute)
3. L4 GPU quota in desired region
4. Artifact Registry repository created

### Step-by-Step Migration

1. **Update Code**:
   ```bash
   # All code changes are already implemented in this repository
   git pull origin main
   ```

2. **Build and Push Image**:
   ```bash
   # Set your project variables
   export PROJECT_ID="your-project-id"
   export REGION="us-central1"
   
   # Build image
   docker build \
     --build-arg MODEL_TYPE=flux1-dev-fp8 \
     -t $REGION-docker.pkg.dev/$PROJECT_ID/comfyui/comfyui:latest \
     .
   
   # Push to Artifact Registry
   docker push $REGION-docker.pkg.dev/$PROJECT_ID/comfyui/comfyui:latest
   ```

3. **Deploy to Cloud Run**:
   ```bash
   # Use the deployment script
   chmod +x deploy.sh
   ./deploy.sh $PROJECT_ID $REGION latest
   ```

4. **Test Deployment**:
   ```bash
   # Get service URL
   SERVICE_URL=$(gcloud run services describe comfyui --region=$REGION --format="value(status.url)")
   
   # Test endpoints
   curl $SERVICE_URL/healthz
   python test_local.py --url $SERVICE_URL --skip-predict
   ```

### Client Code Updates

If you have existing client code that calls the RunPod API, you'll need to update it:

```python
# Old RunPod client code
import requests

response = requests.post(
    f"https://api.runpod.ai/v2/{endpoint_id}/runsync",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"input": {"workflow": workflow_data}}
)

# New Cloud Run client code
response = requests.post(
    f"{service_url}/predict",
    json={"workflow": workflow_data}
)
```

## Cost Considerations

### RunPod vs Cloud Run Costs:
- **RunPod**: Pay per second of GPU usage
- **Cloud Run**: Pay for CPU/memory/GPU time + cold start overhead

### Optimization Tips:
1. Set `min-instances=1` to avoid cold starts (increases cost)
2. Use `min-instances=0` to minimize idle costs (increases latency)
3. Monitor usage with Cloud Monitoring
4. Consider regional deployment for lower latency

## Troubleshooting

### Common Issues:

1. **GPU Quota Exceeded**:
   ```bash
   # Request quota increase
   gcloud compute project-info describe --project=$PROJECT_ID
   ```

2. **Image Build Timeout**:
   ```bash
   # Increase timeout in cloudbuild.yaml
   timeout: '3600s'  # 1 hour
   ```

3. **Cold Start Timeout**:
   ```bash
   # Increase Cloud Run timeout
   --timeout=900  # 15 minutes
   ```

4. **Memory Issues**:
   ```bash
   # Increase memory allocation
   --memory=32Gi
   ```

## Rollback Plan

If you need to rollback to RunPod:

1. Keep your original RunPod deployment running during migration
2. Update DNS/load balancer to point back to RunPod
3. The original `handler.py` file is preserved for reference

## Support

For issues specific to this migration:
1. Check Cloud Run logs: `gcloud run logs tail comfyui --region=$REGION`
2. Monitor Cloud Run metrics in Google Cloud Console
3. Test locally using `python main.py --test`
