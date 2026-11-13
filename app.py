import os
import json
import requests
import time
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

PROXIES = {
    "http": "http://82.25.90.240:3128",
    "https": "http://82.25.90.240:3128",
}

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
    'X-User-Agent': 'Model: MAG250; Link: WiFi',
    'Accept': '*/*',
    'Connection': 'Keep-Alive',
    'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
})

def get_stalker_token():
    urls = [
        f"{PORTAL_URL}/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js",
    ]
    for attempt in range(3):
        for url in urls:
            try:
                print(f"[DEBUG] Attempt {attempt+1} Handshake via proxy")
                r = session.get(url, timeout=25, proxies=PROXIES)
                print(f"[DEBUG] Status: {r.status_code}")
                if r.status_code == 200 and r.text.strip().startswith('{'):
                    data = r.json()
                    token = data.get('js', {}).get('token')
                    if token:
                        print(f"[DEBUG] Token success: {token}")
                        return token
            except Exception as e:
                print(f"[!] Handshake error: {e}")
        time.sleep(2)
    return None

@app.route('/')
def home():
    return f"MAC Restream Proxy for {MAC_ADDRESS} is Active and Running Successfully!"

@app.route('/channels')
def get_channels():
    try:
        with open('channels.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stream/<path:cmd>')
def stream_proxy(cmd):
    print(f"[+] Stream request: {cmd}")
    
    token = get_stalker_token()
    if not token:
        return "Error: Authentication failed", 500

    cmd_clean = cmd
    if not cmd.startswith('ffmpeg') and not cmd.startswith('http'):
        cmd_clean = f"ffmpeg http://localhost/ch/{cmd}_"

    link_url = f"{PORTAL_URL}/server/load.php?type=itv&action=create_link&cmd={requests.utils.quote(cmd_clean)}&mac={MAC_ADDRESS}"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
    }
    
    try:
        link_resp = session.get(link_url, headers=headers, timeout=15, proxies=PROXIES)
        if link_resp.status_code != 200:
            return f"Error: Create link failed ({link_resp.status_code})", 500
            
        link_data = link_resp.json()
        real_url = link_data.get('js', {}).get('cmd', '')
        
        if real_url.startswith('ffmpeg '):
            real_url = real_url[7:].strip()
        if real_url.startswith('auto '):
            real_url = real_url[5:].strip()
            
        if not real_url or not real_url.startswith('http'):
            return "Error: Invalid stream URL", 404

        print(f"[+] Playing: {real_url}")

        def generate():
            try:
                with session.get(real_url, stream=True, timeout=20, proxies=PROXIES) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk
            except Exception as e:
                print(f"[!] Stream error: {e}")

        return Response(generate(), mimetype='video/mp2t')

    except Exception as e:
        print(f"[!] Stream proxy error: {e}")
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
