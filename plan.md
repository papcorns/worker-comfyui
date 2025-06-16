# Migration & Test Plan: ComfyUI on Google Cloud Run with L4 GPU

This document lists – **in order** – the concrete changes required to run the existing *Runpod*-oriented ComfyUI worker on **Google Cloud Run (GCR)** with an attached **L4 GPU**, as well as the verification steps for each change.

---
## 0. Preparation
1.  Enable the APIs: `cloudrun.googleapis.com`, `artifactregistry.googleapis.com`, `compute.googleapis.com`, `run.googleapis.com`.
2.  Request GPU quota in the desired region (e.g. `us-central1`) and specifically for **L4**.
3.  Install / update the local SDK: `gcloud components update` ≥ 473.0.0.

> **Test 0**: `gcloud run regions list --format="value(REGION,CPUPlatforms)" | grep L4` returns the chosen region.

---
## 1. Repository layout changes
| # | Task | Why |
|---|------|-----|
|1.1|Add `main.py` entrypoint exposing HTTP functions compatible with **Functions Framework** (no Flask/FastAPI wrapper needed).|Cloud Run starts the container by running the Functions Framework target.
|1.2|Move existing startup logic (currently inside `start.sh` or equivalent) into `create_app()` or `main()` in `main.py`.|
|1.3|Ensure `/healthz` and `/` routes return 200 quickly (used for health-checks).|
|1.4|Refactor `handler.py` to REMOVE **runpod** SDK (`runpod.*`) and expose functions via the new HTTP app.|Runpod-specific serverless utilities are not available in Cloud Run.
|1.5|Relocate logic from `handler()` into a service layer callable by the HTTP route.|Separates worker logic from platform integration.
|1.6|Add Cloud Run–friendly entrypoint `predict()` (or similar) mapped to `POST /predict`.|
|1.7|Update env-var handling (e.g. `REFRESH_WORKER`) to Cloud-Run-appropriate flags or remove.|

> **Test 1**: `python main.py --test` starts a local server and returns `200 OK` on `/healthz`.

---
## 2. `requirements.txt` & Python runtime
2.1  Add:  
```
functions-framework==3.*
```
2.2  Pin GPU-related libs (torch, xformers, torchvision) to **CUDA 12.1** wheels (these run on the Cloud Run CUDA 12.2 runtime for L4).

> **Test 2**: `pip install -r requirements.txt` inside a CUDA 12.2 Docker image succeeds and `python -c "import torch,os;print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"` prints `True, "NVIDIA L4"`.

---
## 3. Dockerfile overhaul
| # | Modification |
|---|--------------|
|3.1|Base image → **official Cloud Run GPU image** `gcr.io/cloud-run/nvidia-cuda:12.2-runtime` (or `nvidia/cuda:12.2.0-runtime-ubuntu22.04` if you need custom).|
|3.2|Skip NVIDIA Container Toolkit install when using `gcr.io/cloud-run` base (already included). Only install manually if falling back to vanilla NVIDIA image.|
|3.3|Copy source, install `requirements.txt` in **virtual env**.|
|3.4|Expose port **8080**.|
|3.5|Set `CMD ["functions-framework", "--target=app", "--port", "8080"]` (assuming `app = create_app()`).|
|3.6|Add `ENV NVIDIA_VISIBLE_DEVICES=all \  \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility` (already set in Cloud Run base but kept for clarity).
|3.7|Optional: Enable Python’s `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:64` to limit fragmentation.

> **Test 3**: `docker build -t comfyui-gcr . && docker run --gpus all -p 8080:8080 comfyui-gcr` then open `http://localhost:8080/healthz` → 200.

---
## 4. CI/CD
1. Create **Artifact Registry** repo `comfyui` (type **Docker**) in the same region.
2. Add GitHub Action / Cloud Build YAML to:
   • Build image  
   • Push to `REGION-docker.pkg.dev/PROJECT/comfyui/comfyui:<sha>`.

> **Test 4**: Build + push pipeline finishes < 15 min; image size < 6 GB.

---
## 5. Cloud Run deployment settings
| Setting | Value |
|---------|-------|
|CPU | 8 |
|Memory | 32 GiB |
|GPU | 1 × L4 |
|Min instances | 0 or 1 (cold-start trade-off) |
|Max instances | ≤3 (adjust) |
|Concurrency | 1 (GPU not share-friendly) |
|Timeout | 900 s |
|Ingress | all |

Deployment command example:
```
gcloud run deploy comfyui \
  --image=REGION-docker.pkg.dev/PROJECT/comfyui/comfyui:TAG \
  --region=us-central1 --platform=managed \
  --gpu=1 --gpu-type=l4 --memory=32Gi --cpu=8 \
  --allow-unauthenticated --timeout=900 --concurrency=1
```

> **Test 5**: `curl https://comfyui-<hash>-uc.a.run.app/healthz` → 200 in < 10 s.

---
## 6. Functional verification
| # | Check | Success criteria |
|---|-------|-----------------|
|6.1|Inference request with sample image prompt.|HTTP 200, latency < 30 s, valid output.
|6.2|Concurrent request while first is running.|Second returns 429/503 – **or** queue until GPU frees; no OOM.
|6.3|Large resolution prompt (e.g. 2048×2048).|No OOM; latency acceptable.
|6.4|Idle for 30 min then request.|Cold start < 120 s, GPU visible.

---
## 7. Observability & autoscaling
1. Configure Cloud Monitoring alerts:  
   • GPU utilization > 90 %  
   • Memory > 28 GiB  
2. Enable Cloud Profiler.
3. (Optional) Publish custom metrics (images/s, queue length).

> **Test 7**: Induce high load; verify autoscaler spins up to `max-instances` and metrics appear.

---
## 8. Cost validation
1. Use Cost Table to project monthly cost at expected RPS.
2. Try `min-instances=0` + `--cpu-throttling` to reduce idle spend.

> **Test 8**: After 24 h pilot run, BigQuery export shows spend ≤ budget.

---
## 9. Documentation
1. Update `README.md` with:
   • `gcloud run deploy` snippet  
   • Environment variables list  
   • Limitations (single request at a time)  
2. Add architecture diagram (optional).

---
## 10. De-commission Runpod resources
1. Delete old Runpod pods/workers.  
2. Remove API keys / tokens.

> **Test 10**: Billing dashboard shows zero Runpod spend.

---
## Done 
When every **Test** passes, migration is complete.
