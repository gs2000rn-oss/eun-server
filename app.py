from flask import Flask, request, jsonify, Response, stream_with_context
import yt_dlp
import os
import shutil
import logging
import traceback
import requests
import base64
from urllib.parse import quote, unquote

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
            logger.error(f"Cookie copy failed: {e}")
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


def resolve_short_url(url):
    try:
        shorts = ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co', 'bit.ly']
        if any(d in url for d in shorts):
            r = requests.head(url, allow_redirects=True, timeout=12,
                              headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})
            if r.url and r.url != url:
                return r.url
    except:
        pass
    return url


def get_best_url(info, mode='video'):
    formats = info.get('formats') or []
    main_url = info.get('url')
    extractor = (info.get('extractor_key') or info.get('extractor') or '').lower()

    candidates = []
    for f in formats:
        u = f.get('url')
        if not u:
            continue

        note = str(f.get('format_note', '') or '').lower()
        fid  = str(f.get('format_id', '') or '').lower()
        ext  = str(f.get('ext', '') or '').lower()
        proto = str(f.get('protocol', '') or '').lower()
        vcodec = str(f.get('vcodec', 'none') or 'none').lower()
        acodec = str(f.get('acodec', 'none') or 'none').lower()
        height = f.get('height') or 0
        tbr = f.get('tbr') or 0
        abr = f.get('abr') or 0

        if any(x in note for x in ['storyboard', 'preview', 'image', 'thumbnail']):
            continue
        if any(x in fid for x in ['sb0', 'sb1', 'sb2', 'sb3', 'storyboard', 'thumb']):
            continue
        if ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
            continue

        has_v = vcodec not in ('none', 'null', '')
        has_a = acodec not in ('none', 'null', '')

        candidates.append({
            'url': u, 'height': height, 'has_v': has_v, 'has_a': has_a,
            'ext': ext, 'tbr': tbr, 'abr': abr, 'proto': proto
        })

    if not candidates:
        return main_url

    if mode == 'audio':
        only_a = [c for c in candidates if c['has_a'] and not c['has_v']]
        if only_a:
            only_a.sort(key=lambda x: x['abr'] or x['tbr'], reverse=True)
            return only_a[0]['url']
        with_a = [c for c in candidates if c['has_a']]
        return with_a[0]['url'] if with_a else candidates[0]['url']

    # progressive first
    progressive = [c for c in candidates if c['has_v'] and c['has_a']]
    if progressive:
        progressive.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        return progressive[0]['url']

    # Pinterest / Twitter prefer non-HLS
    if 'pinterest' in extractor or 'twitter' in extractor:
        non_hls = [c for c in candidates if c['has_v'] and 'm3u8' not in c['proto'] and '.m3u8' not in c['url']]
        if non_hls:
            non_hls.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
            return non_hls[0]['url']

    video_only = [c for c in candidates if c['has_v']]
    if video_only:
        video_only.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        return video_only[0]['url']

    return candidates[0]['url']


@app.route('/')
def home():
    return jsonify({'status': 'online', 'version': '9.0-proxy'})


@app.route('/health')
def health():
    cookies = setup_cookies()
    ok = bool(cookies and os.path.exists(cookies))
    size = os.path.getsize(cookies) if ok else 0
    return jsonify({'status': 'ok', 'cookies_found': ok, 'cookies_size': size})


@app.route('/download', methods=['GET', 'POST'])
def download():
    """يرجع JSON فيه رابط proxy من سيرفرنا (عشان DownloadManager)"""
    url = request.args.get('url') or request.form.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL'}), 400

    url = resolve_short_url(url)
    logger.info(f"Request: {url}")

    is_youtube = any(x in url for x in ['youtube.com', 'youtu.be'])
    is_pinterest = 'pinterest' in url or 'pin.it' in url
    is_twitter = 'twitter.com' in url or 'x.com' in url
    is_instagram = 'instagram.com' in url

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
        'format': 'all',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'socket_timeout': 25,
        'retries': 5,
    }

    if is_youtube:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'android_sdkless', 'web', 'mweb', 'tv', 'ios'],
            }
        }
    if is_pinterest:
        ydl_opts['http_headers']['Referer'] = 'https://www.pinterest.com/'
    if is_twitter:
        ydl_opts['http_headers']['Referer'] = 'https://x.com/'
    if is_instagram:
        ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'

    cookie_file = setup_cookies()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract'}), 500

            title = info.get('title') or 'video'
            duration = info.get('duration')
            real_url = get_best_url(info, mode)

            if not real_url:
                return jsonify({'status': 'error', 'message': 'No playable URL'}), 500

            # نرجع رابط proxy من سيرفرنا (مش الرابط الأصلي)
            # عشان DownloadManager ينزل بدون ما يحتاج Referer
            encoded = base64.urlsafe_b64encode(real_url.encode()).decode()
            proxy_url = f"https://eun-server.onrender.com/stream?u={encoded}"

            # نحدد الـ referer اللي يحتاجه الـ stream
            referer = 'https://www.pinterest.com/' if is_pinterest else \
                      'https://x.com/' if is_twitter else \
                      'https://www.instagram.com/' if is_instagram else \
                      'https://www.youtube.com/'

            # نضيف الـ referer كـ query أيضاً
            ref_encoded = base64.urlsafe_b64encode(referer.encode()).decode()
            proxy_url += f"&r={ref_encoded}"

            return jsonify({
                'status': 'success',
                'url': proxy_url,
                'title': title,
                'duration': duration
            })

    except Exception as e:
        err = str(e)
        logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': err[:400]}), 500


@app.route('/stream')
def stream():
    """يحمل الفيديو من المصدر مع الـ headers الصحيحة ويرسله للتطبيق"""
    u = request.args.get('u')
    r = request.args.get('r')

    if not u:
        return "Missing u", 400

    try:
        real_url = base64.urlsafe_b64decode(u.encode()).decode()
        referer = base64.urlsafe_b64decode(r.encode()).decode() if r else 'https://www.pinterest.com/'
    except Exception:
        return "Invalid encoding", 400

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': referer,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    try:
        # نستخدم stream=True عشان ما نحمّل الملف كامل في الذاكرة
        resp = requests.get(real_url, headers=headers, stream=True, timeout=60)

        if resp.status_code != 200:
            return f"Upstream error {resp.status_code}", 502

        def generate():
            for chunk in resp.iter_content(chunk_size=1024 * 64):
                if chunk:
                    yield chunk

        return Response(
            stream_with_context(generate()),
            content_type=resp.headers.get('Content-Type', 'video/mp4'),
            headers={
                'Content-Disposition': 'attachment; filename="video.mp4"',
                'Content-Length': resp.headers.get('Content-Length', ''),
            }
        )
    except Exception as e:
        logger.error(f"Stream error: {e}")
        return str(e), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
