from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# استخدام واجهة Cobalt البرمجية (API)
COBALT_API_URL = "https://api.cobalt.tools/api/json"

@app.route('/download', methods=['GET'])
def get_download_link():
    url = request.args.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided'}), 400

    payload = {
        "url": url,
        "vCodec": "h264",
        "vQuality": "720",
        "disableMetadata": True
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    try:
        # إرسال الطلب لخدمة Cobalt
        response = requests.post(COBALT_API_URL, json=payload, headers=headers, timeout=10)
        data = response.json()

        # إذا نجحت العملية
        if data.get("status") == "tunnel" or data.get("status") == "success":
            return jsonify({
                'status': 'success',
                'url': data.get("url"),
                'title': data.get("filename", "Video")
            })
        elif data.get("status") == "error":
            return jsonify({'status': 'error', 'message': data.get("text", "Cobalt error")}), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({'status': 'error', 'message': 'Failed to reach downloader service'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
