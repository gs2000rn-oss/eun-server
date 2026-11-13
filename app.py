import os
import json
import requests
import time
from flask import Flask, Response, jsonify

app = Flask(__name__)

PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
    "X-User-Agent": "Model: MAG250; Link: WiFi",
    "Accept": "*/*",
    "Connection": "Keep-Alive",
    "Cookie": f"mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris"
})

def get_token():
    url = f"{PORTAL_URL}/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js"
    for i in range(3):
        try:
            print(f"[DEBUG] Handshake attempt {i+1}")
            r = session.get(url, timeout=20)
            print(f"[DEBUG] Status: {r.status_code}")
            print(f"[DEBUG] Response: {r.text[:200]}")
            if r.status_code == 200 and r.text.strip().startswith("{"):
                data = r.json()
                token = data.get("js", {}).get("token")
                if token:
                    print(f"[DEBUG] Token: {token}")
                    return token
        except Exception as e:
            print(f"[!] Handshake error: {e}")
        time.sleep(1)
    return None

@app.route("/")
def home():
    return f"MAC Restream Proxy for {MAC_ADDRESS} is Active and Running Successfully!"

@app.route("/channels")
def channels():
    try:
        with open("channels.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stream/<path:cmd>")
def stream(cmd):
    print(f"[+] Requested: {cmd}")
    token = get_token()
    if not token:
        return "Authentication failed", 500

    if not cmd.startswith("ffmpeg") and not cmd.startswith("http"):
        cmd = f"ffmpeg http://localhost/ch/{cmd}_"

    link_url = f"{PORTAL_URL}/server/load.php?type=itv&action=create_link&cmd={requests.utils.quote(cmd)}&mac={MAC_ADDRESS}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        print(f"[DEBUG] Create link: {link_url}")
        r = session.get(link_url, headers=headers, timeout=15)
        print(f"[DEBUG] Create link status: {r.status_code}")
        print(f"[DEBUG] Create link body: {r.text[:300]}")

        if r.status_code != 200:
            return f"Create link failed: {r.status_code}", 500

        data = r.json()
        real = data.get("js", {}).get("cmd", "")
        if real.startswith("ffmpeg "):
            real = real[7:].strip()
        if real.startswith("auto "):
            real = real[5:].strip()

        if not real.startswith("http"):
            return "Invalid stream URL", 404

        print(f"[+] Stream URL: {real}")

        def generate():
            try:
                with session.get(real, stream=True, timeout=20) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(8192):
                        if chunk:
                            yield chunk
            except Exception as e:
                print(f"[!] Stream error: {e}")

        return Response(generate(), mimetype="video/mp2t")

    except Exception as e:
        print(f"[!] Error: {e}")
        return f"Error: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
