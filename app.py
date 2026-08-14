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

def get_best_direct_url(info, mode):
    """استخراج رابط MP4/MP3 مباشر يتوافق مع Android DownloadManager وتجنب روابط m3u8"""
    formats = info.get('formats', [])
    
    valid_formats = []
    for f in formats:
        url = f.get('url', '')
        protocol = f.get('protocol', '')
        
        # استبعاد روابط HLS / m3u8 لأن Android DownloadManager لا يقرأها كملف mp4
        if not url or '.m3u8' in url or 'm3u8' in protocol:
            continue
            
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        height = f.get('height', 0) or 0
        abr = f.get('abr', 0) or 0
        
        valid_formats.append({
            'url': url,
            'vcodec': vcodec,
            'acodec': acodec,
            'height': height,
            'abr': abr,
            'has_video': vcodec != 'none',
            'has_audio': acodec != 'none'
        })

    if mode == 'audio':
        audio_formats = [f for f in valid_formats if f['has_audio']]
        if audio_formats:
            audio_formats.sort(key=lambda x: x['abr'], reverse=True)
            return audio_formats[0]['url']
    else:
        # 1. البحث عن صيغة تحتوي على فيديو وصوت معاً (Progressive MP4)
        complete_formats = [f for f in valid_formats if f['has_video'] and f['has_audio']]
        if complete_formats:
            complete_formats.sort(key=lambda x: x['height'], reverse=True)
            return complete_formats[0]['url']
        
        # 2. البحث عن أي فيديو متاح بدون m3u8
        video_formats = [f for f in valid_formats if f['has_video']]
        if video_formats:
            video_formats.sort(key=lambda x: x['height'], reverse=True)
            return video_formats[0]['url']

    # في حال عدم وجود قائمة صيغ متوافقة، التأكد من أن الرابط الرئيسي ليس m3u8
    main_url = info.get('url')
    if main_url and '.m3u8' not in main_url:
        return main_url

    return valid_formats[0]['url'] if valid_formats else None

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

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
        # إجبار yt-dlp على اختيار صيغة كاملة مدمجة لا تتطلب ffmpeg
        'format': 'b/best[ext=mp4]/best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android_vr', 'web_creator', 'mweb', 'ios'],
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
            download_url = get_best_direct_url(info, mode)

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title
                })
            else:
                return jsonify({'status': 'error', 'message': 'No direct playable MP4 link found'}), 500

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '3.5'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
