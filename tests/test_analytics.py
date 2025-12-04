#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script para los endpoints de analytics
"""

import requests
import json

BASE_URL = 'http://localhost:5000/api/analytics'

def test_endpoint(name, url):
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    print('='*60)
    try:
        response = requests.get(url, timeout=5)
        print(f"Status Code: {response.status_code}")
        if response.ok:
            data = response.json()
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == '__main__':
    print("="*60)
    print("  TESTING ANALYTICS API ENDPOINTS")
    print("="*60)

    # Test all endpoints
    test_endpoint("Overview", f"{BASE_URL}/overview")
    test_endpoint("Searches (30 days)", f"{BASE_URL}/searches?days=30")
    test_endpoint("Captures (30 days)", f"{BASE_URL}/captures?days=30")
    test_endpoint("Interactions (30 days)", f"{BASE_URL}/interactions?days=30")

    print("\n" + "="*60)
    print("  TESTS COMPLETED")
    print("="*60)
