from flask import Flask, request, jsonify, Response, stream_with_context
import yt_dlp
import os
import shutil
import logging
import requests
from urllib.parse import quote, unquote

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def setup_cookies():
    """نسخ ملف الكوكيز إلى مجلد /tmp القابل للكتابة لتفادي خطأ Read-only system"""
    secret_cookies = '/etc/secrets/cookies.txt'
    tmp_cookies = '/tmp/cookies.txt'
    
    if os.path.exists(secret_cookies):
        try:
            shutil.copy(secret_cookies, tmp_cookies)
            logger.info("Successfully copied cookies to /tmp/cookies.txt")
            return tmp_cookies
        except Exception as e:
            logger.error(f"Failed to copy cookies: {e}")
            return secret_cookies
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # فك روابط Pinterest المختصرة
    if 'pin.it' in url or 'pinterest' in url:
        try:
            response = requests.head(url, allow_redirects=True, timeout=5)
            url = response.url
            logger.info(f"Resolved Pinterest URL: {url}")
        except Exception as e:
            logger.error(f"Failed to resolve shortlink: {e}")

    logger.info(f"Processing URL: {url} | Mode: {mode}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'tv_embedded', 'ios', 'android'],
                'skip': ['webpage', 'configs']
            }
        }
    }

    cookie_file = setup_cookies()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract media'}), 500

            title = info.get('title', 'Downloaded_Media')
            formats = info.get('formats', [])

            direct_url = None

            if mode == 'audio':
                # البحث عن مسار صوتي نقي
                audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                if audio_formats:
                    audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                    direct_url = audio_formats[0].get('url')
            else:
                # البحث عن مسار مدمج بصوت وصورة معاً
                combo_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
                if combo_formats:
                    combo_formats.sort(key=lambda x: x.get('height', 0) or 0, reverse=True)
                    direct_url = combo_formats[0].get('url')

            if not direct_url:
                direct_url = info.get('url')

            if direct_url:
                # بدل إرجاع رابط googlevideo الذي يسبب 403 على الهاتف،
                # نرجّع رابط البروكسي الخاص بسيرفرنا ليتم التحميل عن طريقه مباشرة
                host_url = request.host_url.rstrip('/')
                proxy_url = f"{host_url}/proxy?stream_url={quote(direct_url)}"

                return jsonify({
                    'status': 'success',
                    'url': proxy_url,
                    'title': title
                })
            else:
                return jsonify({'status': 'error', 'message': 'No valid playable link found'}), 500

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500


@app.route('/proxy', methods=['GET'])
def proxy_stream():
    """هذه الدالة تعمل كجسر لنقل البيانات المباشرة من يوتيوب للهاتف لتفادي حظر 403"""
    stream_url = request.args.get('stream_url')
    if not stream_url:
        return "No stream URL provided", 400

    target_url = unquote(stream_url)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }

    try:
        req = requests.get(target_url, headers=headers, stream=True, timeout=20)
        
        def generate():
            for chunk in req.iter_content(chunk_size=1024 * 64):
                if chunk:
                    yield chunk

        response = Response(stream_with_context(generate()), content_type=req.headers.get('Content-Type', 'video/mp4'))
        if 'Content-Length' in req.headers:
            response.headers['Content-Length'] = req.headers['Content-Length']
        return response

    except Exception as e:
        logger.error(f"Proxy streaming failed: {e}")
        return f"Proxy error: {str(e)}", 500


@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '4.0'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
