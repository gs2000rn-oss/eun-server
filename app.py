from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

def setup_cookies():
    secret_cookies = '/etc/secrets/cookies.txt'
    tmp_cookies = '/tmp/cookies.txt'
    if os.path.exists(secret_cookies):
        try:
            shutil.copy(secret_cookies, tmp_cookies)
            return tmp_cookies
        except Exception:
            return secret_cookies
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

@app.route('/download', methods=['GET'])
def download():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    cookie_path = setup_cookies()

    # إلغاء خيار format الصارم نهائياً لتفادي خطأ "Requested format is not available"
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': USER_AGENT,
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'mweb', 'ios'],
            }
        }
    }

    if cookie_path:
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # استخراج معلومات الفيديو بدون فرض صيغة معينة
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract info'}), 500

            title = info.get('title', 'Video')
            download_url = None
            formats = info.get('formats', [])

            if mode == 'audio':
                # اختيار أفضل مسار صوتي متوفر
                audio_formats = [
                    f for f in formats 
                    if f.get('acodec') != 'none' and (not f.get('vcodec') or f.get('vcodec') == 'none')
                ]
                if audio_formats:
                    audio_formats.sort(key=lambda x: x.get('abr') or 0, reverse=True)
                    download_url = audio_formats[0].get('url')
            else:
                # 1. البحث عن صيغة مدمجة (صوت + صورة معاً)
                progressive_formats = [
                    f for f in formats 
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none'
                    and not f.get('url', '').endswith('.m3u8')
                ]
                if progressive_formats:
                    progressive_formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
                    download_url = progressive_formats[0].get('url')

            # 2. إذا لم يجد صيغة مدمجة، يتخذ الرابط المباشر العام للـ info
            if not download_url:
                download_url = info.get('url')

            # 3. خطة احتياطية أخيرة: أخذ آخر صيغة متوفرة في قائمة formats
            if not download_url and formats:
                download_url = formats[-1].get('url')

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title
                })
            else:
                return jsonify({'status': 'error', 'message': 'No playable link found'}), 500

    except Exception as e:
        logger.error(f"yt-dlp error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine Pro'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
