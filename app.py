from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import shutil
import logging
import tempfile
import traceback
import subprocess
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

def ffprobe_streams(path):
    """يرجع (has_video, has_audio, duration)"""
    try:
        v = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=20
        )
        a = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=20
        )
        d = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=20
        )
        has_v = 'video' in (v.stdout or '')
        has_a = 'audio' in (a.stdout or '')
        try:
            dur = float((d.stdout or '0').strip() or 0)
        except:
            dur = 0
        return has_v, has_a, dur
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
        return True, True, 0

def ffmpeg_merge(video_path, audio_path, out_path):
    """دمج فيديو + صوت يدوياً"""
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', audio_path,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-shortest',
        '-movflags', '+faststart',
        out_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        logger.error(f"ffmpeg merge: {r.stderr[-500:]}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 10000

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
        if any(x in low for x in ['original', 'full', '1080', 'large', '4k']):
            score += 50_000_000
        candidates.append((score, u))
    for f in (info.get('formats') or []):
        u = f.get('url')
        if not u:
            continue
        ext = str(f.get('ext') or '').lower()
        if ext in ('jpg', 'jpeg', 'png', 'webp') or any(x in u.lower() for x in ['.jpg', '.jpeg', '.png', '.webp']):
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

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'version': '19-tiktok-audio-fix',
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
    logger.info(f"DOWNLOAD → {url}")

    is_tw = any(x in url for x in ['twitter.com', 'x.com', 't.co'])
    is_pin = 'pinterest' in url or 'pin.it' in url
    is_ig = 'instagram.com' in url
    is_fb = 'facebook.com' in url or 'fb.watch' in url or 'fb.me' in url
    is_tt = any(x in url for x in ['tiktok.com', 'douyin.com', 'vt.tiktok.com', 'vm.tiktok.com'])

    temp_dir = tempfile.mkdtemp(prefix='dl_')
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
        # تيك توك: أولوية لملف فيه صوت، ثم دمج
        ydl_opts['format'] = (
            'best[ext=mp4][acodec!=none]/'
            'bestvideo[ext=mp4]+bestaudio/'
            'bestvideo+bestaudio/'
            'best'
        )
        ydl_opts['merge_output_format'] = 'mp4'
        # مهم للفيديوهات الطويلة
        ydl_opts['socket_timeout'] = 90
        ydl_opts['retries'] = 20
        ydl_opts['fragment_retries'] = 20

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

            files = [f for f in Path(temp_dir).rglob('*')
                     if f.is_file()
                     and f.stat().st_size > 5000
                     and not f.name.endswith(('.json', '.vtt', '.srt', '.ytdl'))]

            if not files:
                img = pick_best_image(info)
                if img:
                    path, mime, safe = download_image(img, temp_dir, headers, title)
                    if path:
                        return send_file(path, mimetype=mime, as_attachment=True, download_name=safe)
                return jsonify({'status': 'error', 'message': 'No media file'}), 500

            # لو في أكثر من ملف (فيديو + صوت منفصل)
            video_files = []
            audio_files = []
            other_files = []
            for f in files:
                low = f.name.lower()
                if low.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    other_files.append(f)
                    continue
                if low.endswith(('.m4a', '.mp3', '.aac', '.opus', '.wav')):
                    audio_files.append(f)
                    continue
                # mp4/webm — نفحص
                has_v, has_a, _ = ffprobe_streams(str(f))
                if has_v and has_a:
                    other_files.append(f)  # كامل
                elif has_v and not has_a:
                    video_files.append(f)
                elif has_a and not has_v:
                    audio_files.append(f)
                else:
                    other_files.append(f)

            # ملف كامل جاهز (فيديو+صوت)
            complete = [f for f in other_files if f.suffix.lower() in ('.mp4', '.webm', '.mkv', '.mov')]
            if complete:
                filepath = str(max(complete, key=lambda p: p.stat().st_size))
                has_v, has_a, probe_dur = ffprobe_streams(filepath)
                size = os.path.getsize(filepath)
                logger.info(f"COMPLETE file: {size/1024/1024:.2f}MB v={has_v} a={has_a} dur={probe_dur}")

                if mode != 'audio' and has_v and has_a:
                    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
                    safe = safe[:40] + '.mp4'
                    return send_file(filepath, mimetype='video/mp4', as_attachment=True, download_name=safe)

            # دمج يدوي إذا فيديو بدون صوت + صوت موجود
            if mode != 'audio' and video_files and audio_files:
                vpath = str(max(video_files, key=lambda p: p.stat().st_size))
                apath = str(max(audio_files, key=lambda p: p.stat().st_size))
                merged = os.path.join(temp_dir, 'merged.mp4')
                logger.info(f"Manual merge: {vpath} + {apath}")
                if ffmpeg_merge(vpath, apath, merged):
                    has_v, has_a, probe_dur = ffprobe_streams(merged)
                    size = os.path.getsize(merged)
                    logger.info(f"MERGED OK: {size/1024/1024:.2f}MB v={has_v} a={has_a} dur={probe_dur}")
                    safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
                    safe = safe[:40] + '.mp4'
                    return send_file(merged, mimetype='video/mp4', as_attachment=True, download_name=safe)

            # تيك توك: فيديو بدون صوت → حمّل الصوت لوحده وادمج
            if mode != 'audio' and is_tt:
                best = str(max(files, key=lambda p: p.stat().st_size))
                has_v, has_a, probe_dur = ffprobe_streams(best)

                if has_v and not has_a:
                    logger.warning("TikTok video has NO audio — downloading audio separately")
                    audio_dir = tempfile.mkdtemp(prefix='aud_')
                    try:
                        audio_opts = {
                            'outtmpl': os.path.join(audio_dir, 'audio.%(ext)s'),
                            'format': 'bestaudio/best',
                            'quiet': True,
                            'no_warnings': True,
                            'retries': 15,
                            'socket_timeout': 90,
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

                        audio_files2 = [f for f in Path(audio_dir).rglob('*')
                                        if f.is_file() and f.stat().st_size > 1000]
                        if audio_files2:
                            apath = str(max(audio_files2, key=lambda p: p.stat().st_size))
                            merged = os.path.join(temp_dir, 'merged_final.mp4')
                            if ffmpeg_merge(best, apath, merged):
                                size = os.path.getsize(merged)
                                logger.info(f"TIKTOK FIXED: {size/1024/1024:.2f}MB with audio")
                                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
                                safe = safe[:40] + '.mp4'
                                return send_file(merged, mimetype='video/mp4', as_attachment=True, download_name=safe)
                    finally:
                        shutil.rmtree(audio_dir, ignore_errors=True)

            # مسار عادي
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

            if mode == 'audio' or low.endswith(('.mp3', '.m4a', '.aac')):
                mime = 'audio/mpeg' if low.endswith('.mp3') else 'audio/mp4'
                ext = '.mp3' if low.endswith('.mp3') else Path(filepath).suffix
                safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'audio'
                safe = safe[:40] + ext
                return send_file(filepath, mimetype=mime, as_attachment=True, download_name=safe)

            if size < 20000:
                return jsonify({'status': 'error', 'message': 'File too small'}), 500

            has_v, has_a, probe_dur = ffprobe_streams(filepath)
            logger.info(f"OK: {size/1024/1024:.2f}MB | v={has_v} a={has_a} | {probe_dur or duration}s | {title[:30]}")

            # تحذير: فيديو بدون صوت
            if has_v and not has_a and mode != 'audio':
                logger.error("Returning video WITHOUT audio (could not fix)")

            safe = "".join(c if c.isalnum() or c in ' ._-' else '_' for c in title).strip() or 'video'
            safe = safe[:40] + '.mp4'
            return send_file(filepath, mimetype='video/mp4', as_attachment=True, download_name=safe)

    except Exception as e:
        err = str(e)
        logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': err[:350]}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
