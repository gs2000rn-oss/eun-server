import os
import json
import requests
from flask import Flask, Response, request, jsonify
from urllib.parse import quote

app = Flask(__name__)

PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

def get_stalker_token():
    urls = [
        f"{PORTAL_URL}/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js",
        f"{PORTAL_URL}/stalker_portal/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js",
    ]
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris',
        'Accept': '*/*',
        'Connection': 'Keep-Alive'
    }
    for url in urls:
        try:
            print(f"[DEBUG] Handshake URL: {url}")
            r = requests.get(url, headers=headers, timeout=20)
            print(f"[DEBUG] Handshake Status: {r.status_code} | Response: {r.text[:300]}")
            
            if r.status_code == 200 and r.text.strip().startswith('{'):
                data = r.json()
                token = data.get('js', {}).get('token')
                if token:
                    print(f"[DEBUG] Token OK: {token}")
                    return token
        except Exception as e:
            print(f"[!] Handshake failed with exception: {e}")
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
        return "Error: Could not authenticate (Check Render logs for handshake response)", 500

    encoded_cmd = quote(cmd, safe='')
    
    link_urls = [
        f"{PORTAL_URL}/server/load.php?type=itv&action=create_link&cmd={encoded_cmd}&mac={MAC_ADDRESS}",
        f"{PORTAL_URL}/stalker_portal/server/load.php?type=itv&action=create_link&cmd={encoded_cmd}&mac={MAC_ADDRESS}"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Authorization': f"Bearer {token}",
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris',
        'Referer': f"{PORTAL_URL}/stalker_portal/c/"
    }
    
    real_stream_url = None
    for link_url in link_urls:
        try:
            print(f"[DEBUG] Trying link URL: {link_url}")
            link_response = requests.get(link_url, headers=headers, timeout=10)
            print(f"[DEBUG] Link Response Code: {link_response.status_code} | Text: {link_response.text[:200]}")
            
            if link_response.status_code == 200 and link_response.text.strip().startswith('{'):
                link_data = link_response.json()
                js_obj = link_data.get('js')
                if isinstance(js_obj, dict):
                    real_stream_url = js_obj.get('cmd')
                elif isinstance(js_obj, str):
                    real_stream_url = js_obj
                
                if real_stream_url:
                    break
        except Exception as e:
            print(f"[!] Error trying link URL {link_url}: {e}")
            
    if not real_stream_url:
        return "Error: Could not fetch stream URL from portal (403 or Invalid response)", 404
        
    if real_stream_url.startswith('ffmpeg '):
        real_stream_url = real_stream_url.replace('ffmpeg ', '').strip()
    if real_stream_url.startswith('auto '):
        real_stream_url = real_stream_url.replace('auto ', '').strip()

    print(f"[+] Real Stream URL: {real_stream_url}")

    def generate():
        try:
            with requests.get(real_stream_url, stream=True, timeout=15, headers={'User-Agent': 'VLC/3.0.18'}) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except Exception as e:
            print(f"[!] Stream error: {e}")

    return Response(generate(), mimetype='video/mp2t')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
