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
        except Exception as e:
            logger.error(f"Cookie copy: {e}")
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

def resolve_short_url(url):
    try:
        import requests
        shorts = ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co', 'bit.ly']
        if any(d in url for d in shorts):
            r = requests.head(url, allow_redirects=True, timeout=12,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})
            if r.url and r.url != url:
                logger.info(f"Resolved → {r.url}")
                return r.url
    except Exception as e:
        logger.warning(f"resolve: {e}")
    return url

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '13-twitter-youtube',
        'supports': ['Instagram', 'Facebook', 'TikTok', 'Pinterest', 'Twitter/X', 'YouTube']
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
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL'}), 400

    url = resolve_short_url(url)
    logger.info(f"DOWNLOAD → {url}")

    is_yt = any(x in url for x in ['youtube.com', 'youtu.be', 'youtube-nocookie.com'])
    is_tw = any(x in url for x in ['twitter.com', 'x.com', 't.co'])
    is_pin = 'pinterest' in url or 'pin.it' in url
    is_ig = 'instagram.com' in url
    is_fb = 'facebook.com' in url or 'fb.watch' in url or 'fb.me' in url
    is_tt = 'tiktok.com' in url or 'douyin.com' in url

    temp_dir = tempfile.mkdtemp(prefix='dl_')
    outtmpl = os.path.join(temp_dir, 'out.%(ext)s')

    # ===== إعدادات عامة =====
    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 12,
        'fragment_retries': 12,
        'socket_timeout': 45,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

    # ===== يوتيوب =====
    if is_yt:
        ydl_opts['extractor_args'] = {
            'youtube': {
                # أفضل ترتيب حالياً ضد الحماية
                'player_client': ['android', 'android_sdkless', 'ios', 'mweb', 'web', 'tv'],
                'player_skip': ['webpage', 'configs'],
            }
        }
        ydl_opts['format'] = 'best[height<=720]/bestvideo[height<=720]+bestaudio/best'
        ydl_opts['http_headers']['Referer'] = 'https://www.youtube.com/'
        ydl_opts['http_headers']['Origin'] = 'https://www.youtube.com'

    # ===== تويتر / X =====
    elif is_tw:
        ydl_opts['http_headers']['Referer'] = 'https://x.com/'
        ydl_opts['http_headers']['Origin'] = 'https://x.com'
        # تويتر يحتاج كوكيز غالباً + نفضل mp4
        ydl_opts['format'] = 'best[ext=mp4]/bestvideo+bestaudio/best'
        # بعض الفيديوهات تكون m3u8 → yt-dlp + ffmpeg يحولها
        ydl_opts['extractor_args'] = {
            'twitter': {
                'api': ['syndication', 'graphql', 'legacy'],
            }
        }

    # ===== بينترست =====
    elif is_pin:
        ydl_opts['http_headers']['Referer'] = 'https://www.pinterest.com/'
        ydl_opts['format'] = 'best/bestvideo+bestaudio'

    # ===== إنستغرام =====
    elif is_ig:
        ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'
        ydl_opts['format'] = 'bestvideo+bestaudio/best'

    # ===== فيسبوك =====
    elif is_fb:
        ydl_opts['http_headers']['Referer'] = 'https://www.facebook.com/'
        ydl_opts['format'] = 'bestvideo+bestaudio/best'

    # ===== تيك توك =====
    elif is_tt:
        ydl_opts['http_headers']['Referer'] = 'https://www.tiktok.com/'
        ydl_opts['format'] = 'best'

    # الكوكيز (مهمة جداً لتويتر ويوتيوب)
    cookie = setup_cookies()
    if cookie:
        ydl_opts['cookiefile'] = cookie
        logger.info("Using cookies")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            files = [f for f in Path(temp_dir).rglob('*')
                     if f.is_file() and f.stat().st_size > 50000]

            if not files:
                return jsonify({
                    'status': 'error',
                    'message': 'File empty or too small (maybe blocked)'
                }), 500

            filepath = str(max(files, key=lambda p: p.stat().st_size))
            size = os.path.getsize(filepath)
            title = (info.get('title') or info.get('id') or 'video')[:55]
            duration = info.get('duration') or 0

            logger.info(f"OK: {size/1024/1024:.2f} MB | {duration}s | {title[:30]}")

            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
            safe = safe[:40] + '.mp4'

            return send_file(
                filepath,
                mimetype='video/mp4',
                as_attachment=True,
                download_name=safe
            )

    except Exception as e:
        err = str(e)
        logger.error(traceback.format_exc())

        if 'No video formats found' in err:
            msg = 'YouTube: No formats (blocked IP or need fresh cookies)'
        elif 'Sign in to confirm' in err or 'not a bot' in err.lower():
            msg = 'YouTube bot check → re-export cookies from Incognito'
        elif '403' in err or '401' in err:
            msg = 'Access denied (cookies expired or private video)'
        elif 'Unsupported URL' in err or 'No video could be found' in err:
            msg = 'Twitter/X: video not found or private (try with cookies)'
        else:
            msg = err[:350]

        return jsonify({'status': 'error', 'message': msg}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
