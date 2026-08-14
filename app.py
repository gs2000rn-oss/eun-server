from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil
import logging
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

def setup_cookies():
    """نسخ ملف الكوكيز من Render Secrets إلى مجلد /tmp القابل للكتابة"""
    secret_cookies = '/etc/secrets/cookies.txt'
    tmp_cookies = '/tmp/cookies.txt'
    
    if os.path.exists(secret_cookies):
        try:
            shutil.copy(secret_cookies, tmp_cookies)
            logger.info("Successfully copied cookies from /etc/secrets/cookies.txt to /tmp/cookies.txt")
            return tmp_cookies
        except Exception as e:
            logger.error(f"Failed to copy cookies: {e}")
            return secret_cookies
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

def extract_combined_url(info, mode):
    """استخراج رابط مباشر يحتوي على الصوت والصورة مدمجين معاً بدون نقص"""
    formats = info.get('formats', [])
    if not formats:
        return info.get('url')

    if mode == 'audio':
        # 1. البحث عن مسار صوتي فقط (Audio only)
        audio_only = [
            f for f in formats 
            if f.get('acodec') and f.get('acodec') != 'none' 
            and (not f.get('vcodec') or f.get('vcodec') == 'none')
        ]
        if audio_only:
            audio_only.sort(key=lambda x: x.get('abr') or 0, reverse=True)
            return audio_only[0].get('url')
        
        # احتياطي: أي مسار يحتوي على صوت
        any_audio = [f for f in formats if f.get('acodec') and f.get('acodec') != 'none']
        if any_audio:
            return any_audio[0].get('url')
    else:
        # 2. فيديو: تصفية الروابط واختيار فقط الروابط المدمجة (صوت + صورة)
        progressive_formats = [
            f for f in formats 
            if f.get('vcodec') and f.get('vcodec') != 'none' 
            and f.get('acodec') and f.get('acodec') != 'none'
            and '.m3u8' not in f.get('url', '')
            and 'manifest' not in f.get('url', '')
        ]

        if progressive_formats:
            # فرز النتائج: إعطاء الأولوية لصيغة mp4 ثم لأعلى دقة متوفرة
            progressive_formats.sort(
                key=lambda x: (x.get('ext') == 'mp4', x.get('height') or 0), 
                reverse=True
            )
            return progressive_formats[0].get('url')

    # في حال لم يجد، يرجع الرابط الرئيسي
    return info.get('url')

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # فك روابط Pinterest المختصرة
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
        'http_headers': {
            'User-Agent': USER_AGENT,
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'mweb'],
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
            download_url = extract_combined_url(info, mode)

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title,
                    'user_agent': USER_AGENT
                })
            else:
                return jsonify({'status': 'error', 'message': 'No valid playable link found'}), 500

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '5.1'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
