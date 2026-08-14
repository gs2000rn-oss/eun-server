from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import shutil
import logging
import tempfile
import traceback
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

def resolve_short_url(url):
    try:
        import requests
        shorts = ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co']
        if any(d in url for d in shorts):
            r = requests.head(url, allow_redirects=True, timeout=10,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            if r.url != url:
                return r.url
    except:
        pass
    return url

@app.route('/')
def home():
    return jsonify({'status': 'online', 'version': '12-real-mp4'})

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
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL'}), 400

    url = resolve_short_url(url)
    logger.info(f"FULL REAL DOWNLOAD: {url}")

    is_pin = 'pinterest' in url or 'pin.it' in url
    is_ig = 'instagram' in url
    is_tw = 'twitter' in url or 'x.com' in url
    is_yt = 'youtube' in url or 'youtu.be' in url

    temp_dir = tempfile.mkdtemp(prefix='dl_')
    outtmpl = os.path.join(temp_dir, 'out.%(ext)s')

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 40,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

    if is_pin:
        ydl_opts['http_headers']['Referer'] = 'https://www.pinterest.com/'
        ydl_opts['format'] = 'best/bestvideo+bestaudio'
    if is_ig:
        ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'
    if is_tw:
        ydl_opts['http_headers']['Referer'] = 'https://x.com/'
    if is_yt:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'android_sdkless', 'web', 'mweb', 'tv']
            }
        }
        ydl_opts['format'] = 'best[height<=720]/bestvideo[height<=720]+bestaudio/best'

    cookie = setup_cookies()
    if cookie:
        ydl_opts['cookiefile'] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            files = [f for f in Path(temp_dir).rglob('*') if f.is_file() and f.stat().st_size > 80000]
            if not files:
                return jsonify({'status': 'error', 'message': 'File too small or empty'}), 500

            filepath = str(max(files, key=lambda p: p.stat().st_size))
            size = os.path.getsize(filepath)
            title = (info.get('title') or 'video')[:50]
            duration = info.get('duration') or 0

            logger.info(f"READY: {size/1024/1024:.2f}MB | {duration}s")

            # نرجع الملف مباشرة كـ MP4 (التطبيق الجديد يتعامل معه)
            safe_name = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title)[:40] + '.mp4'

            return send_file(
                filepath,
                mimetype='video/mp4',
                as_attachment=True,
                download_name=safe_name
            )

    except Exception as e:
        logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': str(e)[:350]}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
