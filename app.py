import os
import tempfile
import shutil
from pathlib import Path
from flask import Flask, request, send_file, jsonify, render_template_string
import yt_dlp

app = Flask(__name__)

# مسار cookies.txt من Render Secret Files
COOKIES_PATHS = [
    "/etc/secrets/cookies.txt",  # المسار الرسمي في Render
    "./cookies.txt",             # للاختبار المحلي
    "cookies.txt",
]

def get_cookies_path():
    for path in COOKIES_PATHS:
        if os.path.exists(path):
            return path
    return None


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تحميل فيديوهات يوتيوب</title>
    <style>
        * { box-sizing: border-box; font-family: 'Segoe UI', Tahoma, sans-serif; }
        body { background: #0f0f0f; color: #fff; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .container { background: #1a1a1a; padding: 2rem; border-radius: 16px; width: 100%; max-width: 500px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }
        h1 { text-align: center; color: #ff0000; margin-bottom: 1.5rem; }
        input[type="url"] { width: 100%; padding: 12px 16px; border: 2px solid #333; border-radius: 8px; background: #111; color: #fff; font-size: 16px; margin-bottom: 1rem; }
        input[type="url"]:focus { outline: none; border-color: #ff0000; }
        button { width: 100%; padding: 14px; background: #ff0000; color: white; border: none; border-radius: 8px; font-size: 18px; font-weight: bold; cursor: pointer; transition: 0.2s; }
        button:hover { background: #cc0000; }
        button:disabled { background: #555; cursor: not-allowed; }
        .info { margin-top: 1rem; font-size: 14px; color: #aaa; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⬇️ تحميل من يوتيوب</h1>
        <form id="dlForm" method="POST" action="/download">
            <input type="url" name="url" id="url" placeholder="الصق رابط فيديو يوتيوب هنا..." required>
            <button type="submit" id="btn">تحميل الفيديو</button>
        </form>
        <div class="info">
            يستخدم cookies.txt من Secret Files على Render<br>
            الجودة الأفضل (MP4)
        </div>
    </div>
    <script>
        document.getElementById('dlForm').addEventListener('submit', function() {
            document.getElementById('btn').disabled = true;
            document.getElementById('btn').textContent = 'جاري التحميل... انتظر';
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/download", methods=["POST"])
def download():
    url = request.form.get("url") or (request.json.get("url") if request.is_json else None)
    
    if not url:
        return jsonify({"error": "الرجاء إدخال رابط يوتيوب"}), 400

    cookies = get_cookies_path()
    if not cookies:
        return jsonify({
            "error": "ملف cookies.txt غير موجود. أضفه كـ Secret File باسم cookies.txt في Render"
        }), 500

    temp_dir = tempfile.mkdtemp()
    
    ydl_opts = {
        "format": "bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": os.path.join(temp_dir, "%(title).80s.%(ext)s"),
        "cookiefile": cookies,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                files = list(Path(temp_dir).glob("*"))
                if not files:
                    raise Exception("لم يتم العثور على الملف بعد التحميل")
                filename = str(files[0])

            safe_name = os.path.basename(filename)
            
            return send_file(
                filename,
                as_attachment=True,
                download_name=safe_name,
                mimetype="video/mp4"
            )

    except Exception as e:
        return jsonify({"error": f"فشل التحميل: {str(e)}"}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


@app.route("/health")
def health():
    cookies_ok = get_cookies_path() is not None
    return jsonify({
        "status": "ok",
        "cookies_found": cookies_ok,
        "cookies_path": get_cookies_path()
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
