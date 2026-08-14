from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import shutil
import logging
import tempfile
import traceback
from pathlib import Path

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
        import requests
        shorts = ['pin.it', 'vm.tiktok.com', 'vt.tiktok.com', 'fb.watch', 't.co', 'bit.ly']
        if any(d in url for d in shorts):
            r = requests.head(url, allow_redirects=True, timeout=12,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})
            if r.url and r.url != url:
                return r.url
    except:
        pass
    return url

def pick_best_image(info):
    """أعلى جودة صورة ممكنة (يفضل 4K / original)"""
    candidates = []

    # thumbnails من yt-dlp
    for t in (info.get('thumbnails') or []):
        u = t.get('url')
        if not u:
            continue
        w = t.get('width') or 0
        h = t.get('height') or 0
        # استبعاد صور صغيرة جداً
        if w < 200 and h < 200 and w != 0:
            continue
        score = (w * h) if (w and h) else 0
        # تفضيل روابط original / full / 4k
        low = u.lower()
        if any(x in low for x in ['original', 'full', '4k', '1080', 'large', 'o1']):
            score += 50_000_000
        candidates.append((score, u, w, h))

    # بعض المنصات تضع الصورة في formats كـ jpg
    for f in (info.get('formats') or []):
        u = f.get('url')
        if not u:
            continue
        ext = str(f.get('ext') or '').lower()
        vcodec = str(f.get('vcodec') or 'none').lower()
        if ext in ['jpg', 'jpeg', 'png', 'webp'] or vcodec in ['none', ''] and any(x in u.lower() for x in ['.jpg', '.jpeg', '.png', '.webp']):
            w = f.get('width') or 0
            h = f.get('height') or 0
            score = (w * h) if (w and h) else 1
            candidates.append((score, u, w, h))

    # url مباشر إذا كان صورة
    main = info.get('url')
    if main and any(x in main.lower() for x in ['.jpg', '.jpeg', '.png', '.webp']):
        candidates.append((10_000_000, main, 0, 0))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0]
    logger.info(f"Best image: {best[2]}x{best[3]} score={best[0]}")
    return best[1]

