from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp, os, tempfile, uuid, threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
CORS(app)

JOBS = {}
DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "vidgrab")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

@app.route("/")
def index():
    return send_file(os.path.join(STATIC_DIR, "index.html"))

@app.route("/icon.jpg")
def icon():
    return send_file(os.path.join(STATIC_DIR, "icon.jpg"))

@app.route("/info", methods=["POST"])
def info():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    formats = []
    for f in meta.get("formats", []):
        if f.get("vcodec") == "none" and f.get("acodec") == "none":
            continue
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution") or ("audio" if f.get("vcodec") == "none" else "video"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "note": f.get("format_note") or "",
        })
    return jsonify({
        "title": meta.get("title"),
        "thumbnail": meta.get("thumbnail"),
        "duration": meta.get("duration"),
        "uploader": meta.get("uploader"),
        "formats": formats,
    })

def run_download(job_id, url, format_id):
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    def hook(d):
        if d["status"] == "downloading":
            JOBS[job_id]["progress"] = d.get("_percent_str", "0%").strip()
            JOBS[job_id]["downloaded"] = d.get("_downloaded_bytes_str", "0 B").strip()
            JOBS[job_id]["total"] = d.get("_total_bytes_str") or d.get("_total_bytes_estimate_str") or "?"
        elif d["status"] == "finished":
            JOBS[job_id]["progress"] = "100%"
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["file"] = d["filename"]
    ydl_opts = {"outtmpl": outtmpl, "noplaylist": True, "progress_hooks": [hook]}
    if format_id:
        ydl_opts["format"] = format_id
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    format_id = data.get("format_id")
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "progress": "0%", "downloaded": "0 B", "total": "?"}
    threading.Thread(target=run_download, args=(job_id, url, format_id), daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/progress/<job_id>")
def progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(job)

@app.route("/file/<job_id>")
def file(job_id):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "Not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=os.path.basename(job["file"]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
