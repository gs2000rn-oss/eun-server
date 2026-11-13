import os
import json
import requests
from flask import Flask, Response, jsonify

app = Flask(__name__)

BASE = "http://cf.egg-s10.xyz:80"
USER = "f7622b9dd016"
PASS = "0998a344f2"

HEADERS_LIST = [
    {
        "User-Agent": "VLC/3.0.18 LibVLC/3.0.18",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Range": "bytes=0-"
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": BASE + "/",
        "Origin": BASE
    },
    {
        "User-Agent": "IPTVSmartersPro",
        "Accept": "*/*"
    },
    {
        "User-Agent": "TiviMate/4.6.0 (Linux;Android 11) ExoPlayerLib/2.18.1",
        "Accept": "*/*"
    }
]

@app.route("/")
def home():
    return "Aggressive Xtream Proxy"

@app.route("/channels")
def channels():
    try:
        with open("channels.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stream/<path:sid>")
def stream(sid):
    url = f"{BASE}/live/{USER}/{PASS}/{sid}.m3u8"
    print(f"[+] Trying: {url}")
    
    for i, headers in enumerate(HEADERS_LIST):
        try:
            print(f"[DEBUG] Attempt {i+1} with UA: {headers.get('User-Agent', '')[:40]}")
            r = requests.get(url, headers=headers, stream=True, timeout=20)
            print(f"[DEBUG] Status: {r.status_code}")
            if r.status_code == 200:
                print("[+] Success!")
                def generate():
                    for chunk in r.iter_content(8192):
                        if chunk:
                            yield chunk
                return Response(generate(), mimetype=r.headers.get("Content-Type", "application/vnd.apple.mpegurl"))
            r.close()
        except Exception as e:
            print(f"[!] Failed: {e}")
            continue
    
    return "All attempts failed", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
