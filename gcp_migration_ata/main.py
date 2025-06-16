# Standard library imports
import os
import json
import base64
import uuid
import time
import subprocess
import traceback
import tempfile
from io import BytesIO
from typing import List, Dict, Any, Optional

# Third-party imports
import requests
import websocket
import socket
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import functions_framework

# Cloud storage imports
import boto3
from botocore.exceptions import ClientError
from google.cloud import storage

# --- Configuration ---
COMFY_HOST = "127.0.0.1:8188"
COMFY_API_AVAILABLE_INTERVAL_MS = 50
COMFY_API_AVAILABLE_MAX_RETRIES = 500
WEBSOCKET_RECONNECT_ATTEMPTS = int(os.environ.get("WEBSOCKET_RECONNECT_ATTEMPTS", 5))
WEBSOCKET_RECONNECT_DELAY_S = int(os.environ.get("WEBSOCKET_RECONNECT_DELAY_S", 3))

# Cloud Storage Configuration
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
S3_REGION = os.environ.get("S3_REGION")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

# --- FastAPI App & Pydantic Models ---
class ImageInput(BaseModel):
    name: str
    image: str

class RequestBody(BaseModel):
    workflow: Dict[str, Any]
    images: Optional[List[ImageInput]] = None

@functions_framework.http
def app(request):
    """
    HTTP Cloud Function.
    This function is executed for every HTTP request.
    It uses an internal FastAPI app to handle routing and logic.
    """
    # This is a bit of a workaround to make FastAPI work with Functions Framework v3
    # See: https://github.com/GoogleCloudPlatform/functions-framework-python/issues/225
    from asgiref.wsgi import WsgiToAsgi
    asgi_app = WsgiToAsgi(fastapi_app)
    
    async def run_asgi(scope, receive, send):
        await asgi_app(scope, receive, send)

    scope = {
        'type': 'http',
        'http_version': '1.1',
        'method': request.method,
        'path': request.path,
        'headers': request.headers.items(),
        'scheme': 'http',
        'query_string': request.query_string,
        'body': request.get_data(),
        'client': ('127.0.0.1', 80),
        'server': ('127.0.0.1', 8080)
    }

    # This is a simplified event loop to run the async app
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    response_sent = False
    async def send(message):
        nonlocal response_sent
        if message['type'] == 'http.response.start' and not response_sent:
            status_code = message['status']
            headers = [(k.decode(), v.decode()) for k, v in message['headers']]
            from flask import Response
            response = Response(b"", status=status_code, headers=headers)
            globals()['flask_response'] = response
            response_sent = True
        elif message['type'] == 'http.response.body':
            globals()['flask_response'].data += message.get('body', b'')

    async def receive():
        return {'type': 'http.request', 'body': request.get_data(), 'more_body': False}

    try:
        task = loop.create_task(run_asgi(scope, receive, send))
        loop.run_until_complete(task)
    finally:
        loop.close()
        
    return globals().get('flask_response', ('Internal Server Error', 500))

fastapi_app = FastAPI()

# --- ComfyUI Startup ---
def start_comfyui():
    """Starts the ComfyUI server in a background process."""
    os.chdir("/comfyui")
    cmd = [
        "python", "-u", "main.py",
        "--disable-auto-launch",
        "--disable-metadata",
        "--verbose", os.environ.get("COMFY_LOG_LEVEL", "DEBUG"),
        "--log-stdout"
    ]
    print("worker-comfyui: Starting ComfyUI server...")
    subprocess.Popen(cmd)
    print("worker-comfyui: ComfyUI process started.")

start_comfyui()

# --- Helper Functions (from original handler.py, adapted) ---

def _comfy_server_status():
    """Return a dictionary with basic reachability info for the ComfyUI HTTP server."""
    try:
        resp = requests.get(f"http://{COMFY_HOST}/", timeout=5)
        return {
            "reachable": resp.status_code == 200,
            "status_code": resp.status_code,
        }
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}

def check_server(url, retries, delay):
    """Check if a server is reachable."""
    print(f"worker-comfyui - Checking API server at {url}...")
    for i in range(retries):
        try:
            if _comfy_server_status()["reachable"]:
                print(f"worker-comfyui - API is reachable")
                return True
        except requests.RequestException:
            pass
        time.sleep(delay / 1000)
    print(f"worker-comfyui - Failed to connect to server at {url} after {retries} attempts.")
    return False

def upload_images(images: List[ImageInput]):
    """Upload a list of base64 encoded images to the ComfyUI server."""
    if not images:
        return {"status": "success", "message": "No images to upload"}

    print(f"worker-comfyui - Uploading {len(images)} image(s)...")
    for image in images:
        try:
            image_data_uri = image.image
            if "," in image_data_uri:
                base64_data = image_data_uri.split(",", 1)[1]
            else:
                base64_data = image_data_uri
            
            blob = base64.b64decode(base64_data)
            files = {"image": (image.name, BytesIO(blob), "image/png"), "overwrite": (None, "true")}
            response = requests.post(f"http://{COMFY_HOST}/upload/image", files=files, timeout=30)
            response.raise_for_status()
            print(f"worker-comfyui - Successfully uploaded {image.name}")
        except Exception as e:
            raise RuntimeError(f"Error uploading {image.name}: {e}")
    return {"status": "success"}

