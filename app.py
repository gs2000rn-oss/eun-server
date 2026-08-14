from flask import Flask, request, jsonify
import yt_dlp
import os

app = Flask(__name__)

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    # إعدادات متقدمة لتجاوز حظر Datacenter IPs من يوتيوب
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            download_url = info.get('url')

            # تصفية الصيغ لاختيار رابط مباشر يعمل مع أندرويد
            if 'formats' in info:
                formats = info['formats']
                
                if mode == 'audio':
                    # البحث عن أعلى جودة صوت
                    audio_formats = [
                        f for f in formats 
                        if f.get('url') and f.get('vcodec') == 'none' and f.get('acodec') != 'none'
                    ]
                    if audio_formats:
                        download_url = audio_formats[-1]['url']
                else:
                    # البحث عن صيغة مدمجة (فيديو + صوت معاً)
                    combo_formats = [
                        f for f in formats 
                        if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none'
                    ]
                    if combo_formats:
                        download_url = combo_formats[-1]['url']

            # إذا لم يتم العثور على صيغة مدمجة، نأخذ آخر رابط متوفر
            if not download_url and 'formats' in info:
                valid_formats = [f for f in info['formats'] if f.get('url')]
                if valid_formats:
                    download_url = valid_formats[-1]['url']

            if not download_url:
                return jsonify({'status': 'error', 'message': 'Could not extract direct URL'}), 400

            return jsonify({
                'status': 'success',
                'url': download_url,
                'title': info.get('title', 'Video')
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
