# worker-comfyui

> [ComfyUI](https://github.com/comfyanonymous/ComfyUI) as a serverless API on [Google Cloud Run](https://cloud.google.com/run) with L4 GPU

<p align="center">
  <img src="assets/worker_sitting_in_comfy_chair.jpg" title="Worker sitting in comfy chair" />
</p>

---

This project allows you to run ComfyUI workflows as a serverless API endpoint on Google Cloud Run with L4 GPU support. Submit workflows via HTTP API calls and receive generated images as base64 strings.

## Table of Contents

- [Quickstart](#quickstart)
- [Available Docker Images](#available-docker-images)
- [API Specification](#api-specification)
- [Usage](#usage)
- [Getting the Workflow JSON](#getting-the-workflow-json)
- [Deployment](#deployment)
- [Environment Variables](#environment-variables)
- [Further Documentation](#further-documentation)

---

## Quickstart

1.  🐳 Build one of the [available Docker images](#available-docker-images) for your Cloud Run service.
2.  📄 Follow the [Deployment](#deployment) section to deploy to Google Cloud Run.
3.  ⚙️ Optionally configure the worker using environment variables.
4.  🧪 Pick an example workflow from [`test_resources/workflows/`](./test_resources/workflows/) or [get your own](#getting-the-workflow-json).
5.  🚀 Follow the [Usage](#usage) steps below to interact with your deployed endpoint.

## Available Docker Images

Build these images with different model configurations:

- **`MODEL_TYPE=base`**: Clean ComfyUI install with no models.
- **`MODEL_TYPE=flux1-schnell`**: Includes checkpoint, text encoders, and VAE for [FLUX.1 schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell).
- **`MODEL_TYPE=flux1-dev`**: Includes checkpoint, text encoders, and VAE for [FLUX.1 dev](https://huggingface.co/black-forest-labs/FLUX.1-dev).
- **`MODEL_TYPE=flux1-dev-fp8`**: Includes FP8 quantized checkpoint for [FLUX.1 dev](https://huggingface.co/Comfy-Org/flux1-dev) (default).
- **`MODEL_TYPE=sdxl`**: Includes checkpoint and VAEs for [Stable Diffusion XL](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0).
- **`MODEL_TYPE=sd3`**: Includes checkpoint for [Stable Diffusion 3 medium](https://huggingface.co/stabilityai/stable-diffusion-3-medium).

## API Specification

The worker exposes HTTP endpoints compatible with Google Cloud Run:

- **`GET /`**: Basic service information
- **`GET /healthz`**: Health check endpoint for Cloud Run
- **`POST /predict`**: Main prediction endpoint for workflow execution
- **`GET /models`**: Get available models information

### Request Format

Send POST requests to `/predict` with the following JSON structure:

```json
{
  "workflow": { ... },  // ComfyUI workflow JSON
  "images": [           // Optional: input images
    {
      "name": "input.png",
      "image": "base64_encoded_image_data"
    }
  ]
}
```

### Response Format

Successful responses return:

```json
{
  "status": "success",
  "prompt_id": "uuid",
  "images": [
    {
      "filename": "output.png",
      "subfolder": "",
      "type": "output",
      "image": "base64_encoded_image_data"
    }
  ],
  "outputs": { ... }
}
```

## Deployment

### Prerequisites

1. Enable required Google Cloud APIs:
   ```bash
   gcloud services enable cloudrun.googleapis.com
   gcloud services enable artifactregistry.googleapis.com
   gcloud services enable compute.googleapis.com
   ```

2. Request L4 GPU quota in your desired region (e.g., `us-central1`).

3. Create an Artifact Registry repository:
   ```bash
   gcloud artifacts repositories create comfyui \
     --repository-format=docker \
     --location=us-central1 \
     --description="ComfyUI Docker repository"
   ```

### Build and Deploy

1. **Build the Docker image:**
   ```bash
   docker build \
     --build-arg MODEL_TYPE=flux1-dev-fp8 \
     --build-arg HUGGINGFACE_ACCESS_TOKEN=your_token \
     -t us-central1-docker.pkg.dev/YOUR_PROJECT/comfyui/comfyui:latest \
     .
   ```

2. **Push to Artifact Registry:**
   ```bash
   docker push us-central1-docker.pkg.dev/YOUR_PROJECT/comfyui/comfyui:latest
   ```

3. **Deploy to Cloud Run:**
   ```bash
   gcloud run deploy comfyui \
     --image=us-central1-docker.pkg.dev/YOUR_PROJECT/comfyui/comfyui:latest \
     --region=us-central1 \
     --platform=managed \
     --gpu=1 \
     --gpu-type=l4 \
     --memory=32Gi \
     --cpu=8 \
     --allow-unauthenticated \
     --timeout=900 \
     --concurrency=1 \
     --min-instances=0 \
     --max-instances=3
   ```

### Using the Deployment Script

Use the provided deployment script for easier deployment:

```bash
chmod +x deploy.sh
./deploy.sh YOUR_PROJECT_ID us-central1 latest
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `COMFY_LOG_LEVEL` | ComfyUI logging level | `DEBUG` |
| `WEBSOCKET_RECONNECT_ATTEMPTS` | WebSocket reconnection attempts | `5` |
| `WEBSOCKET_RECONNECT_DELAY_S` | Delay between reconnection attempts | `3` |
| `WEBSOCKET_TRACE` | Enable WebSocket trace logging | `false` |

## Limitations

- **Single request processing**: Due to GPU memory constraints, only one request is processed at a time (`concurrency=1`).
- **Cold start time**: Initial requests may take 1-2 minutes to start the service.
- **Memory limits**: 32GB memory limit may restrict very large workflows.
- **Timeout**: Maximum execution time is 15 minutes (900 seconds).

## Usage

To interact with your deployed Cloud Run endpoint:

1.  **Get API Key:** Not required for Cloud Run.
2.  **Get Endpoint ID:** Find your endpoint URL on the [Cloud Run dashboard](https://console.cloud.google.com/run).

### Generate Image (Sync Example)

Send a workflow to the `/predict` endpoint (waits for completion). Replace `<endpoint_url>` with your Cloud Run endpoint URL. The `-d` value should contain the [JSON input described above](#request-format).

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"workflow":{... your workflow JSON ...}}' \
  https://<endpoint_url>/predict
```

You can also use the `/predict` endpoint for asynchronous jobs and then poll the `/status` to see when the job is done. Or you [add a `webhook` into your request](https://cloud.google.com/run/docs/triggering/notifications) to be notified when the job is done.

Refer to [`test_input.json`](./test_input.json) for a complete input example.

## Getting the Workflow JSON

To get the correct `workflow` JSON for the API:

1.  Open ComfyUI in your browser.
2.  In the top navigation, select `Workflow > Export (API)`
3.  A `workflow.json` file will be downloaded. Use the content of this file as the value for the `workflow` field in your API requests.

## Further Documentation

- **[Deployment Guide](docs/deployment.md):** Detailed steps for deploying on Google Cloud Run.
- **[Configuration Guide](docs/configuration.md):** Full list of environment variables.
- **[Customization Guide](docs/customization.md):** Adding custom models and nodes (Network Volumes, Docker builds).
- **[Development Guide](docs/development.md):** Setting up a local environment for development & testing
- **[CI/CD Guide](docs/ci-cd.md):** Information about the automated Docker build and publish workflows.
- **[Acknowledgments](docs/acknowledgments.md):** Credits and thanks
