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
    """نسخ ملف الكوكيز إلى مجلد /tmp القابل للكتابة"""
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

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # حل روابط التوجيه القصيرة مثل Pinterest
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
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
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
            formats = info.get('formats', [])
            
            download_url = None
            
            if mode == 'audio':
                audio_formats = []
                for f in formats:
                    u = f.get('url')
                    acodec = str(f.get('acodec', '')).lower()
                    if u and acodec and acodec != 'none':
                        audio_formats.append(f)
                if audio_formats:
                    audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                    download_url = audio_formats[0].get('url')
            else:
                # تصفية واختيار أفضل جودة فيديو واضحة مع صوتها لتجنب التشويش والصور
                valid_videos = []
                for f in formats:
                    u = f.get('url')
                    if not u:
                        continue
                    format_id = str(f.get('format_id', '')).lower()
                    format_note = str(f.get('format_note', '')).lower()
                    vcodec = str(f.get('vcodec', '')).lower()
                    acodec = str(f.get('acodec', '')).lower()
                    ext = str(f.get('ext', '')).lower()
                    
                    # استبعاد تام لصور المعاينة والقصص المصغرة
                    if format_id.startswith('sb') or 'storyboard' in format_id or 'storyboard' in format_note:
                        continue
                    if ext in ['jpg', 'jpeg', 'png', 'webp', 'mhtml', 'gif']:
                        continue
                    if any(img in vcodec for img in ['jpeg', 'mjpeg', 'jpg', 'webp', 'images']):
                        continue
                    if vcodec in ['none', 'null', '']:
                        continue
                    
                    has_audio = acodec not in ['none', 'null', ''] and acodec is not None
                    height = f.get('height', 0) or 0
                    
                    valid_videos.append({
                        'url': u,
                        'height': height,
                        'has_audio': has_audio,
                        'ext': ext
                    })
                
                if valid_videos:
                    # الترتيب بحيث يتم اختيار أعلى دقة متوفرة مع صوت واضح
                    valid_videos.sort(key=lambda x: (x['has_audio'], x['height']), reverse=True)
                    download_url = valid_videos[0]['url']

            if not download_url:
                download_url = info.get('url')

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title
                })
            else:
                return jsonify({'status': 'error', 'message': 'No valid media link found'}), 500

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '4.7'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
