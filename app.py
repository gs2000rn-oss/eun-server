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

def resolve_url_if_needed(url):
    """فك توجيه روابط pin.it فقط دون المساس بروابط يوتيوب"""
    if 'pin.it' in url or 'pinterest.com' in url:
        try:
            res = requests.get(url, allow_redirects=True, timeout=5, headers={'User-Agent': USER_AGENT})
            return res.url
        except Exception as e:
            logger.error(f"Pinterest resolve error: {e}")
    return url

@app.route('/download', methods=['GET'])
def download():
    raw_url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not raw_url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 200

    # 1. التمييز بين بينترست وباقي المواقع
    target_url = resolve_url_if_needed(raw_url)
    is_pinterest = 'pinterest' in target_url or 'pin.it' in raw_url

    # 2. إعدادات عامة وآمنة لـ yt-dlp
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': USER_AGENT
        }
    }

    # إضافة Referer فقط إذا كان الطلب لبينترست
    if is_pinterest:
        ydl_opts['http_headers']['Referer'] = 'https://www.pinterest.com/'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract info'}), 200

            title = info.get('title', 'Downloaded Video')
            formats = info.get('formats', [])
            download_url = None

            if is_pinterest:
                # --- معالجة خاصة لبينترست: البحث عن MP4 واستبعاد m3u8 ---
                for f in reversed(formats):
                    f_url = f.get('url', '')
                    ext = f.get('ext', '')
                    if (ext == 'mp4' or '.mp4' in f_url) and '.m3u8' not in f_url:
                        download_url = f_url
                        break
                
                if not download_url:
                    main_url = info.get('url', '')
                    if main_url and '.m3u8' not in main_url:
                        download_url = main_url

            else:
                # --- معالجة يوتيوب وباقي المنصات ---
                if mode == 'audio':
                    audio_fmt = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                    if audio_fmt:
                        download_url = audio_fmt[-1].get('url')
                else:
                    # تصفية الفيديو لاستخراج فيديو + صوت مدمج
                    prog_fmt = [
                        f for f in formats 
                        if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and not f.get('url', '').endswith('.m3u8')
                    ]
                    if prog_fmt:
                        prog_fmt.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0), reverse=True)
                        download_url = prog_fmt[0].get('url')

                if not download_url:
                    download_url = info.get('url')

                if not download_url and formats:
                    download_url = formats[-1].get('url')

            # 3. إرجاع النتيجة
            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title
                }), 200
            else:
                return jsonify({'status': 'error', 'message': 'No direct playable link found'}), 200

    except Exception as e:
        logger.error(f"Server Exception: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
