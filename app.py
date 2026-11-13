import os
import json
from flask import Flask, jsonify, redirect

app = Flask(__name__)

BASE = "http://cf.egg-s10.xyz:80"
USER = "f7622b9dd016"
PASS = "0998a344f2"

@app.route("/")
def home():
    return "Xtream Redirect Proxy on Render"

@app.route("/channels")
def channels():
    try:
        with open("channels.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stream/<path:sid>")
def stream(sid):
    original = f"{BASE}/live/{USER}/{PASS}/{sid}.m3u8"
    return redirect(original, code=302)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
