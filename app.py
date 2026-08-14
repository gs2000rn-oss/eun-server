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
            logger.error(f"cookies error: {e}")
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '6.0-merge-audio',
        'supports': ['Instagram', 'TikTok', 'Facebook', 'YouTube', 'Pinterest', 'Twitter'],
        'usage': '/download?url=LINK'
    })


@app.route('/health')
def health():
    cookies = setup_cookies()
    ok = bool(cookies and os.path.exists(cookies))
    size = os.path.getsize(cookies) if ok else 0
    return jsonify({
        'status': 'ok',
        'cookies_found': ok,
        'cookies_size': size
    })


@app.route('/download', methods=['GET', 'POST'])
def download():
    url = request.args.get('url') or request.form.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'أضف ?url=الرابط'}), 400

    # فك الروابط المختصرة
    try:
        if any(x in url for x in ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co', 'instagram.com/reel', 'instagram.com/p/']):
            r = requests.head(url, allow_redirects=True, timeout=10,
                              headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            url = r.url
            logger.info(f"Resolved → {url}")
    except Exception as e:
        logger.warning(f"resolve failed: {e}")

    cookie_file = setup_cookies()
    temp_dir = tempfile.mkdtemp(prefix='media_')

    # أهم جزء: دمج فيديو + صوت
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',           # يجبر الدمج
        'outtmpl': os.path.join(temp_dir, '%(title).50s.%(ext)s'),
        'merge_output_format': 'mp4',                   # الناتج دائماً mp4
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'retries': 12,
        'fragment_retries': 12,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {'player_client': ['android', 'web', 'mweb']},
            'instagram': {},
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            filename = ydl.prepare_filename(info)
            
            # ابحث عن الملف النهائي
            if not os.path.exists(filename):
                files = list(Path(temp_dir).rglob('*'))
                files = [f for f in files if f.is_file() and f.stat().st_size > 10000]
                if not files:
                    raise Exception('ما نزل أي ملف صالح')
                filename = str(max(files, key=lambda p: p.stat().st_size))

            size_mb = os.path.getsize(filename) / (1024*1024)
            logger.info(f"Ready: {size_mb:.2f} MB → {filename}")

            if size_mb < 0.05:
                return jsonify({
                    'status': 'error',
                    'message': f'الملف صغير جداً ({size_mb:.2f} MB) — فشل التحميل'
                }), 500

            # اسم نظيف
            title = (info.get('title') or 'video')[:50]
            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip()
            if not safe:
                safe = 'video'
            download_name = safe + '.mp4'

            return send_file(
                filename,
                as_attachment=True,
                download_name=download_name,
                mimetype='video/mp4'
            )

    except Exception as e:
        err = str(e)
        logger.error(err)
        if 'Sign in to confirm' in err or 'not a bot' in err.lower():
            msg = 'YouTube رفض (Bot). أعد تصدير cookies.txt من Incognito'
        elif 'ffmpeg' in err.lower() or 'merging' in err.lower():
            msg = 'مشكلة في دمج الصوت (تأكد إن ffmpeg مثبت في Build Command)'
        else:
            msg = err[:450]
        return jsonify({'status': 'error', 'message': msg}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
