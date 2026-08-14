from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import shutil
import logging
import tempfile
import traceback
import subprocess
import requests
from pathlib import Path
from urllib.parse import quote

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def setup_cookies():
    secret = '/etc/secrets/cookies.txt'
    tmp = '/tmp/cookies.txt'
    if os.path.exists(secret):
        try:
            shutil.copy(secret, tmp)
            return tmp
        except Exception as e:
            logger.error(f"Cookie copy: {e}")
            return secret
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

def resolve_short_url(url):
    try:
        shorts = ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co', 'bit.ly']
        if any(d in url for d in shorts):
            r = requests.head(url, allow_redirects=True, timeout=12,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})
            if r.url and r.url != url:
                logger.info(f"Resolved → {r.url}")
                return r.url
    except Exception as e:
        logger.warning(f"resolve: {e}")
    return url

def ffprobe_streams(path):
    try:
        v = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=20)
        a = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=20)
        has_v = 'video' in (v.stdout or '')
        has_a = 'audio' in (a.stdout or '')
        return has_v, has_a
    except Exception:
        return True, True

def ffmpeg_merge(video_path, audio_path, out_path):
    cmd = [
        'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
        '-map', '0:v:0', '-map', '1:a:0', '-shortest',
        out_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10000

def download_url_to_file(file_url, dest_path, headers=None):
    r = requests.get(file_url, headers=headers or {}, timeout=60, stream=True)
    if r.status_code != 200:
        return False
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(65536):
            if chunk:
                f.write(chunk)
    return os.path.getsize(dest_path) > 1000

def save_image_response(img_url, temp_dir, title, headers=None):
    headers = headers or {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://www.tiktok.com/',
    }
    r = requests.get(img_url, headers=headers, timeout=40)
    if r.status_code != 200 or len(r.content) < 1500:
        return None, None, None
    ctype = (r.headers.get('Content-Type') or '').lower()
    low = img_url.lower()
    if 'png' in ctype or '.png' in low:
        ext, mime = 'png', 'image/png'
    elif 'webp' in ctype or '.webp' in low:
        ext, mime = 'webp', 'image/webp'
    else:
        ext, mime = 'jpg', 'image/jpeg'
    path = os.path.join(temp_dir, f'image.{ext}')
    open(path, 'wb').write(r.content)
    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in (title or 'tiktok_photo')).strip() or 'tiktok_photo'
    safe = safe[:40] + f'.{ext}'
    return path, mime, safe

def handle_tiktok_photo(url, temp_dir):
    """
    منشورات تيك توك /photo/ → صور
    yt-dlp ما يدعمها، لذلك نستخدم TikWM
    """
    try:
        api = f'https://www.tikwm.com/api/?url={quote(url, safe="")}'
        r = requests.get(api, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get('code') != 0 or not j.get('data'):
            return None
        data = j['data']
        title = (data.get('title') or data.get('id') or 'tiktok_photo')[:55]

        images = data.get('images') or []
        # لو ما في images بس duration=0 و cover photomode
        if not images:
            cover = data.get('cover') or data.get('origin_cover') or data.get('ai_dynamic_cover')
            # play = audio فقط في photo mode
            play = (data.get('play') or '')
            if cover and (data.get('duration') == 0 or 'photomode' in cover or 'audio' in play):
                images = [cover]

        if not images:
            return None

        # أفضل صورة (غالباً الأولى هي الأصلية)
        # نفضّل jpeg الأصلي على cover المصغّر
        best = images[0]
        for im in images:
            if 'photomode-image.jpeg' in im or 'image.jpeg' in im:
                best = im
                break

        # جودة أعلى: استبدال cover بحجم أكبر إن أمكن
        if 'tplv-photomode-image-cover' in best:
            # نجرب بدون تصغير
            best2 = best.replace(':640:0:q70', ':0:0:q100').replace('q70', 'q100')
            best = best2

        logger.info(f"TikTok PHOTO mode → image: {best[:80]}...")
        path, mime, safe = save_image_response(best, temp_dir, title)
        if path:
            return path, mime, safe
    except Exception as e:
        logger.error(f"handle_tiktok_photo: {e}")
    return None

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '20-tiktok-photo-fix',
        'supports': ['Instagram', 'Facebook', 'TikTok video+photo', 'Pinterest', 'X']
    })

