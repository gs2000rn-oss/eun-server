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
    """استخراج رابط مباشر وصالح يحتوي على الصوت والصورة معاً بدقة، أو الصوت فقط"""
    formats = info.get('formats', [])
    
    if not formats:
        return info.get('url')

    valid_formats = []
    for f in formats:
        u = f.get('url')
        if not u:
            continue
            
        protocol = f.get('protocol', '')
        ext = f.get('ext', '')
        
        # استبعاد روابط m3u8 و manifest المخصصة للبث المباشر
        if '.m3u8' in u or 'm3u8' in protocol or 'manifest' in u or 'dash' in protocol:
            continue
            
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        height = f.get('height', 0) or 0
        abr = f.get('abr', 0) or 0
        
        # التأكد من وجود الصوت والصورة
        has_video = vcodec != 'none' and vcodec is not None
        has_audio = acodec != 'none' and acodec is not None
        
        valid_formats.append({
            'url': u,
            'has_v': has_video,
            'has_a': has_audio,
            'height': height,
            'abr': abr,
            'ext': ext
        })

    if mode == 'audio':
        # 1. البحث عن مسار صوتي فقط (Audio only)
        audio_only = [f for f in valid_formats if f['has_a'] and not f['has_v']]
        if audio_only:
            audio_only.sort(key=lambda x: (x['ext'] == 'm4a', x['abr']), reverse=True)
            return audio_only[0]['url']
        # 2. أي مسار يحتوي على صوت
        any_audio = [f for f in valid_formats if f['has_a']]
        if any_audio:
            return any_audio[0]['url']
    else:
        # فيديو: البحث حصراً عن مسار مدمج بصوت وصورة معا (Progressive)
        combo = [f for f in valid_formats if f['has_v'] and f['has_a']]
        if combo:
            # ترتيب الأفضلية: صيغة MP4 أولاً، ثم أعلى دقة Height
            combo.sort(key=lambda x: (x['ext'] == 'mp4', x['height']), reverse=True)
            return combo[0]['url']

    # في حال عدم التمكن من إيجاد رابط مدمج، يتم إرجاع أول رابط صالح يحتوي على الميديا
    return valid_formats[0]['url'] if valid_formats else info.get('url')

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
            logger.info(f"Resolved Pinterest URL: {url}")
        except Exception as e:
            logger.error(f"Failed to resolve shortlink: {e}")

    logger.info(f"Processing URL: {url} | Mode: {mode}")

    # إعدادات yt_dlp بدون تقييد format لتجنب خطأ Requested format is not available
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'tv_embedded', 'ios', 'android'],
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
                return jsonify({'status': 'error', 'message': 'No valid playable link found'}), 500

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '3.9'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
