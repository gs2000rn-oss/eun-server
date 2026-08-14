from flask import Flask, request, jsonify
import yt_dlp
import requests
import os

app = Flask(__name__)

# قائمة محدثة وموسعة لـ Invidious
INVIDIOUS_INSTANCES = [
    "https://invidious.nerdvpn.de",
    "https://inv.nadeko.net",
    "https://invidious.flokinet.to",
    "https://yewtu.be",
    "https://vid.priv.au"
]

def get_yt_via_invidious(video_id):
    for instance in INVIDIOUS_INSTANCES:
        try:
            res = requests.get(f"{instance}/api/v1/videos/{video_id}", timeout=5)
            if res.status_code == 200:
                data = res.json()
                # جلب الرابط من formatStreams
                streams = data.get("formatStreams", [])
                if streams:
                    # اختيار أعلى جودة فيديو (غالباً الأخير في القائمة)
                    best_stream = streams[-1]
                    return {
                        'status': 'success',
                        'url': best_stream.get('url'),
                        'title': data.get('title', 'Video')
                    }
        except Exception:
            continue
    return None

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # إعدادات متطورة تحاكي متصفح Desktop لتجاوز حظر Pinterest
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # محاولة جلب الرابط
            download_url = info.get('url') or info.get('redirect_url')
            
            if 'formats' in info and not download_url:
                formats = info['formats']
                if mode == 'audio':
                    valid = [f for f in formats if f.get('vcodec') == 'none']
                else:
                    valid = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
                
                if valid:
                    download_url = valid[-1]['url']

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': info.get('title', 'Video')
                })

    except Exception as e:
        print(f"yt-dlp error: {e}")

    # إذا فشل yt-dlp، نحاول استخراج Video ID ليوتيوب حصراً واستخدام Invidious
    if 'youtube.com' in url or 'youtu.be' in url:
        video_id = None
        if 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0].split('&')[0]
        elif 'watch?v=' in url:
            video_id = url.split('watch?v=')[1].split('?')[0].split('&')[0]
        
        if video_id:
            inv_res = get_yt_via_invidious(video_id)
            if inv_res:
                return jsonify(inv_res)

    return jsonify({'status': 'error', 'message': 'Failed to extract video link. Service might be blocked.'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
