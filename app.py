import os
import json
import requests
from flask import Flask, Response, jsonify

app = Flask(__name__)

BASE = "http://cf.egg-s10.xyz:80"
USER = "f7622b9dd016"
PASS = "0998a344f2"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

@app.route("/")
def home():
    return "Xtream Proxy Active"

@app.route("/channels")
def channels():
    try:
        # جلب التصنيفات
        cats = session.get(f"{BASE}/player_api.php?username={USER}&password={PASS}&action=get_live_categories", timeout=20).json()
        cat_map = {str(c.get("category_id")): c.get("category_name", "Other") for c in cats}

        # جلب القنوات
        streams = session.get(f"{BASE}/player_api.php?username={USER}&password={PASS}&action=get_live_streams", timeout=30).json()
        
        result = []
        for s in streams:
            sid = str(s.get("stream_id", ""))
            name = s.get("name", "")
            if not sid or not name or sid == "0":
                continue
            result.append({
                "id": sid,
                "name": name,
                "logo": s.get("stream_icon", ""),
                "group": cat_map.get(str(s.get("category_id", "")), "Other")
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stream/<path:sid>")
def stream(sid):
    url = f"{BASE}/live/{USER}/{PASS}/{sid}.m3u8"
    print(f"[+] Streaming: {url}")
    
    def generate():
        try:
            with session.get(url, stream=True, timeout=20) as r:
                r.raise_for_status()
                for chunk in r.iter_content(8192):
                    if chunk:
                        yield chunk
        except Exception as e:
            print(f"[!] Error: {e}")
    
    return Response(generate(), mimetype="application/vnd.apple.mpegurl")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
