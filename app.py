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
            logger.info("Cookies copied to /tmp")
            return tmp
        except Exception as e:
            logger.error(f"Copy failed: {e}")
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '4.0-real-download',
        'how_to_use': 'GET /download?url=YOUTUBE_LINK'
    })


@app.route('/health')
def health():
    cookies = setup_cookies()
    ok = cookies is not None and os.path.exists(cookies)
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
    url = request.args.get('url') or request.form.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'أضف ?url=رابط_اليوتيوب'}), 400

    cookie_file = setup_cookies()
    if not cookie_file:
        return jsonify({'status': 'error', 'message': 'cookies.txt مش موجود في Secret Files'}), 500

    temp_dir = tempfile.mkdtemp(prefix='yt_')
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(temp_dir, '%(title).50s.%(ext)s'),
        'cookiefile': cookie_file,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'merge_output_format': 'mp4',
        'retries': 10,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'mweb'],
            }
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            if not os.path.exists(filename):
                files = list(Path(temp_dir).glob('*'))
                if not files:
                    raise Exception('ما تم تحميل أي ملف')
                filename = str(max(files, key=lambda p: p.stat().st_size))

            size_mb = os.path.getsize(filename) / (1024 * 1024)
            logger.info(f"File ready: {size_mb:.1f} MB")

            if size_mb < 0.1:
                return jsonify({'status': 'error', 'message': 'الملف صغير جداً (صورة؟)'}), 500

            safe_name = "".join(c if c.isalnum() or c in '._- ' else '_' for c in os.path.basename(filename))[:60]
            if not safe_name.endswith('.mp4'):
                safe_name += '.mp4'

            return send_file(
                filename,
                as_attachment=True,
                download_name=safe_name,
                mimetype='video/mp4'
            )

    except Exception as e:
        err = str(e)
        logger.error(err)
        if 'Sign in to confirm' in err or 'not a bot' in err.lower():
            msg = 'YouTube رفض (Bot). أعد تصدير cookies.txt من نافذة خاصة + robots.txt'
        else:
            msg = err[:500]
        return jsonify({'status': 'error', 'message': msg}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
