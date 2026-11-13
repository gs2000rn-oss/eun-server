import os
import json
import requests
from flask import Flask, Response, request, jsonify
from urllib.parse import quote

app = Flask(__name__)

PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

# إنشاء جلسة متطورة تحاكي جهاز STB حقيقي
session = requests.Session()

def get_stalker_token():
    # بارامترات جهاز MAG المحاكى بدقة فائقة
    base_params = f"mac={MAC_ADDRESS}&stb_type=MAG250&version=2.18-r12-250&image_version=218&serial=001A790029C2&hw_version=1.6-BD-02&device_id=1234567890ABCDEF1234567890ABCDEF&device_id2=1234567890ABCDEF1234567890ABCDEF"
    
    urls = [
        f"{PORTAL_URL}/stalker_portal/server/load.php?type=stb&action=handshake&{base_params}&js=1",
        f"{PORTAL_URL}/server/load.php?type=stb&action=handshake&{base_params}&js=1",
        f"{PORTAL_URL}/stalker_portal/server/load.php?type=stb&action=get_profile&{base_params}",
        f"{PORTAL_URL}/server/load.php?type=stb&action=get_profile&{base_params}"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Referer': f"{PORTAL_URL}/stalker_portal/c/",
        'Origin': PORTAL_URL,
        'Accept': '*/*',
        'Connection': 'Keep-Alive',
        'Accept-Language': 'en,*;'
    }
    
    # ضبط الكوكيز الأولية للجلسة
    session.cookies.set('mac', MAC_ADDRESS, domain=PORTAL_URL.replace('http://', '').replace('https://', '').split('/')[0])
    session.cookies.set('stb_lang', 'en')
    session.cookies.set('timezone', 'Europe/Paris')

    for url in urls:
        try:
            print(f"[ULTIMATE DEBUG] Trying URL: {url}")
            r = session.get(url, headers=headers, timeout=20)
            print(f"[ULTIMATE DEBUG] Status: {r.status_code} | Text: {r.text[:300]}")
            
            if r.status_code == 200:
                try:
                    data = r.json()
                    # البحث عن التوكن في أكثر من مكان محتمل في استجابة البوابة
                    token = data.get('js', {}).get('token')
                    if not token and isinstance(data.get('js'), str):
                        token = data.get('js')
                    if not token:
                        token = data.get('token')
                        
                    if token:
                        print(f"[ULTIMATE SUCCESS] Token obtained: {token}")
                        return token
                except Exception as je:
                    print(f"[!] JSON parse error: {je}")
        except Exception as e:
            print(f"[!] Connection error: {e}")
            
    return None

@app.route('/')
def home():
    return f"Ultimate MAG Restream Proxy for {MAC_ADDRESS} is Active!"

@app.route('/channels')
def get_channels():
    try:
        if os.path.exists('channels.json'):
            with open('channels.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        else:
            return jsonify({"error": "channels.json not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stream/<path:cmd>')
def stream_proxy(cmd):
    print(f"[+] Ultimate Stream Request for CMD: {cmd}")
    
    token = get_stalker_token()
    if not token:
        print("[!] Ultimate Error: Authentication failed completely")
        return "Error: Authentication failed with portal", 500

    encoded_cmd = quote(cmd, safe='')
    
    link_urls = [
        f"{PORTAL_URL}/stalker_portal/server/load.php?type=itv&action=create_link&cmd={encoded_cmd}&mac={MAC_ADDRESS}&forced_storage=0",
        f"{PORTAL_URL}/server/load.php?type=itv&action=create_link&cmd={encoded_cmd}&mac={MAC_ADDRESS}&forced_storage=0",
        f"{PORTAL_URL}/stalker_portal/server/load.php?type=itv&action=create_link&cmd={encoded_cmd}&mac={MAC_ADDRESS}",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Authorization': f"Bearer {token}",
        'Referer': f"{PORTAL_URL}/stalker_portal/c/",
        'Origin': PORTAL_URL,
        'Accept': '*/*'
    }
    
    real_stream_url = None
    for link_url in link_urls:
        try:
            print(f"[ULTIMATE DEBUG] Requesting Link: {link_url}")
            link_resp = session.get(link_url, headers=headers, timeout=15)
            print(f"[ULTIMATE DEBUG] Link Status: {link_resp.status_code} | Text: {link_resp.text[:300]}")
            
            if link_resp.status_code == 200:
                try:
                    link_data = link_resp.json()
                    js_obj = link_data.get('js')
                    if isinstance(js_obj, dict):
                        real_stream_url = js_obj.get('cmd')
                    elif isinstance(js_obj, str):
                        real_stream_url = js_obj
                    elif isinstance(link_data.get('cmd'), str):
                        real_stream_url = link_data.get('cmd')
                        
                    if real_stream_url:
                        break
                except Exception as je:
                    print(f"[!] JSON Link parse error: {je}")
        except Exception as e:
            print(f"[!] Link connection error: {e}")
            
    if not real_stream_url:
        print("[!] Ultimate Error: Could not resolve real stream URL")
        return "Error: Could not retrieve stream URL from portal", 404
        
    if real_stream_url.startswith('ffmpeg '):
        real_stream_url = real_stream_url.replace('ffmpeg ', '').strip()
    if real_stream_url.startswith('auto '):
        real_stream_url = real_stream_url.replace('auto ', '').strip()

    print(f"[+] Ultimate Resolved Stream URL: {real_stream_url}")

    def generate():
        try:
            with session.get(real_stream_url, stream=True, timeout=25, headers={'User-Agent': 'VLC/3.0.18', 'Accept': '*/*'}) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except Exception as e:
            print(f"[!] Streaming transmission exception: {e}")

    return Response(generate(), mimetype='video/mp2t')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
