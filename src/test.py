#!/usr/bin/env python3
"""
Example script to test the Instagram scraper API
"""
import requests
import json
import sys

BASE_URL = "http://localhost:5001"

def get_user_info(username: str):
    """Get information about a specific user"""
    try:
        response = requests.post(
            f"{BASE_URL}/user-info",
            json={
                "username": username
            },
            timeout=60
        )
    except requests.exceptions.ConnectionError:
        error_response = {
            "error": f"Cannot connect to server at {BASE_URL}",
            "message": "Make sure the server is running: python app.py"
        }
        print(json.dumps(error_response, indent=2))
        return None
    except Exception as e:
        error_response = {
            "error": str(e)
        }
        print(json.dumps(error_response, indent=2))
        return None
    
    try:
        data = response.json()
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return data
    except:
        error_response = {
            "error": f"HTTP {response.status_code}",
            "response": response.text
        }
        print(json.dumps(error_response, indent=2))
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        error_response = {
            "error": "Usage: python src/test.py <username>",
            "example": "python src/test.py paulodybala"
        }
        print(json.dumps(error_response, indent=2))
        sys.exit(1)
    
    username = sys.argv[1].strip().lstrip('@')  # Remove @ if present
    get_user_info(username)

