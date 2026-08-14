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
        except Exception as e:
            logger.error(f"Cookie error: {e}")
            return secret_cookies
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

@app.route('/download', methods=['GET'])
def download():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    if 'pin.it' in url or 'pinterest' in url:
        try:
            res = requests.head(url, allow_redirects=True, timeout=5)
            url = res.url
        except Exception:
            pass

    cookie_path = setup_cookies()

    # إعدادات مخصصة لتجاوز حظر Datacenter IPs في Render
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'format': 'b[ext=mp4]/best[ext=mp4]/best' if mode == 'video' else 'ba[ext=m4a]/ba/best',
        'http_headers': {
            'User-Agent': USER_AGENT,
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb'],  # ios و mweb هما الأكثر نجاحاً مع سيرفرات Render
                'player_skip': ['webpage', 'configs'],
            }
        }
    }

    if cookie_path:
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Extraction returned empty'}), 500

            title = info.get('title', 'Video')
            download_url = info.get('url')

            if not download_url and 'formats' in info:
                formats = info['formats']
                if mode == 'audio':
                    audio_fmt = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                    if audio_fmt:
                        download_url = audio_fmt[-1].get('url')
                else:
                    prog_fmt = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') != 'none']
                    if prog_fmt:
                        download_url = prog_fmt[-1].get('url')

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title
                })
            else:
                return jsonify({'status': 'error', 'message': 'No direct stream URL found'}), 500

    except Exception as e:
        error_msg = str(e)
        logger.error(f"yt-dlp error: {error_msg}")
        return jsonify({'status': 'error', 'message': error_msg}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
