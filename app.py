from flask import Flask, request, jsonify
import yt_dlp
import os
import shutil

app = Flask(__name__)

def get_cookie_path():
    secret_path = '/etc/secrets/cookies.txt'
    tmp_path = '/tmp/cookies.txt'
    if os.path.exists(secret_path):
        try:
            shutil.copy(secret_path, tmp_path)
            return tmp_path
        except Exception:
            return secret_path
    return None

@app.route('/download', methods=['GET'])
def download():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 200

    # خيارات خفيفة بدون فرض صيغة محددة لتفادي خطأ Requested format is not available
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }

    cookie_file = get_cookie_path()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            download_url = None

            if mode == 'audio':
                # استخراج رابط الصوت فقط
                audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                if audio_formats:
                    download_url = audio_formats[-1].get('url')
            else:
                # استخراج رابط فيديو مدمج (صوت + صورة)
                prog_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') != 'none']
                if prog_formats:
                    download_url = prog_formats[-1].get('url')

            # خيار احتياطي في حال عدم وجود صيغة مدمجة
            if not download_url:
                download_url = info.get('url')
            if not download_url and formats:
                download_url = formats[-1].get('url')

            if download_url:
                return jsonify({
                    'status': 'success',
                    'url': download_url,
                    'title': info.get('title', 'Video')
                }), 200
            else:
                return jsonify({'status': 'error', 'message': 'No URL found'}), 200

    except Exception as e:
        # إرجاع الخطأ بتنسيق JSON وبكود 200 حتى يقرأه الأندرويد بوضوح
        return jsonify({'status': 'error', 'message': str(e)}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
