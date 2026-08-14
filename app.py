from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil
import logging
import requests
import traceback

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


def get_best_url(info, mode='video'):
    formats = info.get('formats') or []
    main_url = info.get('url')

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
        tbr    = f.get('tbr') or 0
        abr    = f.get('abr') or 0

        # استبعاد الصور والـ storyboard
        if any(x in note for x in ['storyboard', 'preview', 'image', 'thumbnail']):
            continue
        if any(x in fid for x in ['sb0', 'sb1', 'sb2', 'sb3', 'storyboard', 'thumb']):
            continue
        if ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
            continue
        if 'm3u8' in proto or '.m3u8' in u:
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
            'fid': fid
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

    # فيديو: نفضل اللي فيه صوت + صورة
    progressive = [c for c in candidates if c['has_v'] and c['has_a']]
    if progressive:
        progressive.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        return progressive[0]['url']

    # فيديو فقط (fallback)
    video_only = [c for c in candidates if c['has_v']]
    if video_only:
        video_only.sort(key=lambda x: x['height'], reverse=True)
        return video_only[0]['url']

    return candidates[0]['url']


@app.route('/')
def home():
    return jsonify({'status': 'online', 'version': '4.1-stable'})


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

    # فك الروابط المختصرة
    try:
        if any(d in url for d in ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co']):
            r = requests.head(url, allow_redirects=True, timeout=10,
                              headers={'User-Agent': 'Mozilla/5.0'})
            url = r.url
    except:
        pass

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
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'mweb'],
            }
        },
        'socket_timeout': 25,
    }

    cookie_file = setup_cookies()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract'}), 500

            title = info.get('title') or 'media'
            download_url = get_best_url(info, mode)

            if not download_url:
                return jsonify({'status': 'error', 'message': 'No valid URL'}), 500

            # منع الصور
            low = download_url.lower()
            if any(x in low for x in ['.jpg', '.png', '.webp', 'storyboard', 'ggpht.com']):
                return jsonify({'status': 'error', 'message': 'Got image instead of video'}), 500

            return jsonify({
                'status': 'success',
                'url': download_url,
                'title': title
            })

    except Exception as e:
        logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': str(e)[:400]}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
