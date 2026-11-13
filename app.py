import os
import requests
from flask import Flask, Response, request

app = Flask(__name__)

# إعدادات بوابة Stalker الخاصة بك والماك المطلوب
PORTAL_URL = "http://pro.abct.shop"
MAC_ADDRESS = "00:1A:79:00:29:C2"

# دالة للحصول على توكن المصادقة من البوابة باستخدام الماك
def get_stalker_token():
    auth_url = f"{PORTAL_URL}/stalker_portal/server/load.php?type=stb&action=handshake&mac={MAC_ADDRESS}&version=js"
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi'
    }
    try:
        response = requests.get(auth_url, headers=headers, timeout=10)
        data = response.json()
        token = data.get('js', {}).get('token')
        return token
    except Exception as e:
        print(f"[!] Error getting token: {e}")
        return None

@app.route('/')
def home():
    return f"MAC Restream Proxy for {MAC_ADDRESS} is Active and Running Successfully!"

@app.route('/stream/<path:cmd>')
def stream_proxy(cmd):
    print(f"[+] User requested command/channel: {cmd}")
    
    # 1. الحصول على التوكن النشط
    token = get_stalker_token()
    if not token:
        return "Error: Could not authenticate with MAC address", 500

    # 2. طلب رابط البث الفعلي (Link) باستخدام الـ CMD الخاص بالقناة
    link_url = f"{PORTAL_URL}/stalker_portal/server/load.php?type=itv&action=create_link&cmd={cmd}&mac={MAC_ADDRESS}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Authorization': f"Bearer {token}"
    }
    
    try:
        link_response = requests.get(link_url, headers=headers, timeout=10)
        link_data = link_response.json()
        real_stream_url = link_data.get('js', {}).get('cmd')
        
        if not real_stream_url:
            return "Error: Could not fetch real stream URL", 404
            
        # إذا كان الرابط يبدأ بـ ffmpeg، نقوم بتنقيته للحصول على رابط البث المباشر
        if real_stream_url.startswith('ffmpeg '):
            real_stream_url = real_stream_url.replace('ffmpeg ', '')

        print(f"[+] Real Stream URL: {real_stream_url}")

        # 3. فتح اتصال واحد فقط بالمصدر الأصلي وبدء التدفق للمستخدمين
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
