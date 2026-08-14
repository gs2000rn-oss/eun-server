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
                logger.info(f"Resolved → {r.url}")
                return r.url
    except Exception as e:
        logger.warning(f"resolve: {e}")
    return url

def pick_best_image(info):
    candidates = []
    for t in (info.get('thumbnails') or []):
        u = t.get('url')
        if not u:
            continue
        w = t.get('width') or 0
        h = t.get('height') or 0
        score = (w * h) if (w and h) else 0
        low = u.lower()
        if any(x in low for x in ['original', 'full', '1080', 'large', '4k', 'heic']):
            score += 50_000_000
        candidates.append((score, u))

    # تيك توك photo mode أحياناً في formats
    for f in (info.get('formats') or []):
        u = f.get('url')
        if not u:
            continue
        ext = str(f.get('ext') or '').lower()
        vcodec = str(f.get('vcodec') or 'none').lower()
        if ext in ('jpg', 'jpeg', 'png', 'webp') or vcodec in ('none', '') and any(x in u.lower() for x in ['.jpg', '.jpeg', '.png', '.webp']):
            w = f.get('width') or 0
            h = f.get('height') or 0
            candidates.append(((w * h) if (w and h) else 1, u))

    if info.get('thumbnail'):
        candidates.append((1000, info['thumbnail']))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def download_image(img_url, temp_dir, headers, title):
    import requests
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
    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in (title or 'image')).strip() or 'image'
    safe = safe[:40] + f'.{ext}'
    return path, mime, safe

def is_audio_only_file(path):
    """فحص سريع إذا الملف صوت فقط"""
    low = path.lower()
    if low.endswith(('.mp3', '.m4a', '.aac', '.wav', '.opus', '.ogg')):
        return True
    # mp4 بدون فيديو نادر — نعتمد على الامتداد + الحجم الغريب لاحقاً
    return False