def queue_workflow(workflow, client_id):
    """Queue a workflow to be processed by ComfyUI."""
    payload = {"prompt": workflow, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    response = requests.post(f"http://{COMFY_HOST}/prompt", data=data, headers=headers, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to queue workflow: {response.text}")
    return response.json()

def get_history(prompt_id):
    """Retrieve the history of a given prompt."""
    response = requests.get(f"http://{COMFY_HOST}/history/{prompt_id}", timeout=30)
    response.raise_for_status()
    return response.json()

def get_image_data(filename, subfolder, image_type):
    """Fetch image bytes from the ComfyUI /view endpoint."""
    data = {"filename": filename, "subfolder": subfolder, "type": image_type}
    url_values = urllib.parse.urlencode(data)
    response = requests.get(f"http://{COMFY_HOST}/view?{url_values}", timeout=60)
    response.raise_for_status()
    return response.content

def upload_to_gcs(data, bucket_name, object_name):
    """Upload data to a GCS bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_string(data, content_type='image/png')
    return f"gs://{bucket_name}/{object_name}"

def upload_to_s3(data, bucket_name, object_name):
    """Upload data to an S3 bucket."""
    s3_client = boto3.client("s3", endpoint_url=S3_ENDPOINT_URL, aws_access_key_id=S3_ACCESS_KEY_ID, aws_secret_access_key=S3_SECRET_ACCESS_KEY, region_name=S3_REGION)
    s3_client.put_object(Body=data, Bucket=bucket_name, Key=object_name, ContentType='image/png')
    if S3_ENDPOINT_URL:
        return f"{S3_ENDPOINT_URL}/{bucket_name}/{object_name}"
    return f"https://{bucket_name}.s3.{S3_REGION}.amazonaws.com/{object_name}"


def run_workflow_and_get_images(request_body: RequestBody):
    """The main logic to run the workflow and handle images."""
    workflow = request_body.workflow
    input_images = request_body.images

    if not check_server(f"http://{COMFY_HOST}/", COMFY_API_AVAILABLE_MAX_RETRIES, COMFY_API_AVAILABLE_INTERVAL_MS):
        raise RuntimeError("ComfyUI server is not available.")
    
    if input_images:
        upload_images(input_images)

    client_id = str(uuid.uuid4())
    ws_url = f"ws://{COMFY_HOST}/ws?clientId={client_id}"
    ws = websocket.WebSocket()
    ws.connect(ws_url, timeout=10)

    try:
        queued_workflow = queue_workflow(workflow, client_id)
        prompt_id = queued_workflow["prompt_id"]
        
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message["type"] == "executed" and message["data"]["prompt_id"] == prompt_id:
                    break
        
        history = get_history(prompt_id)[prompt_id]
        output_images_list = []
        output_errors = []

        for node_id, node_output in history["outputs"].items():
            if "images" in node_output:
                for image in node_output["images"]:
                    image_data = get_image_data(image["filename"], image["subfolder"], image["type"])
                    if not image_data:
                        output_errors.append(f"Failed to retrieve image {image['filename']}")
                        continue

                    if GCS_BUCKET_NAME:
                        url = upload_to_gcs(image_data, GCS_BUCKET_NAME, image["filename"])
                        output_images_list.append({"filename": image["filename"], "type": "gcs_url", "data": url})
                    elif S3_BUCKET_NAME:
                        url = upload_to_s3(image_data, S3_BUCKET_NAME, image["filename"])
                        output_images_list.append({"filename": image["filename"], "type": "s3_url", "data": url})
                    else:
                        base64_image = base64.b64encode(image_data).decode("utf-8")
                        output_images_list.append({"filename": image["filename"], "type": "base64", "data": base64_image})
        
        result = {"images": output_images_list}
        if output_errors:
            result["errors"] = output_errors
        return result
    finally:
        ws.close()

# --- API Endpoints ---
@fastapi_app.post("/predict")
async def predict(body: RequestBody):
    """Synchronous endpoint to run a workflow."""
    try:
        start_time = time.time()
        output = run_workflow_and_get_images(body)
        end_time = time.time()
        
        return {
            "id": f"sync-{uuid.uuid4()}",
            "status": "COMPLETED",
            "output": output,
            "executionTime": int((end_time - start_time) * 1000)
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@fastapi_app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "comfyui": _comfy_server_status()}

@fastapi_app.get("/")
async def root():
    """Root endpoint for basic health check."""
    return {"status": "ok"} 