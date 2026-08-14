from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil
import logging
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def setup_cookies():
    secret_cookies = '/etc/secrets/cookies.txt'
    tmp_cookies = '/tmp/cookies.txt'
    
    if os.path.exists(secret_cookies):
        try:
            shutil.copy(secret_cookies, tmp_cookies)
            logger.info("Cookies copied to /tmp/cookies.txt")
            return tmp_cookies
        except Exception as e:
            logger.error(f"Failed to copy cookies: {e}")
            return secret_cookies
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


def extract_clean_url(info, mode='video'):
    """
    يستخرج أفضل رابط فيديو حقيقي (مش storyboard ولا صورة)
    """
    formats = info.get('formats', [])
    if not formats:
        return info.get('url')

    valid = []

    for f in formats:
        url = f.get('url')
        if not url:
            continue

        # ===== استبعاد أي شيء مش فيديو حقيقي =====
        fmt_id = str(f.get('format_id', '')).lower()
        note = str(f.get('format_note', '')).lower()
        ext = str(f.get('ext', '')).lower()
        protocol = str(f.get('protocol', '')).lower()
        vcodec = str(f.get('vcodec', 'none')).lower()
        acodec = str(f.get('acodec', 'none')).lower()
        height = f.get('height') or 0
        width = f.get('width') or 0

        # استبعاد storyboard + صور + m3u8
        if any(x in note for x in ['storyboard', 'preview', 'image']):
            continue
        if any(x in fmt_id for x in ['sb', 'storyboard', 'thumb']):
            continue
        if ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
            continue
        if '.m3u8' in url or 'm3u8' in protocol or 'manifest' in url:
            continue
        if 'dash' in protocol and mode == 'video':  # نفضل progressive
            continue

        has_video = vcodec not in ['none', '']
        has_audio = acodec not in ['none', '']

        valid.append({
            'url': url,
            'height': height,
            'width': width,
            'has_v': has_video,
            'has_a': has_audio,
            'ext': ext,
            'abr': f.get('abr') or 0,
            'tbr': f.get('tbr') or 0,
            'format_id': f.get('format_id'),
            'note': note
        })

    if not valid:
        # fallback أخير
        return info.get('url')

    if mode == 'audio':
        # أفضل صوت فقط
        audio = [x for x in valid if x['has_a'] and not x['has_v']]
        if audio:
            audio.sort(key=lambda x: x['abr'] or x['tbr'], reverse=True)
            return audio[0]['url']
        # أي حاجة فيها صوت
        any_a = [x for x in valid if x['has_a']]
        if any_a:
            return any_a[0]['url']
    else:
        # 1. أفضل Progressive (فيديو + صوت معاً) — هذا اللي نبيه
        progressive = [x for x in valid if x['has_v'] and x['has_a'] and x['ext'] in ['mp4', 'webm']]
        if progressive:
            progressive.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
            logger.info(f"Selected progressive: {progressive[0]['format_id']} {progressive[0]['height']}p")
            return progressive[0]['url']

        # 2. فيديو فقط (لو ما فيه progressive)
        video_only = [x for x in valid if x['has_v']]
        if video_only:
            video_only.sort(key=lambda x: x['height'], reverse=True)
            logger.info(f"Selected video-only: {video_only[0]['format_id']}")
            return video_only[0]['url']

    # آخر حل
    valid.sort(key=lambda x: x['height'], reverse=True)
    return valid[0]['url']


@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # فك روابط Pinterest
    if 'pin.it' in url or 'pinterest' in url:
        try:
            r = requests.head(url, allow_redirects=True, timeout=8)
            url = r.url
        except:
            pass

    logger.info(f"Processing: {url} | mode={mode}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
        'format': 'bestvideo*+bestaudio/best',   # مهم
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'mweb'],  # android أفضل مع الكوكيز
                'player_skip': ['webpage', 'configs'],
            }
        },
    }

    cookie_file = setup_cookies()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract'}), 500

            title = info.get('title', 'video')
            download_url = extract_clean_url(info, mode)

            if not download_url:
                return jsonify({'status': 'error', 'message': 'No valid video link found'}), 500

            # تحقق سريع إن الرابط مش صورة
            if any(x in download_url.lower() for x in ['.jpg', '.png', '.webp', 'storyboard', 'ggpht.com']):
                return jsonify({
                    'status': 'error',
                    'message': 'Got an image/storyboard instead of video. Try another video or update cookies.'
                }), 500

            return jsonify({
                'status': 'success',
                'url': download_url,
                'title': title,
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail')
            })

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'service': 'Shark Engine',
        'version': '3.8-fixed'
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
