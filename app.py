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
    """نسخ ملف الكوكيز إلى مجلد /tmp القابل للكتابة لتفادي خطأ Read-only system"""
    secret_cookies = '/etc/secrets/cookies.txt'
    tmp_cookies = '/tmp/cookies.txt'
    
    if os.path.exists(secret_cookies):
        try:
            shutil.copy(secret_cookies, tmp_cookies)
            logger.info("Successfully copied cookies to /tmp/cookies.txt")
            return tmp_cookies
        except Exception as e:
            logger.error(f"Failed to copy cookies: {e}")
            return secret_cookies
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

def extract_clean_url(info, mode):
    """استخراج رابط فيديو MP4 حقيقي واستبعاد كافة صور المعاينة والـ Storyboard"""
    formats = info.get('formats', [])
    
    valid_formats = []
    for f in formats:
        u = f.get('url')
        if not u:
            continue
            
        protocol = str(f.get('protocol', '')).lower()
        format_id = str(f.get('format_id', '')).lower()
        format_note = str(f.get('format_note', '')).lower()
        ext = str(f.get('ext', '')).lower()
        vcodec = str(f.get('vcodec', '')).lower()
        acodec = str(f.get('acodec', '')).lower()
        fps = f.get('fps') or 0

        # 1. فلترة صريحة وقاطعة لشبكات الصور والـ Storyboards
        if format_id.startswith('sb') or 'storyboard' in format_id or 'storyboard' in format_note:
            continue
        if ext in ['mhtml', 'jpg', 'jpeg', 'png', 'webp', 'gif']:
            continue
        if any(img in vcodec for img in ['jpeg', 'mjpeg', 'jpg', 'webp', 'none', 'null', 'images']):
            continue
        if 'mhtml' in protocol or '.m3u8' in u:
            continue

        # 2. التحقق من وجود فيديو حقيقي (يجب أن يحتوي على fps وبكسلات)
        has_v = (vcodec not in ['none', 'null', '']) and (fps > 0)
        has_a = (acodec not in ['none', 'null', ''])

        height = f.get('height', 0) or 0
        abr = f.get('abr', 0) or 0

        valid_formats.append({
            'url': u,
            'has_v': has_v,
            'has_a': has_a,
            'height': height,
            'abr': abr,
            'ext': ext,
            'format_id': format_id
        })

    if mode == 'audio':
        # اختيار أفضل مقطع صوتي
        audio_formats = [f for f in valid_formats if f['has_a']]
        if audio_formats:
            audio_formats.sort(key=lambda x: x['abr'], reverse=True)
            return audio_formats[0]['url']
    else:
        # اختيار فيديو حقيقي:
        # أ) إعطاء الأولوية للفيديوهات التي تحتوي على صوت وصورة معا (مثل MP4 المباشر 720p/360p)
        combo_mp4 = [f for f in valid_formats if f['has_v'] and f['has_a'] and f['ext'] == 'mp4']
        if combo_mp4:
            combo_mp4.sort(key=lambda x: x['height'], reverse=True)
            return combo_mp4[0]['url']

        combo_any = [f for f in valid_formats if f['has_v'] and f['has_a']]
        if combo_any:
            combo_any.sort(key=lambda x: x['height'], reverse=True)
            return combo_any[0]['url']

        # ب) إذا لم يوجد، اختيار أفضل فيديو MP4 حقيقي بـ fps > 0
        video_only = [f for f in valid_formats if f['has_v']]
        if video_only:
            video_only.sort(key=lambda x: x['height'], reverse=True)
            return video_only[0]['url']

    return info.get('url')

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # حل روابط Pinterest
    if 'pin.it' in url or 'pinterest' in url:
        try:
            response = requests.head(url, allow_redirects=True, timeout=5)
            url = response.url
        except Exception as e:
            logger.error(f"Failed to resolve shortlink: {e}")

    logger.info(f"Processing URL: {url} | Mode: {mode}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if mode == 'video' else 'bestaudio/best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
                'skip': ['webpage', 'configs']
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
            download_url = extract_clean_url(info, mode)

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title
                })
            else:
                return jsonify({'status': 'error', 'message': 'No valid video link found'}), 500

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '4.2'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
