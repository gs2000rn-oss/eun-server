import os
import json
import requests
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

PROXIES = {
    "http": "http://41.65.103.168:8080",
    "https": "http://41.65.103.168:8080",
}

def get_stalker_token():
    urls = [
        f"{PORTAL_URL}/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js",
    ]
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris',
        'Accept': '*/*'
    }
    for url in urls:
        try:
            print(f"[DEBUG] Handshake via proxy: {url}")
            r = requests.get(url, headers=headers, timeout=25, proxies=PROXIES)
            print(f"[DEBUG] Status: {r.status_code}")
            if r.status_code == 200 and r.text.strip().startswith('{'):
                data = r.json()
                token = data.get('js', {}).get('token')
                if token:
                    print(f"[DEBUG] Token OK: {token}")
                    return token
        except Exception as e:
            print(f"[!] Handshake failed: {e}")
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
    print(f"[+] User requested: {cmd}")
    
    token = get_stalker_token()
    if not token:
        return "Error: Could not authenticate", 500

    link_url = f"{PORTAL_URL}/server/load.php?type=itv&action=create_link&cmd={cmd}&mac={MAC_ADDRESS}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Authorization': f"Bearer {token}",
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
    }
    
    try:
        link_response = requests.get(link_url, headers=headers, timeout=15, proxies=PROXIES)
        link_data = link_response.json()
        real_stream_url = link_data.get('js', {}).get('cmd')
        
        if not real_stream_url:
            return "Error: Could not fetch stream URL", 404
            
        if real_stream_url.startswith('ffmpeg '):
            real_stream_url = real_stream_url.replace('ffmpeg ', '')

        print(f"[+] Real Stream URL: {real_stream_url}")

        def generate():
            try:
                with requests.get(real_stream_url, stream=True, timeout=20, proxies=PROXIES) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            yield chunk
            except Exception as e:
                print(f"[!] Stream error: {e}")

        return Response(generate(), mimetype='video/mp2t')

    except Exception as e:
        print(f"[!] Error: {e}")
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