def probe_has_video(path):
    """يستخدم ffprobe للتأكد فيه فيديو + صوت"""
    try:
        import subprocess
        # فيديو؟
        v = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=15
        )
        has_v = 'video' in (v.stdout or '')
        # صوت؟
        a = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=15
        )
        has_a = 'audio' in (a.stdout or '')
        # المدة
        d = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=15
        )
        try:
            duration = float((d.stdout or '0').strip() or 0)
        except:
            duration = 0
        return has_v, has_a, duration
    except Exception as e:
        logger.warning(f"ffprobe: {e}")
        return True, True, 0  # ما نكسر التحميل إذا فشل الفحص

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '18-tiktok-audio-images',
        'supports': ['Instagram', 'Facebook', 'TikTok', 'Pinterest', 'X', 'Images']
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
    logger.info(f"DOWNLOAD → {url} mode={mode}")

    is_tw = any(x in url for x in ['twitter.com', 'x.com', 't.co'])
    is_pin = 'pinterest' in url or 'pin.it' in url
    is_ig = 'instagram.com' in url
    is_fb = 'facebook.com' in url or 'fb.watch' in url or 'fb.me' in url
    is_tt = 'tiktok.com' in url or 'douyin.com' in url or 'vt.tiktok.com' in url

    temp_dir = tempfile.mkdtemp(prefix='dl_')
    outtmpl = os.path.join(temp_dir, 'out.%(ext)s')

    # ===== نفس أساس كودك =====
    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 12,
        'fragment_retries': 12,
        'socket_timeout': 45,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
        # مهم: دمج فيديو+صوت
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
        # تيك توك: نجبر فيديو+صوت (ما نأخذ best لوحده لأنه أحياناً صوت فقط)
        ydl_opts['format'] = (
            'bestvideo[ext=mp4]+bestaudio/'
            'bestvideo+bestaudio/'
            'best[ext=mp4]/'
            'best'
        )
        ydl_opts['merge_output_format'] = 'mp4'

    # لو المستخدم يطلب صوت فقط
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
        logger.info("Using cookies")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            title = (info.get('title') or info.get('id') or 'media')[:55]
            duration = info.get('duration') or 0
            headers = ydl_opts.get('http_headers') or {}

            # تيك توك photo mode / slideshow
            # أحياناً duration طويلة للصوت فقط + صور
            is_photo_mode = False
            if is_tt:
                # photo posts غالباً: لا فيديو حقيقي أو formats صور
                formats = info.get('formats') or []
                has_real_video = False
                for f in formats:
                    vc = str(f.get('vcodec') or 'none').lower()
                    ext = str(f.get('ext') or '').lower()
                    if vc not in ('none', '') and ext in ('mp4', 'webm', 'mov'):
                        # ارتفاع منطقي لفيديو
                        h = f.get('height') or 0
                        if h >= 100 or f.get('tbr'):
                            has_real_video = True
                            break
                if not has_real_video and pick_best_image(info):
                    is_photo_mode = True

            files = [f for f in Path(temp_dir).rglob('*')
                     if f.is_file() and f.stat().st_size > 3000
                     and not f.name.endswith('.json')
                     and not f.name.endswith('.vtt')]

            # ===== وضع الصورة / سلايد =====
            if is_photo_mode or not files:
                img = pick_best_image(info)
                if img:
                    path, mime, safe = download_image(img, temp_dir, headers, title)
                    if path:
                        logger.info(f"IMAGE OK | {title[:30]}")
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                if not files:
                    return jsonify({'status': 'error', 'message': 'No media file'}), 500

            filepath = str(max(files, key=lambda p: p.stat().st_size))
            size = os.path.getsize(filepath)
            low = filepath.lower()

            # ملف صورة
            if low.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                mime = 'image/jpeg'
                if low.endswith('.png'):
                    mime = 'image/png'
                elif low.endswith('.webp'):
                    mime = 'image/webp'
                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'image'
                safe = safe[:40] + Path(filepath).suffix
                return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)

            # ملف صوت فقط (والطلب فيديو) → حوّله لصورة إذا photo mode، وإلا ارفض
            if is_audio_only_file(filepath) and mode != 'audio':
                img = pick_best_image(info)
                if img:
                    path, mime, safe = download_image(img, temp_dir, headers, title)
                    if path:
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                return jsonify({
                    'status': 'error',
                    'message': 'Got audio only, not video. Try again or this is a photo post.'
                }), 500

            # فحص ffprobe: فيديو + صوت
            has_v, has_a, probe_dur = probe_has_video(filepath)

            # لو صوت فقط (mp4 بدون فيديو أو m4a)
            if mode != 'audio' and not has_v and has_a:
                img = pick_best_image(info)
                if img:
                    path, mime, safe = download_image(img, temp_dir, headers, title)
                    if path:
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                return jsonify({
                    'status': 'error',
                    'message': 'Downloaded audio-only (no video stream)'
                }), 500

            # لو فيديو بدون صوت → نحاول إعادة التحميل بصيغة أدق
            if mode != 'audio' and has_v and not has_a and is_tt:
                logger.warning("TikTok video without audio — retry with stricter format")
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    temp_dir = tempfile.mkdtemp(prefix='dl2_')
                    outtmpl2 = os.path.join(temp_dir, 'out.%(ext)s')
                    opts2 = dict(ydl_opts)
                    opts2['outtmpl'] = outtmpl2
                    # صيغة تجبر الدمج
                    opts2['format'] = 'bv*+ba/b'
                    opts2['merge_output_format'] = 'mp4'
                    with yt_dlp.YoutubeDL(opts2) as ydl2:
                        info2 = ydl2.extract_info(url, download=True)
                        files2 = [f for f in Path(temp_dir).rglob('*')
                                  if f.is_file() and f.stat().st_size > 20000]
                        if files2:
                            filepath = str(max(files2, key=lambda p: p.stat().st_size))
                            size = os.path.getsize(filepath)
                            has_v, has_a, probe_dur = probe_has_video(filepath)
                            title = (info2.get('title') or title)[:55]
                except Exception as e:
                    logger.error(f"Retry failed: {e}")

            if mode == 'audio':
                # إرجاع صوت
                if not low.endswith('.mp3'):
                    # قد يكون m4a
                    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'audio'
                    safe = safe[:40] + ('.mp3' if low.endswith('.mp3') else Path(filepath).suffix)
                    mime = 'audio/mpeg' if low.endswith('.mp3') else 'audio/mp4'
                else:
                    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'audio'
                    safe = safe[:40] + '.mp3'
                    mime = 'audio/mpeg'
                return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)

            # فيديو نهائي
            if size < 20000:
                return jsonify({'status': 'error', 'message': 'File too small'}), 500

            logger.info(f"OK: {size/1024/1024:.2f}MB | v={has_v} a={has_a} | {probe_dur or duration}s | {title[:30]}")

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

        # محاولة صورة
        try:
            opts2 = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'noplaylist': True,
                'http_headers': ydl_opts.get('http_headers') or {},
            }
            if cookie:
                opts2['cookiefile'] = cookie
            with yt_dlp.YoutubeDL(opts2) as ydl2:
                info2 = ydl2.extract_info(url, download=False)
                img = pick_best_image(info2)
                if img:
                    path, mime, safe = download_image(
                        img, temp_dir, opts2.get('http_headers') or {},
                        info2.get('title') or 'image'
                    )
                    if path:
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
        except Exception:
            pass

        return jsonify({'status': 'error', 'message': err[:350]}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
