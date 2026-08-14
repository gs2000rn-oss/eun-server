from flask import Flask, request, jsonify
import yt_dlp
import requests

app = Flask(__name__)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

def get_real_pinterest_url(url):
    """فك اختصار pin.it للحصول على الرابط الأصلي"""
    try:
        res = requests.get(url, allow_redirects=True, timeout=5, headers={'User-Agent': USER_AGENT})
        return res.url
    except Exception:
        return url

@app.route('/download', methods=['GET'])
def download():
    raw_url = request.args.get('url')
    if not raw_url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 200

    target_url = get_real_pinterest_url(raw_url)

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        # تجنب صيغ m3u8 و hls كلياً والبحث عن mp4 مباشر
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'http_headers': {
            'User-Agent': USER_AGENT,
            'Referer': 'https://www.pinterest.com/'
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            formats = info.get('formats', [])
            
            clean_mp4_url = None

            # التفتيش في قائمة الصيغ لتجاهل أي رابط m3u8
            for f in reversed(formats):
                f_url = f.get('url', '')
                ext = f.get('ext', '')
                
                # إستبعاد m3u8 نهائياً لضمان عدم ظهور 00:00
                if (ext == 'mp4' or '.mp4' in f_url) and '.m3u8' not in f_url:
                    clean_mp4_url = f_url
                    break

            if not clean_mp4_url:
                main_url = info.get('url', '')
                if '.m3u8' not in main_url:
                    clean_mp4_url = main_url

            if clean_mp4_url:
                return jsonify({
                    'status': 'success',
                    'url': clean_mp4_url,
                    'title': info.get('title', 'Pinterest Video')
                }), 200
            else:
                return jsonify({'status': 'error', 'message': 'No direct MP4 found'}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 200