def is_image_entry(info):
    """هل المحتوى صورة؟"""
    # duration 0 أو None + ما في فيديو حقيقي
    duration = info.get('duration')
    formats = info.get('formats') or []

    has_real_video = False
    for f in formats:
        vcodec = str(f.get('vcodec') or 'none').lower()
        ext = str(f.get('ext') or '').lower()
        if vcodec not in ('none', '', 'null') and ext not in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
            has_real_video = True
            break
        # m3u8 / mp4 بدون vcodec أحياناً
        if ext in ('mp4', 'webm', 'm4v') and f.get('height'):
            has_real_video = True
            break

    if has_real_video and duration and duration > 0.5:
        return False

    # إنستغرام/بينترست صور
    if info.get('_type') == 'playlist':
        return False

    # إذا ما في فيديو حقيقي
    if not has_real_video:
        return True

    if duration is not None and duration <= 0.3:
        return True

    return False

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '15-images-and-videos',
        'features': 'video + image (max quality / 4K when available)'
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
    mode = request.args.get('mode', 'video')  # video | audio | image

    if not url:
        return jsonify({'status': 'error', 'message': 'No URL'}), 400

    # نرفض يوتيوب بهدوء (زي ما طلبت)
    if any(x in url for x in ['youtube.com', 'youtu.be', 'youtube-nocookie.com']):
        return jsonify({
            'status': 'error',
            'message': 'YouTube not supported on free server. Use other platforms.'
        }), 400

    url = resolve_short_url(url)
    logger.info(f"→ {url} mode={mode}")

    is_tw = any(x in url for x in ['twitter.com', 'x.com', 't.co'])
    is_pin = 'pinterest' in url or 'pin.it' in url
    is_ig = 'instagram.com' in url
    is_fb = 'facebook.com' in url or 'fb.watch' in url
    is_tt = 'tiktok.com' in url or 'douyin.com' in url

    temp_dir = tempfile.mkdtemp(prefix='dl_')
    outtmpl = os.path.join(temp_dir, 'out.%(ext)s')

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 40,
        'writethumbnail': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': '*/*',
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
        ydl_opts['extractor_args'] = {'twitter': {'api': ['syndication', 'graphql', 'legacy']}}
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
        ydl_opts['format'] = 'best'

    # صور: نخلي yt-dlp يجيب كل شيء
    if mode == 'image':
        ydl_opts['format'] = 'best'
        ydl_opts.pop('postprocessors', None)

    cookie = setup_cookies()
    if cookie:
        ydl_opts['cookiefile'] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # أولاً extract بدون تحميل لنعرف إذا صورة أو فيديو
            info = ydl.extract_info(url, download=False)

            # carousel / album → أول عنصر
            if info.get('_type') == 'playlist' and info.get('entries'):
                entries = [e for e in info['entries'] if e]
                if entries:
                    info = entries[0]
                    # نعيد extract للعنصر
                    if info.get('url') or info.get('id'):
                        try:
                            entry_url = info.get('webpage_url') or info.get('original_url') or url
                            info = ydl.extract_info(entry_url, download=False)
                        except:
                            pass

            title = (info.get('title') or info.get('id') or 'media')[:55]
            want_image = (mode == 'image') or is_image_entry(info)

            # ========== صورة ==========
            if want_image:
                img_url = pick_best_image(info)
                if not img_url:
                    # محاولة أخيرة: thumbnail
                    img_url = info.get('thumbnail')

                if not img_url:
                    return jsonify({'status': 'error', 'message': 'No image found'}), 500

                # نحمل الصورة بـ requests
                import requests
                headers = dict(ydl_opts.get('http_headers') or {})
                r = requests.get(img_url, headers=headers, timeout=40, stream=True)
                if r.status_code != 200:
                    return jsonify({'status': 'error', 'message': f'Image fetch failed {r.status_code}'}), 500

                # حدد الامتداد
                ctype = r.headers.get('Content-Type', 'image/jpeg').lower()
                if 'png' in ctype:
                    ext = 'png'
                    mime = 'image/png'
                elif 'webp' in ctype:
                    ext = 'webp'
                    mime = 'image/webp'
                else:
                    ext = 'jpg'
                    mime = 'image/jpeg'

                # من الرابط
                low = img_url.lower()
                if '.png' in low:
                    ext, mime = 'png', 'image/png'
                elif '.webp' in low:
                    ext, mime = 'webp', 'image/webp'

                filepath = os.path.join(temp_dir, f'image.{ext}')
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)

                size = os.path.getsize(filepath)
                if size < 2000:
                    return jsonify({'status': 'error', 'message': 'Image too small'}), 500

                logger.info(f"IMAGE OK {size/1024:.1f}KB | {title[:30]}")
                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'image'
                safe = safe[:40] + f'.{ext}'

                return send_file(
                    filepath,
                    mimetype=mime,
                    as_attachment=True,
                    download_name=safe
                )

            # ========== فيديو ==========
            # نحمّل فعلياً
            info2 = ydl.extract_info(url, download=True)
            title = (info2.get('title') or title)[:55]

            files = [f for f in Path(temp_dir).rglob('*')
                     if f.is_file() and f.stat().st_size > 20000]

            # استبعاد thumbnails الصغيرة إذا انحمّلت بالغلط
            media_files = []
            for f in files:
                name = f.name.lower()
                if any(x in name for x in ['.jpg', '.jpeg', '.png', '.webp', '.vtt', '.json']):
                    # إذا الملف الوحيد صورة كبيرة نعتبرها صورة
                    if f.stat().st_size > 50000 and any(x in name for x in ['.jpg', '.jpeg', '.png', '.webp']):
                        media_files.append(f)
                    continue
                media_files.append(f)

            if not media_files:
                # ربما كانت صورة وفشلنا في is_image_entry
                img_url = pick_best_image(info2) or info2.get('thumbnail')
                if img_url:
                    import requests
                    headers = dict(ydl_opts.get('http_headers') or {})
                    r = requests.get(img_url, headers=headers, timeout=40)
                    if r.status_code == 200 and len(r.content) > 2000:
                        filepath = os.path.join(temp_dir, 'image.jpg')
                        open(filepath, 'wb').write(r.content)
                        safe = (title[:40] or 'image') + '.jpg'
                        return send_file(filepath, mimetype='image/jpeg', as_attachment=True, download_name=safe)

                return jsonify({'status': 'error', 'message': 'No media file created'}), 500

            filepath = str(max(media_files, key=lambda p: p.stat().st_size))
            size = os.path.getsize(filepath)
            duration = info2.get('duration') or 0

            # لو الملف صورة
            low_path = filepath.lower()
            if low_path.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                mime = 'image/jpeg'
                if low_path.endswith('.png'):
                    mime = 'image/png'
                elif low_path.endswith('.webp'):
                    mime = 'image/webp'
                ext = Path(filepath).suffix
                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'image'
                safe = safe[:40] + ext
                logger.info(f"IMAGE-FILE OK {size/1024:.1f}KB")
                return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)

            logger.info(f"VIDEO OK {size/1024/1024:.2f}MB | {duration}s")
            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
            safe = safe[:40] + '.mp4'

            return send_file(
                filepath,
                mimetype='video/mp4',
                as_attachment=True,
                download_name=safe
            )

    except Exception as e:
        err = str(e)
        logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': err[:350]}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
