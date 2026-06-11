"""
Flask REST API — bridges the download engine to the web UI.
"""

import os
import uuid
import json
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS

# make engine importable from this file's location
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.downloader import DownloadEngine, Status
from engine.torrent    import TorrentSession, HAS_LIBTORRENT

DOWNLOAD_DIR = os.environ.get("FDM_DOWNLOAD_DIR",
               os.path.join(os.path.dirname(__file__), "..", "downloads"))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

engine  = DownloadEngine(default_dest=DOWNLOAD_DIR)
torrent = TorrentSession(save_path=DOWNLOAD_DIR)

app = Flask(__name__,
            static_folder=os.path.join(os.path.dirname(__file__), "..", "ui", "static"),
            template_folder=os.path.join(os.path.dirname(__file__), "..", "ui", "templates"))
CORS(app)


# ──────────────────────────────────────────────
# Serve the UI
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


# ──────────────────────────────────────────────
# HTTP downloads
# ──────────────────────────────────────────────

@app.route("/api/downloads", methods=["GET"])
def list_downloads():
    tasks   = engine.list_tasks()
    torrents = torrent.list_torrents()
    return jsonify({"downloads": tasks, "torrents": torrents})


@app.route("/api/downloads", methods=["POST"])
def add_download():
    data     = request.json or {}
    url      = (data.get("url") or "").strip()
    filename = (data.get("filename") or "").strip()
    category = data.get("category", "General")
    threads  = int(data.get("threads", 8))

    if not url:
        return jsonify({"error": "url is required"}), 400

    # Detect magnet link or .torrent URL
    if url.startswith("magnet:"):
        task_id = str(uuid.uuid4())
        meta    = torrent.add_magnet(task_id, url)
        if "error" in meta:
            return jsonify(meta), 400
        return jsonify({"id": task_id, "type": "torrent", **meta}), 201

    task_id = engine.add(url, filename=filename, threads=threads, category=category)
    task    = engine.get(task_id)
    return jsonify(task.to_dict()), 201


@app.route("/api/downloads/<task_id>", methods=["GET"])
def get_download(task_id):
    task = engine.get(task_id)
    if task:
        return jsonify(task.to_dict())
    # check torrents
    meta = torrent.get_status(task_id)
    if meta:
        return jsonify(meta)
    return jsonify({"error": "not found"}), 404


@app.route("/api/downloads/<task_id>/pause", methods=["POST"])
def pause_download(task_id):
    task = engine.get(task_id)
    if task:
        engine.pause(task_id)
        return jsonify({"status": "paused"})
    torrent.pause(task_id)
    return jsonify({"status": "paused"})


@app.route("/api/downloads/<task_id>/resume", methods=["POST"])
def resume_download(task_id):
    task = engine.get(task_id)
    if task:
        engine.resume(task_id)
        return jsonify({"status": "resumed"})
    torrent.resume(task_id)
    return jsonify({"status": "resumed"})


@app.route("/api/downloads/<task_id>/cancel", methods=["POST"])
def cancel_download(task_id):
    engine.cancel(task_id)
    torrent.remove(task_id)
    return jsonify({"status": "cancelled"})


@app.route("/api/downloads/<task_id>", methods=["DELETE"])
def remove_download(task_id):
    engine.remove(task_id)
    torrent.remove(task_id)
    return jsonify({"status": "removed"})


# ──────────────────────────────────────────────
# Torrent file upload
# ──────────────────────────────────────────────

@app.route("/api/torrents/upload", methods=["POST"])
def upload_torrent():
    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400
    f       = request.files["file"]
    tmp     = os.path.join("/tmp", f.filename)
    f.save(tmp)
    task_id = str(uuid.uuid4())
    meta    = torrent.add_torrent_file(task_id, tmp)
    os.remove(tmp)
    if "error" in meta:
        return jsonify(meta), 400
    return jsonify({"id": task_id, "type": "torrent", **meta}), 201


# ──────────────────────────────────────────────
# Server-Sent Events — live progress stream
# ──────────────────────────────────────────────

@app.route("/api/events")
def sse():
    def stream():
        import time
        while True:
            tasks    = engine.list_tasks()
            torrents = torrent.list_torrents()
            payload  = json.dumps({"downloads": tasks, "torrents": torrents})
            yield f"data: {payload}\n\n"
            time.sleep(1)
    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ──────────────────────────────────────────────
# System info
# ──────────────────────────────────────────────

@app.route("/api/info")
def info():
    return jsonify({
        "libtorrent_available": HAS_LIBTORRENT,
        "download_dir":         os.path.abspath(DOWNLOAD_DIR),
        "max_concurrent":       engine.MAX_CONCURRENT,
        "active":               len(engine._active),
        "queued":               len(engine._queue),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"FDM Server running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
