from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil
import logging
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

def setup_cookies():
    secret_cookies = '/etc/secrets/cookies.txt'
    tmp_cookies = '/tmp/cookies.txt'
    if os.path.exists(secret_cookies):
        try:
            shutil.copy(secret_cookies, tmp_cookies)
            return tmp_cookies
        except Exception:
            return secret_cookies
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

def fetch_via_cobalt_engine(url, mode):
    """محرك احتياطي داخلي يتجاوز حظر يوتيوب لـ Render IPs"""
    nodes = [
        "https://cobalt-api.kwiatek.xyz",
        "https://api.cobalt.tools",
        "https://cobalt.canine.tools"
    ]
    payload = {
        "url": url,
        "videoQuality": "720",
        "downloadMode": "audio" if mode == "audio" else "auto"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }
    
    for node in nodes:
        try:
            res = requests.post(f"{node}/", json=payload, headers=headers, timeout=7)
            if res.status_code == 200:
                data = res.json()
                if "url" in data:
                    return data["url"], "YouTube Video (Fast Engine)"
                elif "picker" in data and len(data["picker"]) > 0:
                    return data["picker"][0]["url"], "YouTube Video (Fast Engine)"
        except Exception as e:
            logger.error(f"Fallback node failed: {e}")
    return None, None

@app.route('/download', methods=['GET'])
def download():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 200

    cookie_path = setup_cookies()

    # 1. المحاولة الأولى باستخدام yt-dlp
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'http_headers': {'User-Agent': USER_AGENT},
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb', 'android'],
            }
        }
    }
    if cookie_path:
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                title = info.get('title', 'Downloaded Media')
                download_url = None
                formats = info.get('formats', [])

                if mode == 'audio':
                    audio_fmt = [f for f in formats if f.get('acodec') != 'none' and (not f.get('vcodec') or f.get('vcodec') == 'none')]
                    if audio_fmt:
                        download_url = audio_fmt[-1].get('url')
                else:
                    prog_fmt = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
                    if prog_fmt:
                        download_url = prog_fmt[-1].get('url')

                if not download_url:
                    download_url = info.get('url')

                if download_url:
                    return jsonify({'status': 'success', 'url': download_url, 'title': title}), 200
    except Exception as e:
        logger.error(f"yt-dlp error on Render: {str(e)}")

    # 2. المحاولة الثانية (الخطة B تلقائياً من داخل السيرفر):
    logger.info("Switching to internal fallback engine...")
    fallback_url, fallback_title = fetch_via_cobalt_engine(url, mode)
    if fallback_url:
        return jsonify({'status': 'success', 'url': fallback_url, 'title': fallback_title}), 200

    # ارجاع 200 دائماً لكي يقرأ الأندرويد رسالة JSON بوضوح
    return jsonify({
        'status': 'error',
        'message': 'YouTube blocked the extraction. Please try again.'
    }), 200

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine Pro'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
