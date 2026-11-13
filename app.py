import os
import requests
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

def get_stalker_token():
    auth_url = f"{PORTAL_URL}/stalker_portal/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js"
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
    }
    try:
        print(f"[DEBUG] Handshake URL: {auth_url}")
        response = requests.get(auth_url, headers=headers, timeout=15)
        print(f"[DEBUG] Status: {response.status_code}")
        print(f"[DEBUG] Response: {response.text[:500]}")
        data = response.json()
        token = data.get('js', {}).get('token')
        print(f"[DEBUG] Token: {token}")
        return token
    except Exception as e:
        print(f"[!] Error getting token: {e}")
        return None

@app.route('/')
def home():
    return f"MAC Restream Proxy for {MAC_ADDRESS} is Active and Running Successfully!"

@app.route('/channels')
def get_channels():
    token = get_stalker_token()
    if not token:
        return jsonify({"error": "Could not authenticate"}), 500

    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Authorization': f"Bearer {token}",
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
    }

    try:
        genres_url = f"{PORTAL_URL}/stalker_portal/server/load.php?type=itv&action=get_genres&mac={MAC_ADDRESS}"
        genres_resp = requests.get(genres_url, headers=headers, timeout=15)
        genres_data = genres_resp.json()
        
        genre_map = {}
        genre_list = genres_data.get('js', []) if isinstance(genres_data.get('js'), list) else genres_data.get('genre', [])
        if isinstance(genre_list, list):
            for g in genre_list:
                gid = str(g.get('id', ''))
                title = g.get('title', 'Other')
                if gid:
                    genre_map[gid] = title

        channels_url = f"{PORTAL_URL}/stalker_portal/server/load.php?type=itv&action=get_all_channels&mac={MAC_ADDRESS}"
        ch_resp = requests.get(channels_url, headers=headers, timeout=20)
        ch_data = ch_resp.json()
        
        raw_channels = []
        js_part = ch_data.get('js', {})
        if isinstance(js_part, dict):
            raw_channels = js_part.get('data', [])
        elif isinstance(js_part, list):
            raw_channels = js_part

        result = []
        seen = set()
        for c in raw_channels:
            cid = str(c.get('id', ''))
            if not cid or cid in seen:
                continue
            seen.add(cid)
            
            name = c.get('name', 'Unknown')
            logo = c.get('logo', '')
            genre_id = str(c.get('tv_genre_id', ''))
            group = genre_map.get(genre_id, c.get('tv_genre_name', 'Other'))
            
            result.append({
                "id": cid,
                "name": name,
                "logo": logo,
                "group": group or "Other"
            })

        return jsonify(result)

    except Exception as e:
        print(f"[!] Error fetching channels: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/stream/<path:cmd>')
def stream_proxy(cmd):
    print(f"[+] User requested command/channel: {cmd}")
    
    token = get_stalker_token()
    if not token:
        return "Error: Could not authenticate with MAC address", 500

    link_url = f"{PORTAL_URL}/stalker_portal/server/load.php?type=itv&action=create_link&cmd={cmd}&mac={MAC_ADDRESS}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Authorization': f"Bearer {token}",
        'Cookie': f'mac={MAC_ADDRESS}; stb_lang=en; timezone=Europe/Paris'
    }
    
    try:
        link_response = requests.get(link_url, headers=headers, timeout=10)
        link_data = link_response.json()
        real_stream_url = link_data.get('js', {}).get('cmd')
        
        if not real_stream_url:
            return "Error: Could not fetch real stream URL", 404
            
        if real_stream_url.startswith('ffmpeg '):
            real_stream_url = real_stream_url.replace('ffmpeg ', '')

        print(f"[+] Real Stream URL: {real_stream_url}")

        def generate():
            try:
                with requests.get(real_stream_url, stream=True, timeout=15) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            yield chunk
            except Exception as e:
                print(f"[!] Error streaming content: {e}")

        return Response(generate(), mimetype='video/mp2t')

    except Exception as e:
        print(f"[!] Error processing stream request: {e}")
        return f"Internal Server Error: {str(e)}", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
