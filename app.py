from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import shutil
import logging
import tempfile
import traceback
import requests
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def setup_cookies():
    secret = '/etc/secrets/cookies.txt'
    tmp = '/tmp/cookies.txt'
    if os.path.exists(secret):
        try:
            shutil.copy(secret, tmp)
            return tmp
        except:
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


def resolve_url(url):
    try:
        if any(x in url for x in ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co', 'bit.ly']):
            r = requests.head(url, allow_redirects=True, timeout=10,
                              headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            return r.url
    except:
        pass
    return url


@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '7.0',
        'usage': '/download?url=LINK'
    })


@app.route('/health')
def health():
    c = setup_cookies()
    ok = bool(c and os.path.exists(c))
    return jsonify({
        'status': 'ok',
        'cookies_found': ok,
        'cookies_size': os.path.getsize(c) if ok else 0
    })


@app.route('/download', methods=['GET', 'POST'])
def download():
    url = request.args.get('url') or request.form.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'أضف ?url=الرابط'}), 400

    url = resolve_url(url)
    logger.info(f"Downloading: {url}")

    cookie = setup_cookies()
    temp_dir = tempfile.mkdtemp(prefix='dl_')

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'outtmpl': os.path.join(temp_dir, 'video.%(ext)s'),
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {'player_client': ['android', 'web', 'mweb']},
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

    # Headers خاصة
    if 'pinterest' in url or 'pin.it' in url:
        ydl_opts['http_headers']['Referer'] = 'https://www.pinterest.com/'
    elif 'twitter.com' in url or 'x.com' in url:
        ydl_opts['http_headers']['Referer'] = 'https://x.com/'
    elif 'instagram.com' in url:
        ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'

    if cookie:
        ydl_opts['cookiefile'] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            files = [f for f in Path(temp_dir).rglob('*') if f.is_file() and f.stat().st_size > 8000]
            if not files:
                raise Exception('ما نزل ملف صالح')

            filename = str(max(files, key=lambda p: p.stat().st_size))
            size_mb = os.path.getsize(filename) / (1024*1024)
            duration = info.get('duration') or 0

            logger.info(f"OK: {size_mb:.2f}MB | {duration}s")

            if size_mb < 0.06:
                return jsonify({'status': 'error', 'message': f'ملف صغير جداً ({size_mb:.2f}MB)'}), 500

            title = (info.get('title') or 'video')[:50]
            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
            
            return send_file(
                filename,
                as_attachment=True,
                download_name=safe + '.mp4',
                mimetype='video/mp4'
            )

    except Exception as e:
        err = str(e)
        logger.error(err)
        if 'Sign in to confirm' in err or 'not a bot' in err.lower():
            msg = 'YouTube Bot — أعد تصدير cookies.txt'
        elif '404' in err:
            msg = 'الرابط غير موجود أو Pinterest/Twitter حجب'
        else:
            msg = err[:350]
        return jsonify({'status': 'error', 'message': msg}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
