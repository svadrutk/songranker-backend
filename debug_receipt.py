import requests

url = "http://localhost:8000/generate-receipt"

payload = {
  "songs": [
    {
      "song_id": "1",
      "name": "Bohemian Rhapsody",
      "artist": "Queen",
      "cover_url": "https://upload.wikimedia.org/wikipedia/en/9/9f/Bohemian_Rhapsody.png"
    },
    {
      "song_id": "2",
      "name": "Stairway to Heaven",
      "artist": "Led Zeppelin",
      "cover_url": "https://upload.wikimedia.org/wikipedia/en/4/41/Led_Zeppelin_-_Led_Zeppelin_IV.jpg"
    }
  ],
  "orderId": 9999,
  "dateStr": "TEST_DATE",
  "timeStr": "TEST_TIME"
}

try:
    print(f"Sending payload: {payload}")
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        with open("test_receipt_debug.png", "wb") as f:
            f.write(response.content)
        print("Success! Image saved to test_receipt_debug.png")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"Request failed: {e}")
