"""
ComfyUI Service Layer - Refactored from handler.py to remove RunPod dependencies
"""

import json
import urllib.request
import urllib.parse
import time
import os
import requests
import base64
from io import BytesIO
import websocket
import uuid
import tempfile
import socket
import traceback
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Time to wait between API check attempts in milliseconds
COMFY_API_AVAILABLE_INTERVAL_MS = 50
# Maximum number of API check attempts
COMFY_API_AVAILABLE_MAX_RETRIES = 500
# Websocket reconnection behaviour
WEBSOCKET_RECONNECT_ATTEMPTS = int(os.environ.get("WEBSOCKET_RECONNECT_ATTEMPTS", 5))
WEBSOCKET_RECONNECT_DELAY_S = int(os.environ.get("WEBSOCKET_RECONNECT_DELAY_S", 3))

# Extra verbose websocket trace logs
if os.environ.get("WEBSOCKET_TRACE", "false").lower() == "true":
    websocket.enableTrace(True)

# Host where ComfyUI is running
COMFY_HOST = "127.0.0.1:8188"

class ComfyUIService:
    """Service class for ComfyUI operations"""
    
    def __init__(self):
        self.comfy_host = COMFY_HOST
        
    def _comfy_server_status(self) -> Dict[str, Any]:
        """Return a dictionary with basic reachability info for the ComfyUI HTTP server."""
        try:
            resp = requests.get(f"http://{self.comfy_host}/", timeout=5)
            return {"status": "reachable", "code": resp.status_code, "response": resp.text}
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}

    def _attempt_websocket_reconnect(self, ws_url: str, max_attempts: int, delay_s: int, initial_error: Exception) -> websocket.WebSocket:
        """
        Attempts to reconnect to the WebSocket server after a disconnect.
        """
        logger.warning(f"WebSocket connection lost: {initial_error}")
        logger.info(f"Attempting to reconnect to {ws_url} (max {max_attempts} attempts, {delay_s}s delay)")
        
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Reconnection attempt {attempt}/{max_attempts}")
                time.sleep(delay_s)
                
                ws = websocket.WebSocket()
                ws.connect(ws_url)
                logger.info(f"Successfully reconnected on attempt {attempt}")
                return ws
                
            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt} failed: {e}")
                if attempt == max_attempts:
                    logger.error(f"All {max_attempts} reconnection attempts failed")
                    raise websocket.WebSocketConnectionClosedException(
                        f"Failed to reconnect after {max_attempts} attempts. Last error: {e}"
                    )
        
        raise websocket.WebSocketConnectionClosedException("Unexpected end of reconnection loop")

    def validate_input(self, job_input: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Validates the input for the handler function.
        """
        # Check if input is provided
        if job_input is None:
            return {}, "Please provide input"

        # Check if input is a dictionary
        if not isinstance(job_input, dict):
            return {}, "Input must be a dictionary"

        # Validate required fields
        if "workflow" not in job_input:
            return {}, "Missing 'workflow' parameter"

        workflow = job_input["workflow"]
        if not isinstance(workflow, dict):
            return {}, "'workflow' must be a dictionary"

        # Validate images if provided
        if "images" in job_input:
            images = job_input["images"]
            if not isinstance(images, list):
                return {}, "'images' must be a list"
            
            for i, image in enumerate(images):
                if not isinstance(image, dict):
                    return {}, f"Image {i} must be a dictionary"
                if "name" not in image or "image" not in image:
                    return {}, f"Image {i} must have 'name' and 'image' fields"

        return job_input, None

    def check_server(self, url: str, retries: int = 500, delay: int = 50) -> bool:
        """
        Check if a server is reachable via HTTP GET request
        """
        for i in range(retries):
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            
            if i < retries - 1:  # Don't sleep on the last iteration
                time.sleep(delay / 1000.0)  # Convert ms to seconds
        
        return False

    def upload_images(self, images: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Upload a list of base64 encoded images to the ComfyUI server using the /upload/image endpoint.
        """
        if not images:
            return {"status": "success", "message": "No images to upload"}

        upload_results = []
        
        for image_data in images:
            try:
                image_name = image_data["name"]
                image_base64 = image_data["image"]
                
                # Decode base64 image
                if image_base64.startswith('data:image/'):
                    # Remove data URL prefix if present
                    image_base64 = image_base64.split(',')[1]
                
                image_bytes = base64.b64decode(image_base64)
                
                # Prepare multipart form data
                files = {
                    'image': (image_name, BytesIO(image_bytes), 'image/png')
                }
                
                # Upload to ComfyUI
                response = requests.post(
                    f"http://{self.comfy_host}/upload/image",
                    files=files,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    upload_results.append({
                        "name": image_name,
                        "status": "success",
                        "result": result
                    })
                    logger.info(f"Successfully uploaded image: {image_name}")
                else:
                    upload_results.append({
                        "name": image_name,
                        "status": "error",
                        "error": f"HTTP {response.status_code}: {response.text}"
                    })
                    logger.error(f"Failed to upload image {image_name}: {response.status_code}")
                    
            except Exception as e:
                upload_results.append({
                    "name": image_data.get("name", "unknown"),
                    "status": "error",
                    "error": str(e)
                })
                logger.error(f"Error uploading image: {e}")
        
        # Check if any uploads failed
        failed_uploads = [r for r in upload_results if r["status"] == "error"]
        if failed_uploads:
            return {
                "status": "error",
                "message": f"{len(failed_uploads)} image(s) failed to upload",
                "results": upload_results
            }
        
        return {
            "status": "success",
            "message": f"Successfully uploaded {len(upload_results)} image(s)",
            "results": upload_results
        }

    def get_available_models(self) -> Dict[str, Any]:
        """
        Get list of available models from ComfyUI
        """
        try:
            response = requests.get(f"http://{self.comfy_host}/object_info", timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to get models: HTTP {response.status_code}"}
        except Exception as e:
            return {"error": f"Failed to get models: {str(e)}"}

    def queue_workflow(self, workflow: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """
        Queue a workflow to be processed by ComfyUI
        """
        try:
            # Prepare the prompt data
            prompt_data = {
                "prompt": workflow,
                "client_id": client_id
            }
            
            # Send to ComfyUI
            response = requests.post(
                f"http://{self.comfy_host}/prompt",
                json=prompt_data,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                logger.error(f"Failed to queue workflow: {error_msg}")
                raise ValueError(f"Failed to queue workflow: {error_msg}")
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {str(e)}"
            logger.error(f"Failed to queue workflow: {error_msg}")
            raise ValueError(f"Failed to queue workflow: {error_msg}")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to queue workflow: {error_msg}")
            raise ValueError(f"Failed to queue workflow: {error_msg}")

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        """
        Retrieve the history of a given prompt using its ID
        """
        try:
            response = requests.get(f"http://{self.comfy_host}/history/{prompt_id}", timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to get history: HTTP {response.status_code}"}
        except Exception as e:
            return {"error": f"Failed to get history: {str(e)}"}

    def get_image_data(self, filename: str, subfolder: str, image_type: str) -> Optional[bytes]:
        """
        Fetch image bytes from the ComfyUI /view endpoint.
        """
        try:
            params = {
                "filename": filename,
                "type": image_type
            }
            if subfolder:
                params["subfolder"] = subfolder
            
            url = f"http://{self.comfy_host}/view?" + urllib.parse.urlencode(params)
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Failed to get image data: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting image data: {e}")
            return None

    def process_job(self, job_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main job processing function - replaces the original handler function
        """
        try:
            # Validate input
            validated_input, error = self.validate_input(job_input)
            if error:
                return {"error": error}
            
            # Check if ComfyUI server is available
            if not self.check_server(f"http://{self.comfy_host}/"):
                return {"error": "ComfyUI server is not available"}
            
            # Upload images if provided
            if "images" in validated_input:
                upload_result = self.upload_images(validated_input["images"])
                if upload_result["status"] == "error":
                    return {"error": f"Image upload failed: {upload_result['message']}"}
            
            # Generate client ID for websocket connection
            client_id = str(uuid.uuid4())
            
            # Queue the workflow
            workflow = validated_input["workflow"]
            queue_result = self.queue_workflow(workflow, client_id)
            
            if "prompt_id" not in queue_result:
                return {"error": "Failed to queue workflow - no prompt_id returned"}
            
            prompt_id = queue_result["prompt_id"]
            logger.info(f"Queued workflow with prompt_id: {prompt_id}")
            
            # Connect to websocket to monitor progress
            ws_url = f"ws://{self.comfy_host}/ws?clientId={client_id}"
            
            try:
                ws = websocket.WebSocket()
                ws.connect(ws_url)
            except Exception as e:
                return {"error": f"Failed to connect to websocket: {str(e)}"}
            
            # Monitor execution
            try:
                while True:
                    try:
                        message = ws.recv()
                        if message:
                            data = json.loads(message)
                            
                            if data["type"] == "executing":
                                executing_data = data["data"]
                                if executing_data["node"] is None and executing_data["prompt_id"] == prompt_id:
                                    # Execution finished
                                    logger.info(f"Workflow execution completed for prompt_id: {prompt_id}")
                                    break
                            elif data["type"] == "execution_error":
                                error_data = data["data"]
                                logger.error(f"Execution error: {error_data}")
                                return {"error": f"Workflow execution failed: {error_data}"}
                                
                    except websocket.WebSocketConnectionClosedException as e:
                        # Try to reconnect
                        ws = self._attempt_websocket_reconnect(
                            ws_url, WEBSOCKET_RECONNECT_ATTEMPTS, WEBSOCKET_RECONNECT_DELAY_S, e
                        )
                        continue
                    except Exception as e:
                        logger.error(f"WebSocket error: {e}")
                        break
                        
            finally:
                try:
                    ws.close()
                except:
                    pass
            
            # Get the results
            history = self.get_history(prompt_id)
            if "error" in history:
                return {"error": f"Failed to get execution history: {history['error']}"}
            
            if prompt_id not in history:
                return {"error": "Execution history not found"}
            
            # Extract output images
            outputs = history[prompt_id].get("outputs", {})
            result_images = []
            
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for image_info in node_output["images"]:
                        filename = image_info["filename"]
                        subfolder = image_info.get("subfolder", "")
                        image_type = image_info.get("type", "output")
                        
                        # Get image data
                        image_data = self.get_image_data(filename, subfolder, image_type)
                        if image_data:
                            # Convert to base64
                            image_base64 = base64.b64encode(image_data).decode('utf-8')
                            result_images.append({
                                "filename": filename,
                                "subfolder": subfolder,
                                "type": image_type,
                                "image": image_base64
                            })
            
            return {
                "status": "success",
                "prompt_id": prompt_id,
                "images": result_images,
                "outputs": outputs
            }
            
        except Exception as e:
            logger.error(f"Error processing job: {e}")
            logger.error(traceback.format_exc())
            return {"error": f"Job processing failed: {str(e)}"}
