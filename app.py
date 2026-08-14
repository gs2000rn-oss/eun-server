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

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

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
                headers={'User-Agent': UA})
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
        d = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=20)
        has_v = 'video' in (v.stdout or '')
        has_a = 'audio' in (a.stdout or '')
        try:
            dur = float((d.stdout or '0').strip() or 0)
        except Exception:
            dur = 0
        return has_v, has_a, dur
    except Exception:
        return True, True, 0

def ffmpeg_merge_av(video_path, audio_path, out_path):
    cmd = [
        'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
        '-map', '0:v:0', '-map', '1:a:0', '-shortest',
        out_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10000

def download_file(url, dest, headers=None):
    h = headers or {'User-Agent': UA, 'Referer': 'https://www.tiktok.com/'}
    r = requests.get(url, headers=h, timeout=90, stream=True)
    if r.status_code != 200:
        return False
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(65536):
            if chunk:
                f.write(chunk)
    return os.path.exists(dest) and os.path.getsize(dest) > 1000

def make_slideshow_video(image_paths, audio_path, out_path, duration=None):
    """
    يجمع صورة/صور + صوت = فيديو زي تيك توك Photo Mode
    """
    if not image_paths:
        return False

    # مدة الصوت
    if duration is None or duration <= 0:
        _, _, duration = ffprobe_streams(audio_path)
    if duration is None or duration <= 0:
        duration = 15.0  # افتراضي

    n = len(image_paths)
    # كل صورة تأخذ جزء من المدة (على الأقل 2 ثانية)
    per = max(duration / n, 2.0)

    # لو صورة واحدة: صورة ثابتة طول الصوت
    if n == 1:
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', image_paths[0],
            '-i', audio_path,
            '-c:v', 'libx264', '-tune', 'stillimage',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            '-vf', 'scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1',
            '-shortest',
            '-t', str(duration),
            '-movflags', '+faststart',
            out_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            logger.error(f"slideshow single: {r.stderr[-400:]}")
            return False
        return os.path.exists(out_path) and os.path.getsize(out_path) > 10000

    # عدة صور: concat slideshow
    list_file = os.path.join(os.path.dirname(out_path), 'slides.txt')
    # نحتاج نسخ بامتداد معروف + مدة
    work = os.path.dirname(out_path)
    prepared = []
    for i, p in enumerate(image_paths):
        # توحيد الامتداد عبر تحويل بسيط
        jp = os.path.join(work, f'slide_{i:03d}.jpg')
        subprocess.run(
            ['ffmpeg', '-y', '-i', p, '-q:v', '2', jp],
            capture_output=True, timeout=60
        )
        if os.path.exists(jp) and os.path.getsize(jp) > 500:
            prepared.append(jp)
        else:
            prepared.append(p)

    if not prepared:
        return False

    per = max(duration / len(prepared), 2.0)
    with open(list_file, 'w', encoding='utf-8') as f:
        for p in prepared:
            f.write(f"file '{p}'\n")
            f.write(f"duration {per}\n")
        # آخر صورة تتكرر حسب مواصفات concat
        f.write(f"file '{prepared[-1]}'\n")

    temp_video = os.path.join(work, 'slides_only.mp4')
    cmd1 = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0', '-i', list_file,
        '-vf', 'scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-t', str(duration),
        temp_video
    ]
    r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=300)
    if r1.returncode != 0 or not os.path.exists(temp_video):
        logger.error(f"slideshow multi: {r1.stderr[-400:]}")
        # fallback: أول صورة فقط
        return make_slideshow_video([image_paths[0]], audio_path, out_path, duration)

    cmd2 = [
        'ffmpeg', '-y',
        '-i', temp_video,
        '-i', audio_path,
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '128k',
        '-map', '0:v:0', '-map', '1:a:0',
        '-shortest',
        '-movflags', '+faststart',
        out_path
    ]
    r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=300)
    if r2.returncode != 0:
        logger.error(f"slideshow merge audio: {r2.stderr[-400:]}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 10000

def fetch_tiktok_photo_bundle(url):
    """
    يرجع: {
      'title': str,
      'images': [urls],
      'audio': url or None,
      'duration': float
    }
    """
    api = f'https://www.tikwm.com/api/?url={quote(url, safe="")}'
    r = requests.get(api, timeout=30, headers={'User-Agent': UA})
    if r.status_code != 200:
        return None
    j = r.json()
    if j.get('code') != 0 or not j.get('data'):
        return None
    data = j['data']

    images = list(data.get('images') or [])
    cover = data.get('cover') or data.get('origin_cover') or data.get('ai_dynamic_cover')
    audio = data.get('music') or data.get('play')
    # play في photo mode = صوت
    if audio and 'audio' not in str(audio) and data.get('music'):
        audio = data.get('music')

    duration = float(data.get('duration') or 0)
    # لو duration 0، المدة من ملف الصوت لاحقاً

    # photo mode إذا في images أو cover photomode
    is_photo = bool(images) or (cover and 'photomode' in str(cover)) or (
        duration == 0 and cover and audio
    )

    if not is_photo and not images:
        return None

    if not images and cover:
        images = [cover]

    # فضّل jpeg الأصلي
    prefer = []
    for im in images:
        if 'image.jpeg' in im or 'photomode-image.jpeg' in im:
            prefer.append(im)
    if prefer:
        images = prefer + [x for x in images if x not in prefer]

    title = (data.get('title') or data.get('id') or 'tiktok_photo')[:55]
    return {
        'title': title,
        'images': images,
        'audio': audio,
        'duration': duration,
        'is_photo': True,
    }

def build_tiktok_photo_video(url, temp_dir):
    """صورة/صور + صوت → MP4"""
    bundle = fetch_tiktok_photo_bundle(url)
    if not bundle or not bundle.get('images'):
        return None

    title = bundle['title']
    headers = {'User-Agent': UA, 'Referer': 'https://www.tiktok.com/'}

    # حمّل الصور
    image_paths = []
    for i, img_url in enumerate(bundle['images'][:12]):  # حد أقصى 12 صورة
        ext = '.jpg'
        if '.png' in img_url.lower():
            ext = '.png'
        elif '.webp' in img_url.lower():
            ext = '.webp'
        dest = os.path.join(temp_dir, f'img_{i:03d}{ext}')
        if download_file(img_url, dest, headers):
            image_paths.append(dest)
            logger.info(f"Image {i+1} OK {os.path.getsize(dest)/1024:.1f}KB")

    if not image_paths:
        return None

    # حمّل الصوت
    audio_path = None
    if bundle.get('audio'):
        audio_path = os.path.join(temp_dir, 'music.mp3')
        if not download_file(bundle['audio'], audio_path, headers):
            audio_path = None
        else:
            # تأكد إنه صوت
            has_v, has_a, dur = ffprobe_streams(audio_path)
            if has_v and not has_a:
                audio_path = None
            else:
                if bundle['duration'] <= 0 and dur > 0:
                    bundle['duration'] = dur
                logger.info(f"Audio OK {os.path.getsize(audio_path)/1024:.1f}KB dur={bundle['duration']}")

    out = os.path.join(temp_dir, 'photo_video.mp4')

    if audio_path:
        ok = make_slideshow_video(image_paths, audio_path, out, bundle.get('duration') or 0)
        if ok:
            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'tiktok_photo'
            safe = safe[:40] + '.mp4'
            logger.info(f"PHOTO+AUDIO VIDEO OK {os.path.getsize(out)/1024/1024:.2f}MB")
            return out, 'video/mp4', safe

    # ما في صوت → رجّع أعلى صورة (بدل فشل)
    best = max(image_paths, key=lambda p: os.path.getsize(p))
    ext = Path(best).suffix or '.jpg'
    mime = 'image/jpeg'
    if ext == '.png':
        mime = 'image/png'
    elif ext == '.webp':
        mime = 'image/webp'
    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'tiktok_photo'
    safe = safe[:40] + ext
    return best, mime, safe

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '21-photo-plus-audio',
        'features': 'TikTok photo mode → MP4 (images + music)'
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

    # ===== تيك توك Photo Mode: صورة + صوت = فيديو =====
    if is_tt and mode != 'audio':
        # جرّب دائماً (الرابط القصير ما يبيّن /photo/ أحياناً)
        try:
            bundle = fetch_tiktok_photo_bundle(url)
            if bundle and bundle.get('is_photo') and bundle.get('images'):
                result = build_tiktok_photo_video(url, temp_dir)
                if result:
                    path, mime, safe = result
                    return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
        except Exception as e:
            logger.warning(f"photo bundle: {e}")

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
            'User-Agent': UA,
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
                     and not f.name.endswith(('.json', '.vtt', '.ytdl', '.txt'))]

            # لو yt-dlp رجّع صوت فقط → photo mode
            if is_tt and mode != 'audio':
                if not files:
                    result = build_tiktok_photo_video(url, temp_dir)
                    if result:
                        path, mime, safe = result
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                else:
                    biggest = max(files, key=lambda p: p.stat().st_size)
                    low = biggest.name.lower()
                    has_v, has_a, _ = ffprobe_streams(str(biggest))
                    if low.endswith(('.mp3', '.m4a', '.aac')) or (has_a and not has_v):
                        result = build_tiktok_photo_video(url, temp_dir)
                        if result:
                            path, mime, safe = result
                            return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)

            if not files:
                return jsonify({'status': 'error', 'message': 'No media file'}), 500

            filepath = str(max(files, key=lambda p: p.stat().st_size))
            size = os.path.getsize(filepath)
            low = filepath.lower()

            if low.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                mime = 'image/jpeg'
                if low.endswith('.png'):
                    mime = 'image/png'
                elif low.endswith('.webp'):
                    mime = 'image/webp'
                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'image'
                safe = safe[:40] + Path(filepath).suffix
                return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)

            # فيديو بدون صوت
            if is_tt and mode != 'audio':
                has_v, has_a, _ = ffprobe_streams(filepath)
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
                            if ffmpeg_merge_av(filepath, str(max(auds, key=lambda p: p.stat().st_size)), merged):
                                filepath = merged
                                size = os.path.getsize(filepath)
                    finally:
                        shutil.rmtree(audio_dir, ignore_errors=True)

            if mode == 'audio':
                mime = 'audio/mpeg' if low.endswith('.mp3') else 'audio/mp4'
                ext = '.mp3' if low.endswith('.mp3') else Path(filepath).suffix
                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'audio'
                safe = safe[:40] + ext
                return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)

            # لا ترجع mp3 كـ "فيديو"
            if low.endswith(('.mp3', '.m4a', '.aac')) and mode != 'audio':
                if is_tt:
                    result = build_tiktok_photo_video(url, temp_dir)
                    if result:
                        path, mime, safe = result
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                return jsonify({'status': 'error', 'message': 'Audio only'}), 500

            if size < 15000:
                return jsonify({'status': 'error', 'message': 'File too small'}), 500

            logger.info(f"OK VIDEO: {size/1024/1024:.2f}MB | {title[:30]}")
            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
            safe = safe[:40] + '.mp4'
            return send_file(filepath, mimetype='video/mp4', as_attachment=True, download_name=safe)

    except Exception as e:
        err = str(e)
        logger.error(traceback.format_exc())

        if is_tt and mode != 'audio':
            try:
                result = build_tiktok_photo_video(url, temp_dir)
                if result:
                    path, mime, safe = result
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
