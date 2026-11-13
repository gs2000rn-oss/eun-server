import os
import json
import requests
from flask import Flask, jsonify, Response, stream_with_context

app = Flask(__name__)

BASE = "http://cf.egg-s10.xyz:80"
USER = "f7622b9dd016"
PASS = "0998a344f2"

@app.route("/")
def home():
    return "Xtream Advanced Proxy - Max Connections Bypass Active"

@app.route("/channels")
def channels():
    try:
        with open("channels.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stream/<path:sid>")
def stream(sid):
    # بناء رابط البث الأصلي
    original_url = f"{BASE}/live/{USER}/{PASS}/{sid}"
    
    try:
        # إرسال طلب إلى السيرفر الأصلي مع الحفاظ على اتصال واحد مستمر
        # استخدام stream=True لتدفق البيانات مباشرة دون تحميلها بالكامل في الذاكرة
        req = requests.get(original_url, stream=True, timeout=15)
        
        # التأكد من أن الاستجابة ناجحة
        if req.status_code != 200:
            return jsonify({"error": "Failed to connect to stream source", "status_code": req.status_code}), 502

        # جلب نوع المحتوى (Content-Type) الحقيقي من السيرفر الأصلي لضمان توافق المشغل
        content_type = req.headers.get('Content-Type', 'video/mp2t')

        # دالة لتدفق البيانات للمستخدمين دون فتح اتصال جديد مع السيرفر الأصلي
        def generate():
            try:
                for chunk in req.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception:
                # التعامل مع انقطاع اتصال العميل بسلاسة
                pass

        return Response(stream_with_context(generate()), content_type=content_type)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Connection error: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
