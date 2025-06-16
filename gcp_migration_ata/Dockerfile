# Stage 1: Base image with CUDA for Google Cloud Run
# Using the official image for Cloud Run with GPU support.
FROM gcr.io/cloud-run/nvidia-cuda:12.2.2-runtime-ubuntu22.04 AS base

# Prevents prompts from packages asking for user input during installation
ENV DEBIAN_FRONTEND=noninteractive
# Prefer binary wheels over source distributions for faster pip installations
ENV PIP_PREFER_BINARY=1
# Ensures output from python is printed immediately to the terminal without buffering
ENV PYTHONUNBUFFERED=1
# For clarity, though Cloud Run sets these.
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
# Suggested by the migration plan to reduce memory fragmentation in PyTorch.
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:64


# Install Python, git and other necessary tools
# Using python3.11 as it's readily available in the ubuntu:22.04 based image
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    git \
    wget \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

# Create and activate a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install comfy-cli to manage ComfyUI installation
RUN pip install comfy-cli

# Install ComfyUI using comfy-cli
# Pinning to CUDA 12.1 as recommended for L4 GPUs on Cloud Run's CUDA 12.2 runtime
RUN /usr/bin/yes | comfy --workspace /comfyui install --version 0.3.30 --cuda-version 12.1 --nvidia

# Set working directory for the application
WORKDIR /app

# Install Python dependencies for our application
# This Dockerfile will be in gcp_migration, so COPY from the current dir.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Add application code
COPY main.py .
# Copy the models config from the parent src directory.
# The build context should be the root of the repository.
COPY ../src/extra_model_paths.yaml /comfyui/

# Expose port 8080 as required by Cloud Run
EXPOSE 8080

# The command to run the application using Functions Framework
# The --target `app` refers to the `app` function in `main.py`
CMD ["functions-framework", "--target=app", "--port", "8080"]


# Stage 2: Model downloader
FROM base AS downloader

ARG HUGGINGFACE_ACCESS_TOKEN
# Set default model type if none is provided
ARG MODEL_TYPE=flux1-dev-fp8

WORKDIR /comfyui
RUN mkdir -p models/checkpoints models/vae models/unet models/clip

# Download models based on build argument
RUN if [ "$MODEL_TYPE" = "sdxl" ]; then \
      wget -q -O models/checkpoints/sd_xl_base_1.0.safetensors https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors && \
      wget -q -O models/vae/sdxl_vae.safetensors https://huggingface.co/stabilityai/sdxl-vae/resolve/main/sdxl_vae.safetensors; \
    fi
RUN if [ "$MODEL_TYPE" = "flux1-dev-fp8" ]; then \
      wget -q -O models/checkpoints/flux1-dev-fp8.safetensors https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors; \
    fi
# Add other model types from the original Dockerfile if needed

# Stage 3: Final image
# Start from the base stage that has the environment setup
FROM base AS final

# Set the working directory
WORKDIR /app

# Copy the application code from the base stage
COPY --from=base /opt/venv /opt/venv
COPY --from=base /comfyui /comfyui
COPY --from=base /app /app

# Copy the downloaded models from the downloader stage
COPY --from=downloader /comfyui/models /comfyui/models 