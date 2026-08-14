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
        except Exception as e:
            logger.error(f"Copy cookies error: {e}")
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'service': 'Universal Media Downloader',
        'version': '5.0-multi',
        'supports': ['YouTube', 'TikTok', 'Instagram', 'Facebook', 'Twitter/X', 'Pinterest'],
        'usage': 'GET /download?url=LINK'
    })


@app.route('/health')
def health():
    cookies = setup_cookies()
    ok = bool(cookies and os.path.exists(cookies))
    size = os.path.getsize(cookies) if ok else 0
    first = ""
    if ok:
        try:
            with open(cookies, 'r', encoding='utf-8', errors='ignore') as f:
                first = f.readline().strip()[:90]
        except:
            first = "error"
    return jsonify({
        'status': 'ok',
        'cookies_found': ok,
        'cookies_size': size,
        'cookies_first_line': first
    })


@app.route('/download', methods=['GET', 'POST'])
def download():
    url = (
        request.args.get('url') or 
        request.form.get('url') or 
        (request.json.get('url') if request.is_json else None)
    )
    
    if not url:
        return jsonify({'status': 'error', 'message': 'أضف الرابط: /download?url=رابط_الفيديو'}), 400

    # فك الروابط المختصرة
    try:
        if any(x in url for x in ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co']):
            r = requests.head(url, allow_redirects=True, timeout=10,
                            headers={'User-Agent': 'Mozilla/5.0'})
            url = r.url
            logger.info(f"Resolved: {url}")
    except:
        pass

    cookie_file = setup_cookies()
    temp_dir = tempfile.mkdtemp(prefix='dl_')
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best',
        'outtmpl': os.path.join(temp_dir, '%(title).55s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'merge_output_format': 'mp4',
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'mweb', 'tv'],
            }
        },
    }

    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                files = [f for f in Path(temp_dir).glob('*') if f.is_file()]
                if not files:
                    raise Exception('ما نزل أي ملف')
                filename = str(max(files, key=lambda p: p.stat().st_size))

            size_mb = os.path.getsize(filename) / (1024 * 1024)
            logger.info(f"Downloaded {size_mb:.2f} MB")

            if size_mb < 0.08:
                return jsonify({
                    'status': 'error',
                    'message': f'الملف صغير جداً ({size_mb:.2f} MB) — غالباً صورة'
                }), 500

            title = info.get('title') or 'video'
            safe_name = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title)[:55].strip()
            ext = Path(filename).suffix.lower() or '.mp4'
            if ext not in ['.mp4', '.webm', '.mkv', '.m4a', '.mp3']:
                ext = '.mp4'
            download_name = safe_name + ext

            return send_file(
                filename,
                as_attachment=True,
                download_name=download_name,
                mimetype='video/mp4' if ext == '.mp4' else 'application/octet-stream'
            )

    except Exception as e:
        err = str(e)
        logger.error(err)
        if 'Sign in to confirm' in err or 'not a bot' in err.lower():
            msg = 'YouTube رفض (Bot). أعد تصدير cookies.txt'
        else:
            msg = err[:500]
        return jsonify({'status': 'error', 'message': msg}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
