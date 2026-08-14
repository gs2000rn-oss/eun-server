from flask import Flask, request, jsonify
import yt_dlp
import os

app = Flask(__name__)

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # إعدادات متشددة للمحاكاة
    ydl_opts = {
        'quiet': False, # سأجعلها False لنرى الأخطاء في الـ Logs
        'no_warnings': False,
        'format': 'best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"DEBUG: Attempting to extract: {url}")
            info = ydl.extract_info(url, download=False)
            download_url = info.get('url') or info.get('redirect_url')
            
            if 'formats' in info and not download_url:
                formats = info['formats']
                valid = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
                if valid:
                    download_url = valid[-1]['url']

            if download_url:
                return jsonify({'status': 'success', 'url': download_url, 'title': info.get('title', 'Video')})
            else:
                return jsonify({'status': 'error', 'message': 'No video URL found'}), 500

    except Exception as e:
        error_msg = str(e)
        print(f"DEBUG_ERROR: {error_msg}")
        return jsonify({'status': 'error', 'message': error_msg}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
