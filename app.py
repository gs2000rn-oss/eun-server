import os
import json
import requests
from flask import Flask, Response, jsonify

app = Flask(__name__)

BASE = "http://cf.egg-s10.xyz:80"
USER = "f7622b9dd016"
PASS = "0998a344f2"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "VLC/3.0.18 LibVLC/3.0.18",
    "Lavf/60.3.100",
    "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
    "IPTVSmartersPro",
    "TiviMate/4.6.0",
    "Perfect Player/1.5.8"
]

def get_session(ua=None):
    s = requests.Session()
    s.headers.update({
        "User-Agent": ua or USER_AGENTS[0],
        "Accept": "*/*",
        "Connection": "Keep-Alive"
    })
    return s

@app.route("/")
def home():
    return "Xtream Proxy Active - Multi UA"

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
    print(f"[+] Streaming: {url}")
    
    for ua in USER_AGENTS:
        try:
            print(f"[DEBUG] Trying UA: {ua[:50]}...")
            session = get_session(ua)
            r = session.get(url, stream=True, timeout=15)
            if r.status_code == 200:
                print(f"[+] Success with UA")
                def generate():
                    try:
                        for chunk in r.iter_content(8192):
                            if chunk:
                                yield chunk
                    except Exception as e:
                        print(f"[!] Stream error: {e}")
                return Response(generate(), mimetype="application/vnd.apple.mpegurl")
            else:
                print(f"[!] Status {r.status_code} with this UA")
                r.close()
        except Exception as e:
            print(f"[!] Failed with UA: {e}")
            continue
    
    return "All User-Agents failed", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
