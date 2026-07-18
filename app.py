import os
import sys
import threading
import json
import tempfile
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import yt_dlp

app = Flask(__name__)

# ===== HELPERS =====

def get_download_folder():
    home = os.path.expanduser("~")
    for folder in ["Downloads", "Desktop"]:
        path = os.path.join(home, folder)
        if os.path.exists(path):
            return path
    return home

def get_ffmpeg_dir():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def get_history_file():
    home = os.path.expanduser("~")
    return os.path.join(home, ".plueschi_downloader_history.json")

def load_history():
    try:
        with open(get_history_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_history(entry):
    history = load_history()
    history.insert(0, entry)
    history = history[:50]
    try:
        with open(get_history_file(), "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except:
        pass

# ===== GLOBALS =====

FFMPEG_DIR = get_ffmpeg_dir()
progress_data = {"percent": 0, "status": "idle", "filename": "", "title": ""}
current_download_folder = get_download_folder()

# ===== PROGRESS HOOK =====

def progress_hook(d):
    global progress_data
    if d["status"] == "downloading":
        raw = d.get("_percent_str", "0%").strip().replace("%", "")
        try:
            progress_data["percent"] = float(raw)
        except:
            progress_data["percent"] = 0
        progress_data["status"] = "downloading"
        progress_data["speed"] = d.get("_speed_str", "")
        progress_data["eta"] = d.get("_eta_str", "")
    elif d["status"] == "finished":
        progress_data["percent"] = 100
        progress_data["status"] = "finished"

# ===== ROUTES =====

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Keine URL"}), 400
    try:
        ydl_opts = {"quiet": True, "skip_download": True, "ffmpeg_location": FFMPEG_DIR}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                "title": info.get("title", "Unbekannt"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/download", methods=["POST"])
def download():
    global progress_data, current_download_folder
    data = request.json
    url        = data.get("url", "").strip()
    fmt        = data.get("format", "mp4")
    quality    = data.get("quality", "best")
    folder     = data.get("folder", current_download_folder)
    proxy      = data.get("proxy", "").strip()
    cookies    = data.get("cookies", "").strip()
    filename   = data.get("filename", "").strip()
    pl_start   = data.get("playlist_start", 1)
    pl_end     = data.get("playlist_end", None)

    if not url:
        return jsonify({"error": "Keine URL eingegeben!"}), 400

    current_download_folder = folder
    progress_data = {"percent": 0, "status": "starting", "filename": "", "title": "", "speed": "", "eta": ""}

    def run():
        global progress_data
        cookie_file = None
        try:
            if cookies:
                cookie_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                )
                if not cookies.startswith("# Netscape"):
                    cookie_file.write("# Netscape HTTP Cookie File\n")
                cookie_file.write(cookies)
                cookie_file.close()

            if filename:
                outtmpl = os.path.join(folder, f"{filename}.%(ext)s")
            else:
                outtmpl = os.path.join(folder, "%(title)s.%(ext)s")

            base_opts = {
                "outtmpl": outtmpl,
                "progress_hooks": [progress_hook],
                "quiet": True,
                "ffmpeg_location": FFMPEG_DIR,
                "playliststart": int(pl_start) if pl_start else 1,
                "noplaylist": False,
            }

            if pl_end:
                base_opts["playlistend"] = int(pl_end)
            if proxy:
                base_opts["proxy"] = proxy
            if cookie_file:
                base_opts["cookiefile"] = cookie_file.name

            if fmt == "mp3":
                ydl_opts = {
                    **base_opts,
                    "format": "bestaudio/best",
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                }
            else:
                quality_map = {
                    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
                    "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
                    "480":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
                }
                ydl_opts = {
                    **base_opts,
                    "format": quality_map.get(quality, quality_map["best"]),
                    "merge_output_format": "mp4",
                }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "Unbekannt") if info else "Unbekannt"
                progress_data["title"] = title
                progress_data["status"] = "finished"
                save_history({
                    "title": title,
                    "url": url,
                    "format": fmt.upper(),
                    "quality": quality if fmt == "mp4" else "192kbps",
                    "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                    "folder": folder,
                    "thumbnail": info.get("thumbnail", "") if info else "",
                    "artist": info.get("uploader", "") if info else "",
                    "filesize": info.get("filesize") or info.get("filesize_approx") or 0 if info else 0,
                })

        except Exception as e:
            progress_data["status"] = "error"
            progress_data["error"] = str(e)
        finally:
            if cookie_file and os.path.exists(cookie_file.name):
                try:
                    os.unlink(cookie_file.name)
                except:
                    pass

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/progress")
def progress():
    return jsonify(progress_data)

@app.route("/history")
def history():
    return jsonify(load_history())

@app.route("/history/clear", methods=["POST"])
def clear_history():
    try:
        with open(get_history_file(), "w", encoding="utf-8") as f:
            json.dump([], f)
    except:
        pass
    return jsonify({"ok": True})

@app.route("/open-folder", methods=["POST"])
def open_folder():
    data = request.json
    folder = data.get("folder", current_download_folder)
    if os.path.exists(folder):
        os.startfile(folder)
    return jsonify({"ok": True})

@app.route("/open-music", methods=["POST"])
def open_music():
    data = request.json
    folder = data.get("folder", current_download_folder)
    title  = data.get("title", "")
    if title and folder and os.path.exists(folder):
        safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
        mp3_path = os.path.join(folder, safe_title + ".mp3")
        if os.path.exists(mp3_path):
            os.startfile(mp3_path)
            return jsonify({"ok": True, "opened": mp3_path})
    try:
        if folder and os.path.exists(folder):
            mp3s = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".mp3")]
            if mp3s:
                newest = max(mp3s, key=os.path.getmtime)
                os.startfile(newest)
                return jsonify({"ok": True, "opened": newest})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": False, "reason": "Keine MP3 gefunden"})

@app.route("/shutdown", methods=["POST"])
def shutdown():
    def kill():
        import time
        time.sleep(0.5)
        if window:
            window.destroy()
        os._exit(0)
    threading.Thread(target=kill, daemon=True).start()
    return jsonify({"ok": True})

# ===== PYWEBVIEW START =====

window = None

def start_flask():
    app.run(debug=False, port=5000, use_reloader=False)

if __name__ == "__main__":
    try:
        import webview

        # Flask im Hintergrund starten
        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()

        # Kurz warten bis Flask bereit ist
        import time
        time.sleep(1.0)

        # PyWebView Fenster erstellen
        window = webview.create_window(
            title="Plüsch Downloader",
            url="http://localhost:5000",
            width=1100,
            height=720,
            min_size=(900, 600),
            resizable=True,
            text_select=False,
            confirm_close=False,
        )

        # App starten (blockiert bis Fenster geschlossen wird)
        webview.start(debug=False)

    except ImportError:
        # Fallback: Browser öffnen wenn PyWebView nicht installiert
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
        app.run(debug=False, port=5000)
