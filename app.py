import os
import sys
import threading
import webbrowser
from flask import Flask, render_template, request, jsonify
import yt_dlp

app = Flask(__name__)

# Output folder: Desktop or Downloads
def get_download_folder():
    home = os.path.expanduser("~")
    for folder in ["Downloads", "Desktop"]:
        path = os.path.join(home, folder)
        if os.path.exists(path):
            return path
    return home

DOWNLOAD_FOLDER = get_download_folder()
progress_data = {"percent": 0, "status": "idle", "filename": ""}

def progress_hook(d):
    global progress_data
    if d["status"] == "downloading":
        raw = d.get("_percent_str", "0%").strip().replace("%", "")
        try:
            progress_data["percent"] = float(raw)
        except:
            progress_data["percent"] = 0
        progress_data["status"] = "downloading"
        progress_data["filename"] = d.get("filename", "")
    elif d["status"] == "finished":
        progress_data["percent"] = 100
        progress_data["status"] = "finished"
        progress_data["filename"] = d.get("filename", "")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/download", methods=["POST"])
def download():
    global progress_data
    data = request.json
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp4")

    if not url:
        return jsonify({"error": "Keine URL eingegeben!"}), 400

    progress_data = {"percent": 0, "status": "starting", "filename": ""}

    def run():
        global progress_data
        try:
            if fmt == "mp3":
                ydl_opts = {
                    "format": "bestaudio/best",
                    "outtmpl": os.path.join(DOWNLOAD_FOLDER, "%(title)s.%(ext)s"),
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                    "progress_hooks": [progress_hook],
                    "quiet": True,
                }
            else:
                ydl_opts = {
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "outtmpl": os.path.join(DOWNLOAD_FOLDER, "%(title)s.%(ext)s"),
                    "progress_hooks": [progress_hook],
                    "quiet": True,
                    "merge_output_format": "mp4",
                }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            progress_data["status"] = "error"
            progress_data["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/progress")
def progress():
    return jsonify(progress_data)

def open_browser():
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    threading.Timer(1.2, open_browser).start()
    app.run(debug=False, port=5000)
