from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil
import logging
import traceback
import requests

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
                logger.info(f"Resolved → {r.url}")
                return r.url
    except Exception as e:
        logger.warning(f"resolve failed: {e}")
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

        # استبعاد الصور والـ storyboard
        if any(x in note for x in ['storyboard', 'preview', 'image', 'thumbnail']):
            continue
        if any(x in fid for x in ['sb0', 'sb1', 'sb2', 'sb3', 'storyboard', 'thumb']):
            continue
        if ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
            continue

        has_v = vcodec not in ('none', 'null', '')
        has_a = acodec not in ('none', 'null', '')

        candidates.append({
            'url': u,
            'height': height,
            'has_v': has_v,
            'has_a': has_a,
            'ext': ext,
            'tbr': tbr,
            'abr': abr,
            'fid': fid,
            'proto': proto
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

    # فيديو: نفضل progressive (فيديو + صوت)
    progressive = [c for c in candidates if c['has_v'] and c['has_a']]
    if progressive:
        progressive.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        logger.info(f"Selected progressive {progressive[0]['height']}p")
        return progressive[0]['url']

    # Pinterest / Twitter: نفضل non-HLS
    if 'pinterest' in extractor or 'twitter' in extractor:
        non_hls = [c for c in candidates if c['has_v'] and 'm3u8' not in c['proto'] and '.m3u8' not in c['url']]
        if non_hls:
            non_hls.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
            return non_hls[0]['url']

    # فيديو فقط
    video_only = [c for c in candidates if c['has_v']]
    if video_only:
        video_only.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        return video_only[0]['url']

    return candidates[0]['url']


@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '8.0-json-for-app',
        'message': 'Returns JSON with direct url for your Android app'
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
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    url = resolve_short_url(url)
    logger.info(f"JSON download request: {url} mode={mode}")

    is_youtube = any(x in url for x in ['youtube.com', 'youtu.be'])
    is_pinterest = 'pinterest' in url or 'pin.it' in url
    is_twitter = 'twitter.com' in url or 'x.com' in url
    is_instagram = 'instagram.com' in url

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
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
                'player_skip': ['webpage', 'configs'],
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
                return jsonify({'status': 'error', 'message': 'Failed to extract info'}), 500

            title = info.get('title') or info.get('id') or 'media'
            duration = info.get('duration')
            download_url = get_best_url(info, mode)

            if not download_url:
                return jsonify({'status': 'error', 'message': 'No playable URL found'}), 500

            # حماية من الصور
            low = download_url.lower()
            if any(x in low for x in ['.jpg', '.jpeg', '.png', '.webp', 'storyboard', 'ggpht.com', '/images/']):
                return jsonify({'status': 'error', 'message': 'Got image instead of video'}), 500

            logger.info(f"SUCCESS: {title[:40]} | duration={duration}")

            # === هذا الشكل اللي تطبيقك يتوقعه ===
            return jsonify({
                'status': 'success',
                'url': download_url,
                'title': title,
                'duration': duration
            })

    except Exception as e:
        err = str(e)
        logger.error(traceback.format_exc())

        if 'No video formats found' in err:
            msg = 'No video formats found (YouTube often blocks free servers)'
        elif 'Sign in to confirm' in err or 'not a bot' in err.lower():
            msg = 'YouTube bot detection - update cookies'
        else:
            msg = err[:350]

        return jsonify({'status': 'error', 'message': msg}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
