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
    secret = '/etc/secrets/cookies.txt'
    tmp = '/tmp/cookies.txt'
    if os.path.exists(secret):
        try:
            shutil.copy(secret, tmp)
            return tmp
        except Exception as e:
            logger.error(f"cookies copy error: {e}")
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None


def get_best_url(info, mode='video'):
    """يختار أفضل رابط حقيقي (مش صورة ولا storyboard)"""
    formats = info.get('formats') or []
    main_url = info.get('url')

    valid = []
    for f in formats:
        u = f.get('url')
        if not u:
            continue

        note = str(f.get('format_note', '')).lower()
        fmt_id = str(f.get('format_id', '')).lower()
        ext = str(f.get('ext', '')).lower()
        protocol = str(f.get('protocol', '')).lower()
        vcodec = str(f.get('vcodec', 'none')).lower()
        acodec = str(f.get('acodec', 'none')).lower()
        height = f.get('height') or 0

        # استبعاد الصور والـ storyboard و m3u8
        if any(x in note for x in ['storyboard', 'preview', 'image']):
            continue
        if any(x in fmt_id for x in ['sb0', 'sb1', 'sb2', 'storyboard', 'thumb']):
            continue
        if ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
            continue
        if '.m3u8' in u or 'm3u8' in protocol:
            continue

        has_v = vcodec not in ['none', '']
        has_a = acodec not in ['none', '']

        valid.append({
            'url': u,
            'height': height,
            'has_v': has_v,
            'has_a': has_a,
            'ext': ext,
            'tbr': f.get('tbr') or 0,
            'abr': f.get('abr') or 0
        })

    if not valid:
        return main_url

    if mode == 'audio':
        audios = [x for x in valid if x['has_a'] and not x['has_v']]
        if audios:
            audios.sort(key=lambda x: x['abr'] or x['tbr'], reverse=True)
            return audios[0]['url']
        any_a = [x for x in valid if x['has_a']]
        return any_a[0]['url'] if any_a else valid[0]['url']

    # فيديو: نفضل progressive (فيديو+صوت)
    progressive = [x for x in valid if x['has_v'] and x['has_a']]
    if progressive:
        progressive.sort(key=lambda x: (x['height'], x['tbr']), reverse=True)
        return progressive[0]['url']

    # فيديو فقط
    videos = [x for x in valid if x['has_v']]
    if videos:
        videos.sort(key=lambda x: x['height'], reverse=True)
        return videos[0]['url']

    return valid[0]['url']


@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'service': 'Shark Engine Multi',
        'version': '3.9-restore',
        'supports': ['youtube', 'tiktok', 'instagram', 'facebook', 'twitter', 'pinterest']
    })


@app.route('/download', methods=['GET', 'POST'])
def get_download_link():
    url = request.args.get('url') or request.form.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # فك الروابط المختصرة
    if any(x in url for x in ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co']):
        try:
            r = requests.head(url, allow_redirects=True, timeout=8,
                            headers={'User-Agent': 'Mozilla/5.0'})
            url = r.url
            logger.info(f"Resolved short url → {url}")
        except Exception as e:
            logger.warning(f"shortlink failed: {e}")

    logger.info(f"Processing: {url} | mode={mode}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
        'format': 'all',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'mweb'],
                'player_skip': ['webpage', 'configs']
            }
        }
    }

    cookie_file = setup_cookies()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract media'}), 500

            title = info.get('title', 'Downloaded_Media')
            download_url = get_best_url(info, mode)

            if not download_url:
                return jsonify({'status': 'error', 'message': 'No valid playable link found'}), 500

            # حماية من الصور
            low = download_url.lower()
            if any(x in low for x in ['.jpg', '.png', '.webp', 'storyboard', 'ggpht.com', 'googleusercontent']):
                return jsonify({
                    'status': 'error',
                    'message': 'Got image/storyboard instead of video'
                }), 500

            return jsonify({
                'status': 'success',
                'url': download_url,
                'title': title
            })

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
