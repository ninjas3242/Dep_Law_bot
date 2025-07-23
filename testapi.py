import requests

def test_gemini_flash_api(api_key):
    """
    Test the Gemini Flash API with a simple 'Hi, hello' prompt.
    """
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"
    headers = {
        "Content-Type": "application/json"
    }
    params = {
        "key": api_key
    }
    payload = {
        "contents": [
            {"parts": [{"text": "Hi, hello"}]}
        ]
    }
    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ API key is valid. Response:", response.json())
        else:
            print(f"❌ API key test failed. Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"❌ Error testing API key: {e}")

if __name__ == "__main__":
    api_key = input("Enter your Gemini API key: ")
    test_gemini_flash_api(api_key)