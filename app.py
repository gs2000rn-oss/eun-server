from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil
import logging
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def get_cookies_file():
    secret_cookies = '/etc/secrets/cookies.txt'
    tmp_cookies = '/tmp/cookies.txt'
    if os.path.exists(secret_cookies):
        try:
            shutil.copy(secret_cookies, tmp_cookies)
            return tmp_cookies
        except Exception:
            pass
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # حل روابط التوجيه القصيرة
    if 'pin.it' in url or 'pinterest' in url:
        try:
            res = requests.head(url, allow_redirects=True, timeout=5)
            url = res.url
        except Exception:
            pass

    logger.info(f"Processing URL: {url} | Mode: {mode}")
    cookie_path = get_cookies_file()

    def try_extract(use_cookies):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'format': 'best[ext=mp4]/best' if mode == 'video' else 'bestaudio/best',
            'extractor_args': {
                'youtube': {
                    'player_client': ['web', 'mweb']
                }
            }
        }
        if use_cookies and cookie_path and os.path.exists(cookie_path):
            ydl_opts['cookiefile'] = cookie_path
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = None
    # محاولة الاستخراج مع الكوكيز، وإن فشلت، يتم السحب تلقائياً بدونها لتفادي التوقف التام
    try:
        if cookie_path:
            try:
                info = try_extract(True)
            except Exception as e:
                logger.warning(f"Cookies extraction failed, retrying without cookies: {e}")
                info = try_extract(False)
        else:
            info = try_extract(False)
    except Exception as e:
        logger.error(f"All extraction attempts failed: {e}")
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500

    if not info:
        return jsonify({'status': 'error', 'message': 'No info returned'}), 500

    title = info.get('title', 'Downloaded_Media')
    download_url = info.get('url')

    # تصفية الصيغ واستبعاد الـ Storyboards تماماً في حال عدم وجود الرابط المباشر
    if not download_url and 'formats' in info:
        for f in info['formats']:
            f_url = f.get('url')
            f_id = str(f.get('format_id', '')).lower()
            vcodec = str(f.get('vcodec', '')).lower()
            
            if f_id.startswith('sb') or 'storyboard' in f_id:
                continue
            if vcodec in ['none', 'null', '']:
                continue
            if f_url:
                download_url = f_url
                break

    if download_url:
        return jsonify({
            'status': 'success',
            'url': download_url,
            'title': title
        })
    else:
        return jsonify({'status': 'error', 'message': 'No valid media link found'}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '5.0'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
