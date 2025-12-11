# test_webhook_signed.py
import time
import hmac
import hashlib
import json
import requests

# UPDATE THIS URL to your current ngrok/server URL
WEBHOOK_URL = "https://7cf1a050b896.ngrok-free.app/webhook/zoom"
SECRET = "y89hMD-cQuy5r-yOoJz6IQ"  # must match settings.ZOOM_WEBHOOK_SECRET_TOKEN on the server

# Generate unique call_id to avoid database duplicate checks
unique_call_id = f"test_{int(time.time())}"

body = {
    "event": "phone.recording_completed",
    "payload": {
        "object": {
            "call_id": unique_call_id,
            "download_url": "https://nlswzwucccjhsebkaczn.supabase.co/storage/v1/object/public/test/ClassAudio(2).mp3",
            "caller": {"phone_number": "+1234567890"},
            "callee": {"name": "Test Agent"},
            "duration": 185,  # 3 minutes 5 seconds
            "date_time": "2025-12-11T12:30:00Z",
        }
    },
}

# JSON serialization must be stable and exactly the bytes the server will receive.
body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

ts = str(int(time.time()))
message = f"v0:{ts}:{body_json}"

digest = hmac.new(
    SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
).hexdigest()
sig_header = f"v0={digest}"

print("Timestamp:", ts)
print("Signature header to send:", sig_header)
print("Message signed (first 200 chars):", message[:200])

headers = {
    "Content-Type": "application/json",
    "x-zm-request-timestamp": ts,
    "x-zm-signature": sig_header,
}

resp = requests.post(WEBHOOK_URL, headers=headers, data=body_json.encode("utf-8"))
print(resp.status_code, resp.text)