@app.route('/health')
def health():
    c = setup_cookies()
    ok = bool(c and os.path.exists(c))
    return jsonify({
        'status': 'ok',
        'cookies_found': ok,
        'cookies_size': os.path.getsize(c) if ok else 0
    })

@app.route('/download', methods=['GET', 'POST'])
def download():
    url = request.args.get('url') or request.form.get('url')
    mode = request.args.get('mode', 'video')

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL'}), 400

    if any(x in url for x in ['youtube.com', 'youtu.be', 'youtube-nocookie.com']):
        return jsonify({'status': 'error', 'message': 'YouTube not supported on free server'}), 400

    url = resolve_short_url(url)
    logger.info(f"DOWNLOAD → {url}")

    is_tw = any(x in url for x in ['twitter.com', 'x.com', 't.co'])
    is_pin = 'pinterest' in url or 'pin.it' in url
    is_ig = 'instagram.com' in url
    is_fb = 'facebook.com' in url or 'fb.watch' in url or 'fb.me' in url
    is_tt = any(x in url for x in ['tiktok.com', 'douyin.com', 'vt.tiktok.com', 'vm.tiktok.com'])

    temp_dir = tempfile.mkdtemp(prefix='dl_')

    # ========== تيك توك PHOTO MODE ==========
    # مثال: /photo/7673...  → لازم صورة مو MP3
    if is_tt and ('/photo/' in url or mode == 'image'):
        result = handle_tiktok_photo(url, temp_dir)
        if result:
            path, mime, safe = result
            return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
        # حتى لو فشل الكشف من الرابط، نكمّل ونفحص لاحقاً

    # فحص مبكر لكل تيك توك (أحياناً الرابط القصير ما يبين photo)
    if is_tt and mode != 'audio':
        result = handle_tiktok_photo(url, temp_dir)
        if result:
            path, mime, safe = result
            # تأكد إنها صورة حقيقية مش فاضي
            if path and os.path.getsize(path) > 5000:
                # فقط إذا API قال images (photo mode)
                # handle_tiktok_photo يرجع فقط عند وجود images
                return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)

    outtmpl = os.path.join(temp_dir, 'out.%(ext)s')

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 12,
        'fragment_retries': 12,
        'socket_timeout': 60,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

    if is_tw:
        ydl_opts['http_headers']['Referer'] = 'https://x.com/'
        ydl_opts['http_headers']['Origin'] = 'https://x.com'
        ydl_opts['format'] = 'best[ext=mp4]/bestvideo+bestaudio/best'
        ydl_opts['extractor_args'] = {
            'twitter': {'api': ['syndication', 'graphql', 'legacy']}
        }
    elif is_pin:
        ydl_opts['http_headers']['Referer'] = 'https://www.pinterest.com/'
        ydl_opts['format'] = 'best/bestvideo+bestaudio'
    elif is_ig:
        ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
    elif is_fb:
        ydl_opts['http_headers']['Referer'] = 'https://www.facebook.com/'
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
    elif is_tt:
        ydl_opts['http_headers']['Referer'] = 'https://www.tiktok.com/'
        ydl_opts['format'] = (
            'best[ext=mp4][acodec!=none]/'
            'bestvideo[ext=mp4]+bestaudio/'
            'bestvideo+bestaudio/'
            'best'
        )
        ydl_opts['merge_output_format'] = 'mp4'
        ydl_opts['socket_timeout'] = 90
        ydl_opts['retries'] = 20

    if mode == 'audio':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    cookie = setup_cookies()
    if cookie:
        ydl_opts['cookiefile'] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = (info.get('title') or info.get('id') or 'media')[:55]

            files = [f for f in Path(temp_dir).rglob('*')
                     if f.is_file() and f.stat().st_size > 3000
                     and not f.name.endswith(('.json', '.vtt', '.ytdl'))]

            if not files:
                # ربما photo mode
                if is_tt:
                    result = handle_tiktok_photo(url, temp_dir)
                    if result:
                        path, mime, safe = result
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                return jsonify({'status': 'error', 'message': 'No media file'}), 500

            filepath = str(max(files, key=lambda p: p.stat().st_size))
            size = os.path.getsize(filepath)
            low = filepath.lower()

            # لو طلع صوت فقط من تيك توك → هذا photo mode غالباً
            if is_tt and mode != 'audio':
                is_audio_file = low.endswith(('.mp3', '.m4a', '.aac', '.opus'))
                has_v, has_a = ffprobe_streams(filepath)
                if is_audio_file or (has_a and not has_v):
                    logger.warning("TikTok returned AUDIO only → trying photo images")
                    result = handle_tiktok_photo(url, temp_dir)
                    if result:
                        path, mime, safe = result
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)

            # صورة
            if low.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                mime = 'image/jpeg'
                if low.endswith('.png'):
                    mime = 'image/png'
                elif low.endswith('.webp'):
                    mime = 'image/webp'
                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'image'
                safe = safe[:40] + Path(filepath).suffix
                return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)

            # فيديو بدون صوت (تيك توك طويل) → دمج
            if is_tt and mode != 'audio':
                has_v, has_a = ffprobe_streams(filepath)
                if has_v and not has_a:
                    audio_dir = tempfile.mkdtemp(prefix='aud_')
                    try:
                        audio_opts = {
                            'outtmpl': os.path.join(audio_dir, 'audio.%(ext)s'),
                            'format': 'bestaudio/best',
                            'quiet': True,
                            'no_warnings': True,
                            'http_headers': ydl_opts.get('http_headers') or {},
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'm4a',
                            }],
                        }
                        if cookie:
                            audio_opts['cookiefile'] = cookie
                        with yt_dlp.YoutubeDL(audio_opts) as ydl_a:
                            ydl_a.extract_info(url, download=True)
                        auds = [f for f in Path(audio_dir).rglob('*') if f.is_file() and f.stat().st_size > 1000]
                        if auds:
                            merged = os.path.join(temp_dir, 'merged.mp4')
                            if ffmpeg_merge(filepath, str(max(auds, key=lambda p: p.stat().st_size)), merged):
                                filepath = merged
                                size = os.path.getsize(filepath)
                    finally:
                        shutil.rmtree(audio_dir, ignore_errors=True)

            if mode == 'audio' or low.endswith(('.mp3', '.m4a')):
                # فقط إذا المستخدم طلب صوت
                if mode == 'audio':
                    mime = 'audio/mpeg' if low.endswith('.mp3') else 'audio/mp4'
                    ext = '.mp3' if low.endswith('.mp3') else Path(filepath).suffix
                    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'audio'
                    safe = safe[:40] + ext
                    return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)
                # غير ذلك: لا ترجع mp3 كفيديو
                if is_tt:
                    result = handle_tiktok_photo(url, temp_dir)
                    if result:
                        path, mime, safe = result
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                return jsonify({'status': 'error', 'message': 'Got audio only (photo post?)'}), 500

            if size < 20000:
                return jsonify({'status': 'error', 'message': 'File too small'}), 500

            logger.info(f"OK VIDEO: {size/1024/1024:.2f}MB | {title[:30]}")
            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
            safe = safe[:40] + '.mp4'
            return send_file(filepath, mimetype='video/mp4', as_attachment=True, download_name=safe)

    except Exception as e:
        err = str(e)
        logger.error(traceback.format_exc())

        # Unsupported URL لـ /photo/ → صور
        if is_tt and mode != 'audio':
            result = handle_tiktok_photo(url, temp_dir)
            if result:
                path, mime, safe = result
                return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)

        return jsonify({'status': 'error', 'message': err[:350]}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
