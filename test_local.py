#!/usr/bin/env python3
"""
Local testing script for ComfyUI Cloud Run worker
"""

import json
import requests
import time
import sys
import argparse

def test_health_endpoint(base_url):
    """Test the health endpoint"""
    print("Testing health endpoint...")
    try:
        response = requests.get(f"{base_url}/healthz", timeout=10)
        print(f"Health check status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

def test_root_endpoint(base_url):
    """Test the root endpoint"""
    print("Testing root endpoint...")
    try:
        response = requests.get(f"{base_url}/", timeout=10)
        print(f"Root endpoint status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Root endpoint test failed: {e}")
        return False

def test_models_endpoint(base_url):
    """Test the models endpoint"""
    print("Testing models endpoint...")
    try:
        response = requests.get(f"{base_url}/models", timeout=30)
        print(f"Models endpoint status: {response.status_code}")
        if response.status_code == 200:
            models = response.json()
            print(f"Available models: {len(models)} categories")
            return True
        else:
            print(f"Models endpoint error: {response.text}")
            return False
    except Exception as e:
        print(f"Models endpoint test failed: {e}")
        return False

def test_predict_endpoint(base_url, workflow_file):
    """Test the predict endpoint with a workflow"""
    print("Testing predict endpoint...")
    
    # Load test workflow
    try:
        with open(workflow_file, 'r') as f:
            test_data = json.load(f)
    except Exception as e:
        print(f"Failed to load workflow file {workflow_file}: {e}")
        return False
    
    try:
        print("Sending prediction request...")
        response = requests.post(
            f"{base_url}/predict",
            json=test_data,
            timeout=300  # 5 minutes timeout
        )
        
        print(f"Predict endpoint status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Prediction successful!")
            print(f"Prompt ID: {result.get('prompt_id', 'N/A')}")
            print(f"Generated images: {len(result.get('images', []))}")
            
            # Save first image if available
            if result.get('images'):
                first_image = result['images'][0]
                filename = f"test_output_{int(time.time())}.png"
                
                import base64
                image_data = base64.b64decode(first_image['image'])
                with open(filename, 'wb') as f:
                    f.write(image_data)
                print(f"Saved test image as: {filename}")
            
            return True
        else:
            print(f"Prediction failed: {response.text}")
            return False
            
    except Exception as e:
        print(f"Predict endpoint test failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Test ComfyUI Cloud Run worker')
    parser.add_argument('--url', default='http://localhost:8080', 
                       help='Base URL of the service (default: http://localhost:8080)')
    parser.add_argument('--workflow', default='test_input.json',
                       help='Path to test workflow file (default: test_input.json)')
    parser.add_argument('--skip-predict', action='store_true',
                       help='Skip the prediction test (useful for quick health checks)')
    
    args = parser.parse_args()
    
    base_url = args.url.rstrip('/')
    
    print(f"Testing ComfyUI worker at: {base_url}")
    print("=" * 50)
    
    # Run tests
    tests_passed = 0
    total_tests = 4 if not args.skip_predict else 3
    
    # Test root endpoint
    if test_root_endpoint(base_url):
        tests_passed += 1
    print()
    
    # Test health endpoint
    if test_health_endpoint(base_url):
        tests_passed += 1
    print()
    
    # Test models endpoint
    if test_models_endpoint(base_url):
        tests_passed += 1
    print()
    
    # Test predict endpoint (if not skipped)
    if not args.skip_predict:
        if test_predict_endpoint(base_url, args.workflow):
            tests_passed += 1
        print()
    
    # Summary
    print("=" * 50)
    print(f"Tests passed: {tests_passed}/{total_tests}")
    
    if tests_passed == total_tests:
        print("✅ All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed!")
        sys.exit(1)

if __name__ == '__main__':
    main()
