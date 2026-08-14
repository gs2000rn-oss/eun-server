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
        shorts = ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co', 'bit.ly', 'youtu.be']
        if any(d in url for d in shorts):
            r = requests.head(url, allow_redirects=True, timeout=12,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})
            if r.url and r.url != url:
                return r.url
    except:
        pass
    return url

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '14-youtube-max',
        'working': ['Instagram', 'Facebook', 'TikTok', 'Pinterest', 'Twitter/X', 'YouTube (try)']
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
    logger.info(f"→ {url}")

    is_yt = any(x in url for x in ['youtube.com', 'youtu.be', 'youtube-nocookie.com'])
    is_tw = any(x in url for x in ['twitter.com', 'x.com', 't.co'])
    is_pin = 'pinterest' in url or 'pin.it' in url
    is_ig = 'instagram.com' in url
    is_fb = 'facebook.com' in url or 'fb.watch' in url
    is_tt = 'tiktok.com' in url or 'douyin.com' in url

    temp_dir = tempfile.mkdtemp(prefix='dl_')
    outtmpl = os.path.join(temp_dir, 'out.%(ext)s')

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 15,
        'fragment_retries': 15,
        'socket_timeout': 50,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': '*/*',
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

    # ========== يوتيوب (أقصى محاولة) ==========
    if is_yt:
        ydl_opts['http_headers'].update({
            'Referer': 'https://www.youtube.com/',
            'Origin': 'https://www.youtube.com',
            'X-YouTube-Client-Name': '3',
            'X-YouTube-Client-Version': '19.09.3',
        })
        # ترتيب العملاء الأقوى حالياً ضد الحماية
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': [
                    'android',
                    'android_sdkless',
                    'ios',
                    'mweb',
                    'web',
                    'tv',
                    'tv_embedded',
                ],
                'player_skip': ['webpage', 'configs'],
                'skip': ['dash', 'hls'] if False else [],  # نتركها عادية
            }
        }
        # جودة متوسطة = فرصة نجاح أعلى
        ydl_opts['format'] = (
            'best[height<=480][ext=mp4]/'
            'best[height<=720][ext=mp4]/'
            'bestvideo[height<=720]+bestaudio/'
            'best[height<=720]/'
            'best'
        )
        # نحاول بدون geo-bypass أحياناً يسبب مشاكل
        ydl_opts['geo_bypass'] = True

    # ========== تويتر / X ==========
    elif is_tw:
        ydl_opts['http_headers']['Referer'] = 'https://x.com/'
        ydl_opts['http_headers']['Origin'] = 'https://x.com'
        ydl_opts['format'] = 'best[ext=mp4]/bestvideo+bestaudio/best'
        ydl_opts['extractor_args'] = {
            'twitter': {'api': ['syndication', 'graphql', 'legacy']}
        }

    # ========== باقي المنصات ==========
    elif is_pin:
        ydl_opts['http_headers']['Referer'] = 'https://www.pinterest.com/'
        ydl_opts['format'] = 'best/bestvideo+bestaudio'
    elif is_ig:
        ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
    elif is_fb:
        ydl_opts['http_headers']['Referer'] = 'https://www.facebook.com/'
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
    elif is_tt:
        ydl_opts['http_headers']['Referer'] = 'https://www.tiktok.com/'
        ydl_opts['format'] = 'best'

    # الكوكيز (ضرورية ليوتيوب)
    cookie = setup_cookies()
    if cookie:
        ydl_opts['cookiefile'] = cookie
        logger.info("Cookies loaded")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            files = [f for f in Path(temp_dir).rglob('*')
                     if f.is_file() and f.stat().st_size > 30000]

            if not files:
                return jsonify({
                    'status': 'error',
                    'message': 'Empty file (YouTube blocked this server IP)'
                }), 500

            filepath = str(max(files, key=lambda p: p.stat().st_size))
            size = os.path.getsize(filepath)
            title = (info.get('title') or info.get('id') or 'video')[:55]
            duration = info.get('duration') or 0

            logger.info(f"SUCCESS {size/1024/1024:.2f}MB | {duration}s | {title[:25]}")

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
            msg = 'YouTube blocked free server. Update cookies or use paid plan.'
        elif 'Sign in to confirm' in err or 'not a bot' in err.lower():
            msg = 'YouTube bot check → export fresh cookies from Incognito'
        elif 'This video is unavailable' in err:
            msg = 'Video unavailable / region / private'
        elif '403' in err or '401' in err:
            msg = 'Access denied (cookies expired)'
        else:
            msg = err[:300]

        return jsonify({'status': 'error', 'message': msg}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
