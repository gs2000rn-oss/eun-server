from flask import Flask, request, jsonify
import yt_dlp
import os
import logging
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def get_best_format(formats, mode):
    try:
        if mode == 'audio':
            audio_formats = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
            if audio_formats:
                audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                return audio_formats[0].get('url')
        else:
            complete_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            if complete_formats:
                complete_formats.sort(key=lambda x: x.get('height', 0) or 0, reverse=True)
                return complete_formats[0].get('url')
            
            video_formats = [f for f in formats if f.get('url')]
            if video_formats:
                return video_formats[-1].get('url')
    except Exception as e:
        logger.error(f"Error parsing formats: {e}")
    return None

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # فك روابط Pinterest المختصرة (pin.it)
    if 'pin.it' in url:
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
        'format': 'best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'ios']
            }
        }
    }

    # التحقق من وجود الكوكيز في Render (Secret File) أو محلياً
    if os.path.exists('/etc/secrets/cookies.txt'):
        ydl_opts['cookiefile'] = '/etc/secrets/cookies.txt'
        logger.info("Using Render Secret Cookies file.")
    elif os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
        logger.info("Using local cookies.txt file.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Failed to extract media'}), 500

            download_url = info.get('url')
            title = info.get('title', 'Downloaded_Media')

            if 'formats' in info:
                extracted_url = get_best_format(info['formats'], mode)
                if extracted_url:
                    download_url = extracted_url

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': title
                })
            else:
                return jsonify({'status': 'error', 'message': 'Stream URL not found'}), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Extraction failed: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'online', 'service': 'Shark Engine', 'version': '3.2'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
