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
        except:
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


def get_best_url(info, mode='video'):
    formats = info.get('formats') or []
    main_url = info.get('url')
    duration = info.get('duration') or 0
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
        width  = f.get('width') or 0
        tbr    = f.get('tbr') or 0
        abr    = f.get('abr') or 0
        f_duration = f.get('duration') or duration or 0

        # ===== استبعاد الصور والـ storyboard =====
        if any(x in note for x in ['storyboard', 'preview', 'image', 'thumbnail']):
            continue
        if any(x in fid for x in ['sb0', 'sb1', 'sb2', 'sb3', 'storyboard', 'thumb']):
            continue
        if ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
            continue

        # لـ Pinterest: نفضل الملفات الحقيقية ونستبعد الـ HLS الضعيف
        if 'pinterest' in extractor:
            if 'm3u8' in proto or '.m3u8' in u:
                # نقبل m3u8 فقط لو ما فيه بديل
                pass
            # نفضل V_720P و V_HLSV4 وغيرها
            if height < 240 and 'hls' not in fid:
                continue

        has_v = vcodec not in ('none', 'null', '')
        has_a = acodec not in ('none', 'null', '')

        # تجاهل الملفات الميتة (مدة 0)
        if f_duration and f_duration < 0.5 and height < 400:
            continue

        candidates.append({
            'url': u,
            'height': height,
            'width': width,
            'has_v': has_v,
            'has_a': has_a,
            'ext': ext,
            'tbr': tbr,
            'abr': abr,
            'fid': fid,
            'duration': f_duration,
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

    # === فيديو ===
    # 1. Progressive (فيديو + صوت)
    progressive = [c for c in candidates if c['has_v'] and c['has_a']]
    if progressive:
        progressive.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        best = progressive[0]
        logger.info(f"Pinterest/Video PROGRESSIVE {best['height']}p {best['fid']}")
        return best['url']

    # 2. لـ Pinterest: نفضل أعلى جودة حتى لو video-only
    if 'pinterest' in extractor:
        # نفضل غير m3u8 أولاً
        non_hls = [c for c in candidates if c['has_v'] and 'm3u8' not in c['proto'] and '.m3u8' not in c['url']]
        if non_hls:
            non_hls.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
            logger.info(f"Pinterest non-HLS {non_hls[0]['height']}p {non_hls[0]['fid']}")
            return non_hls[0]['url']

    # 3. فيديو فقط
    video_only = [c for c in candidates if c['has_v']]
    if video_only:
        video_only.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        return video_only[0]['url']

    return candidates[0]['url']


@app.route('/')
def home():
    return jsonify({'status': 'online', 'version': '4.2-pinterest-fix'})


@app.route('/health')
def health():
    cookies = setup_cookies()
    ok = bool(cookies and os.path.exists(cookies))
    return jsonify({'status': 'ok', 'cookies_found': ok})


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
                              headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            url = r.url
            logger.info(f"Resolved: {url}")
    except:
        pass

    is_pinterest = 'pinterest' in url.lower() or 'pin.it' in url.lower()

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
            'Referer': 'https://www.pinterest.com/' if is_pinterest else 'https://www.google.com/',
            'Origin': 'https://www.pinterest.com' if is_pinterest else None,
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'mweb'],
            }
        },
        'socket_timeout': 25,
    }

    # تنظيف headers من None
    ydl_opts['http_headers'] = {k: v for k, v in ydl_opts['http_headers'].items() if v}

    cookie_file = setup_cookies()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract'}), 500

            title = info.get('title') or 'media'
            duration = info.get('duration') or 0
            download_url = get_best_url(info, mode)

            if not download_url:
                return jsonify({'status': 'error', 'message': 'No valid URL found'}), 500

            # حماية قوية من الفيديوهات الميتة والصور
            low = download_url.lower()
            if any(x in low for x in ['.jpg', '.png', '.webp', 'storyboard', 'ggpht.com', '/images/']):
                return jsonify({'status': 'error', 'message': 'Got image instead of video'}), 500

            if duration and duration < 0.8:
                return jsonify({
                    'status': 'error',
                    'message': f'Video duration is {duration}s (too short / dead). This pin may not be a real video.'
                }), 500

            return jsonify({
                'status': 'success',
                'url': download_url,
                'title': title,
                'duration': duration
            })

    except Exception as e:
        logger.error(traceback.format_exc())
        err = str(e)
        if '404' in err and 'pinterest' in err.lower():
            return jsonify({
                'status': 'error',
                'message': 'Pinterest blocked metadata (404). Try a different pin or update yt-dlp.'
            }), 500
        return jsonify({'status': 'error', 'message': err[:400]}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
