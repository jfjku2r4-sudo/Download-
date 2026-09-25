"""
تطبيق ويب لتنزيل الفيديوهات (YouTube / TikTok / Facebook)
باستخدام Flask + yt-dlp
يعمل داخل Termux
"""

import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify,
    send_file, session, redirect, url_for, flash, g
)
import yt_dlp

# ----------------------------------------------------------------------
# الإعدادات العامة
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
DB_PATH = os.path.join(BASE_DIR, "app.db")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "غيّر-هذا-المفتاح-قبل_النشر")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")  # غيّرها فورًا


# ----------------------------------------------------------------------
# قاعدة البيانات
# ----------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            platform TEXT,
            video_url TEXT,
            quality TEXT,
            title TEXT,
            status TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()


# ----------------------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------------------
def detect_platform(url: str) -> str:
    url = url.lower()
    if "tiktok.com" in url:
        return "TikTok"
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    if "facebook.com" in url or "fb.watch" in url:
        return "Facebook"
    return "غير معروف"


def get_or_create_user(display_name: str) -> int:
    db = get_db()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ua = request.headers.get("User-Agent", "")
    cur = db.execute(
        "INSERT INTO users (display_name, ip_address, user_agent, created_at) VALUES (?, ?, ?, ?)",
        (display_name or "زائر", ip, ua, datetime.utcnow().isoformat()),
    )
    db.commit()
    return cur.lastrowid


def log_download(user_id, platform, url, quality, title, status):
    db = get_db()
    db.execute(
        """INSERT INTO downloads (user_id, platform, video_url, quality, title, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, platform, url, quality, title, status, datetime.utcnow().isoformat()),
    )
    db.commit()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


# ----------------------------------------------------------------------
# الصفحات العامة (المستخدم)
# ----------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/formats", methods=["POST"])
def api_formats():
    """يجلب قائمة الجودات المتاحة لفيديو معيّن"""
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "الرجاء إدخال رابط صحيح"}), 400

    platform = detect_platform(url)
    if platform == "غير معروف":
        return jsonify({"ok": False, "error": "الرابط غير مدعوم. المدعوم: يوتيوب / تيك توك / فيسبوك"}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"ok": False, "error": f"تعذر جلب معلومات الفيديو: {e}"}), 400

    formats = []
    seen = set()
    for f in info.get("formats", []):
        height = f.get("height")
        ext = f.get("ext")
        vcodec = f.get("vcodec")
        if vcodec == "none":
            continue  # صوت فقط، نتجاهله من قائمة الجودات المرئية
        if not height:
            continue
        label = f"{height}p"
        if label in seen:
            continue
        seen.add(label)
        formats.append({
            "format_id": f.get("format_id"),
            "label": label,
            "ext": ext,
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })

    formats.sort(key=lambda x: int(x["label"].replace("p", "")), reverse=True)

    # خيار صوت فقط (MP3)
    formats.append({
        "format_id": "audio_only",
        "label": "🎵 صوت فقط (MP3)",
        "ext": "mp3",
        "filesize": None,
    })

    return jsonify({
        "ok": True,
        "platform": platform,
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "formats": formats,
    })


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    format_id = data.get("format_id")
    display_name = (data.get("display_name") or "زائر").strip()

    if not url or not format_id:
        return jsonify({"ok": False, "error": "بيانات ناقصة"}), 400

    platform = detect_platform(url)
    user_id = get_or_create_user(display_name)

    file_id = str(uuid.uuid4())
    out_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    if format_id == "audio_only":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    else:
        ydl_opts = {
            "format": f"{format_id}+bestaudio/best",
            "outtmpl": out_template,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
    except Exception as e:
        log_download(user_id, platform, url, format_id, "-", "فشل")
        return jsonify({"ok": False, "error": f"فشل التنزيل: {e}"}), 500

    # إيجاد الملف الناتج فعليًا (الامتداد يتحدد بعد المعالجة)
    produced_file = None
    for fname in os.listdir(DOWNLOAD_DIR):
        if fname.startswith(file_id):
            produced_file = fname
            break

    if not produced_file:
        log_download(user_id, platform, url, format_id, title, "فشل")
        return jsonify({"ok": False, "error": "تعذر إيجاد الملف الناتج"}), 500

    log_download(user_id, platform, url, format_id, title, "نجاح")

    return jsonify({
        "ok": True,
        "download_url": url_for("get_file", filename=produced_file),
        "title": title,
    })


@app.route("/files/<path:filename>")
def get_file(filename):
    return send_file(os.path.join(DOWNLOAD_DIR, filename), as_attachment=True)


# ----------------------------------------------------------------------
# صفحات الأدمن
# ----------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("بيانات الدخول غير صحيحة")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY id DESC LIMIT 100").fetchall()
    downloads = db.execute("""
        SELECT downloads.*, users.display_name
        FROM downloads
        JOIN users ON downloads.user_id = users.id
        ORDER BY downloads.id DESC LIMIT 200
    """).fetchall()

    total_users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    total_downloads = db.execute("SELECT COUNT(*) c FROM downloads").fetchone()["c"]
    success_downloads = db.execute(
        "SELECT COUNT(*) c FROM downloads WHERE status = 'نجاح'"
    ).fetchone()["c"]

    by_platform = db.execute("""
        SELECT platform, COUNT(*) c FROM downloads GROUP BY platform
    """).fetchall()

    return render_template(
        "admin_dashboard.html",
        users=users,
        downloads=downloads,
        total_users=total_users,
        total_downloads=total_downloads,
        success_downloads=success_downloads,
        by_platform=by_platform,
    )


# ----------------------------------------------------------------------
# نقطة الدخول
# ----------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
