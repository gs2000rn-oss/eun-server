import os
import json
import requests
import time
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

# قائمة بروكسيات للتجربة
PROXY_LIST = [
    "http://205.178.137.217:8443",
    "http://84.17.47.147:9002",
    "http://192.95.37.111:443",
    "http://188.226.195.20:8881",
    "http://154.26.139.27:443",
    "http://172.191.23.249:443",
    "http://160.16.144.120:443",
    "http://206.223.183.16:9443",
    "http://198.44.142.27:9443",
    "http://149.88.98.65:9443",
    "http://47.254.229.162:443",
    "http://41.77.155.164:443",
    "http://91.227.97.113:443",
    "http://35.228.73.198:443",
    "http://132.145.152.188:443",
    "http://193.233.75.115:443",
    "http://51.38.179.176:443",
    "http://20.7.147.69:443",
    "http://165.22.60.108:443",
    "http://13.232.233.63:443",
]

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
    'X-User-Agent': 'Model: MAG250; Link: WiFi',
    'Accept': '*/*',
    'Connection': 'Keep-Alive',
    'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
})

working_proxy = None

def get_working_proxy():
    global working_proxy
    if working_proxy:
        return working_proxy
    
    test_url = f"{PORTAL_URL}/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js"
    for proxy in PROXY_LIST:
        try:
            print(f"[DEBUG] Testing proxy: {proxy}")
            r = requests.get(test_url, timeout=15, proxies={"http": proxy, "https": proxy})
            if r.status_code == 200 and r.text.strip().startswith('{'):
                data = r.json()
                if data.get('js', {}).get('token'):
                    print(f"[DEBUG] Working proxy found: {proxy}")
                    working_proxy = proxy
                    return proxy
        except Exception as e:
            print(f"[!] Proxy failed: {proxy} - {e}")
            continue
    return None

def get_stalker_token():
    proxy = get_working_proxy()
    if not proxy:
        return None
    
    proxies = {"http": proxy, "https": proxy}
    url = f"{PORTAL_URL}/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js"
    
    for attempt in range(2):
        try:
            r = session.get(url, timeout=20, proxies=proxies)
            if r.status_code == 200 and r.text.strip().startswith('{'):
                data = r.json()
                token = data.get('js', {}).get('token')
                if token:
                    return token
        except Exception as e:
            print(f"[!] Token error: {e}")
        time.sleep(1)
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

    proxy = get_working_proxy()
    proxies = {"http": proxy, "https": proxy} if proxy else None

    cmd_clean = cmd
    if not cmd.startswith('ffmpeg') and not cmd.startswith('http'):
        cmd_clean = f"ffmpeg http://localhost/ch/{cmd}_"

    link_url = f"{PORTAL_URL}/server/load.php?type=itv&action=create_link&cmd={requests.utils.quote(cmd_clean)}&mac={MAC_ADDRESS}"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
    }
    
    try:
        link_resp = session.get(link_url, headers=headers, timeout=15, proxies=proxies)
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
                with session.get(real_url, stream=True, timeout=20, proxies=proxies) as r:
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
