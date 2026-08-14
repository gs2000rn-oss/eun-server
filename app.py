from flask import Flask, request, jsonify
import yt_dlp
import requests
import os

app = Flask(__name__)

def get_yt_via_invidious(video_id):
    """خيار احتياطي مجاني وسريع لاستخراج رابط الفيديو عند حظر يوتيوب للـ IP"""
    instances = [
        "https://invidious.nerdvpn.de",
        "https://inv.nadeko.net",
        "https://invidious.flokinet.to"
    ]
    for instance in instances:
        try:
            res = requests.get(f"{instance}/api/v1/videos/{video_id}", timeout=6)
            if res.status_code == 200:
                data = res.json()
                format_streams = data.get("formatStreams", [])
                if format_streams:
                    # اختيار أعلى جودة تحتوي على فيديو وصوت معاً
                    best_stream = format_streams[-1]
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

    # استخراج Video ID من رابط يوتيوب
    video_id = None
    if 'youtu.be/' in url:
        video_id = url.split('youtu.be/')[1].split('?')[0].split('&')[0]
    elif 'watch?v=' in url:
        video_id = url.split('watch?v=')[1].split('?')[0].split('&')[0]

    # 1. التجربة عبر yt-dlp مع التظاهر بتطبيق أندرويد رسميا
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
            }
        },
        'http_headers': {
            'User-Agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 11; gts7xl) gzip',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            download_url = info.get('url')

            if 'formats' in info and not download_url:
                formats = info['formats']
                if mode == 'audio':
                    valid = [f for f in formats if f.get('url') and f.get('vcodec') == 'none']
                else:
                    valid = [f for f in formats if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none']
                
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

    # 2. إذا فشل yt-dlp بسبب حظر الـ IP، يتم الاستخراج فوراً عبر شبكة Invidious
    if video_id:
        inv_res = get_yt_via_invidious(video_id)
        if inv_res:
            return jsonify(inv_res)

    return jsonify({'status': 'error', 'message': 'Failed to extract video link'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
