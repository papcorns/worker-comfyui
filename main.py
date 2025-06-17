#!/usr/bin/env python3
"""
Cloud Run entrypoint for ComfyUI worker using Functions Framework.
Replaces RunPod serverless framework with HTTP endpoints.
"""

import os
import json
import logging
import subprocess
import time
import threading
from typing import Dict, Any, Tuple
from flask import Flask, request, jsonify
import functions_framework

# Import the refactored handler logic
from service import ComfyUIService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global state
class AppState:
    def __init__(self):
        self.comfy_service = None
        self.comfy_process = None
        self.comfy_ready = False
        self.comfy_thread = None

state = AppState()

def start_comfyui():
    """Start ComfyUI server in background and signal when ready."""
    global state
    
    # Use libtcmalloc for better memory management
    env = os.environ.copy()
    try:
        import subprocess
        result = subprocess.run(['ldconfig', '-p'], capture_output=True, text=True)
        tcmalloc_libs = [line for line in result.stdout.split('\n') if 'libtcmalloc.so' in line]
        if tcmalloc_libs:
            tcmalloc_path = tcmalloc_libs[0].split('=>')[-1].strip()
            env['LD_PRELOAD'] = tcmalloc_path
            logger.info(f"Using tcmalloc: {tcmalloc_path}")
    except Exception as e:
        logger.warning(f"Could not set tcmalloc: {e}")
    
    # Set ComfyUI-Manager to offline mode
    try:
        subprocess.run(['comfy-manager-set-mode', 'offline'], check=False)
    except Exception as e:
        logger.warning(f"Could not set ComfyUI-Manager network_mode: {e}")
    
    # Start ComfyUI
    logger.info("Starting ComfyUI server")
    log_level = os.environ.get('COMFY_LOG_LEVEL', 'DEBUG')
    
    cmd = [
        'python', '-u', '/comfyui/main.py',
        '--disable-auto-launch',
        '--disable-metadata',
        '--listen',
        '--verbose', log_level,
        '--log-stdout'
    ]
    
    state.comfy_process = subprocess.Popen(cmd, env=env)
    
    # Wait for ComfyUI to be ready
    max_retries = 120 # Increased timeout to 4 minutes
    for i in range(max_retries):
        try:
            import requests
            response = requests.get('http://127.0.0.1:8188/', timeout=5)
            if response.status_code == 200:
                logger.info("ComfyUI server is ready")
                state.comfy_ready = True
                return
        except Exception:
            logger.info(f"Waiting for ComfyUI... attempt {i+1}/{max_retries}")
        time.sleep(2)
    
    logger.error("ComfyUI server failed to start within timeout. Terminating process.")
    if state.comfy_process:
        state.comfy_process.terminate()

def initialize_service():
    """Initialize the ComfyUI service in a background thread."""
    global state
    
    if state.comfy_thread is None:
        logger.info("Initializing ComfyUI Service...")
        # Initialize service
        state.comfy_service = ComfyUIService()
        
        # Start ComfyUI in background thread
        state.comfy_thread = threading.Thread(target=start_comfyui, daemon=True)
        state.comfy_thread.start()
        logger.info("ComfyUI startup thread launched.")

# Initialize service on application startup
initialize_service()

@functions_framework.http
def app(request):
    """Main HTTP function for Cloud Run"""
    
    # Handle different routes
    path = request.path
    method = request.method
    
    try:
        
        if path == '/' and method == 'GET':
            return jsonify({
                'status': 'ok',
                'service': 'comfyui-worker',
                'version': '1.0.0'
            }), 200
        
        elif path == '/healthz' and method == 'GET':
            # Health check endpoint for Cloud Run
            if state.comfy_ready:
                return jsonify({'status': 'ok'}), 200
            else:
                # Return 200 OK but indicate service is initializing
                # This keeps Cloud Run happy during cold starts
                return jsonify({'status': 'initializing'}), 200
        
        elif path == '/predict' and method == 'POST':
 
            
            if not state.comfy_ready or not state.comfy_service:
                return jsonify({'error': 'Service not ready'}), 503
            
            # Get request data
            job_input = request.get_json()
            if not job_input:
                return jsonify({'error': 'No JSON data provided'}), 400
            
            # Process the request
            result = state.comfy_service.process_job(job_input)
            
            if 'error' in result:
                return jsonify(result), 400
            else:
                return jsonify(result), 200
        
        elif path == '/models' and method == 'GET':
            # Get available models endpoint
            
            if not state.comfy_ready or not state.comfy_service:
                return jsonify({'error': 'Service not ready'}), 503
            
            models = state.comfy_service.get_available_models()
            return jsonify(models), 200
        
        else:
            return jsonify({'error': 'Not found'}), 404
            
    except Exception as e:
        logger.error(f"Error in app function: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # For local testing
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Run in test mode')
    parser.add_argument('--port', type=int, default=8080, help='Port to run on')
    args = parser.parse_args()
    
    if args.test:
        print("Starting test server...")
        # Create a simple Flask app for testing
        test_app = Flask(__name__)
        
        @test_app.route('/', methods=['GET'])
        def test_root():
            return app(request)
        
        @test_app.route('/healthz', methods=['GET'])
        def test_health():
            return app(request)
        
        @test_app.route('/predict', methods=['POST'])
        def test_predict():
            return app(request)
        
        @test_app.route('/models', methods=['GET'])
        def test_models():
            return app(request)
        
        test_app.run(host='0.0.0.0', port=args.port, debug=True)
