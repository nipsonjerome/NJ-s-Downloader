<<<<<<< HEAD
# FreeDL — Download Manager Engine

A Python download manager modelled after FDM (Free Download Manager) with:

- **Multi-threaded segmented HTTP/HTTPS downloads** — splits files into N parallel byte-range chunks for maximum speed
- **Pause & resume** — all segment progress is preserved; resumes from exact byte offsets
- **Download queue** — max 5 concurrent, auto-starts from queue
- **Torrent support** — magnet links and .torrent files via `libtorrent`
- **Web UI** — dark, responsive interface served by Flask with live SSE updates
- **REST API** — full CRUD for all downloads
- **CLI** — scriptable command-line interface

---

## Quick Start

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. (Optional) Install libtorrent for torrent support
#    macOS:  brew install libtorrent-rasterbar
#    Ubuntu: sudo apt install python3-libtorrent
#    Or:     pip install libtorrent

# 3. Start the web server (serves UI + API)
python api/server.py
# → Open http://localhost:5000

# 4. Or use the CLI
python cli.py add "https://example.com/bigfile.zip" --threads 8
python cli.py list
python cli.py watch <task-id>
```

---

## Project Structure

```
fdm/
├── engine/
│   ├── downloader.py     # Core HTTP engine (segmented, pause/resume, queue)
│   └── torrent.py        # libtorrent wrapper (magnet + .torrent files)
├── api/
│   └── server.py         # Flask REST API + SSE live events
├── ui/
│   └── templates/
│       └── index.html    # Web UI (dark theme, live progress)
├── cli.py                # CLI interface
├── downloads/            # Default save directory
└── requirements.txt
```

---

## REST API

| Method | Endpoint                         | Description            |
|--------|----------------------------------|------------------------|
| GET    | `/api/downloads`                 | List all downloads     |
| POST   | `/api/downloads`                 | Add download (URL/magnet) |
| GET    | `/api/downloads/:id`             | Get task status        |
| POST   | `/api/downloads/:id/pause`       | Pause                  |
| POST   | `/api/downloads/:id/resume`      | Resume                 |
| POST   | `/api/downloads/:id/cancel`      | Cancel                 |
| DELETE | `/api/downloads/:id`             | Remove                 |
| POST   | `/api/torrents/upload`           | Upload .torrent file   |
| GET    | `/api/events`                    | SSE live progress stream |
| GET    | `/api/info`                      | Engine info/status     |

**POST /api/downloads body:**
```json
{
  "url":      "https://...",
  "filename": "optional-name.zip",
  "threads":  8,
  "category": "General"
}
```

---

## CLI Usage

```bash
python cli.py add <url> [--filename NAME] [--threads N] [--category CAT]
python cli.py list
python cli.py pause   <task-id>
python cli.py resume  <task-id>
python cli.py cancel  <task-id>
python cli.py remove  <task-id>
python cli.py watch   <task-id>   # live ASCII progress bar
python cli.py serve               # start web server
```

---

## Architecture

```
                 ┌──────────────────────────────────────┐
                 │           Flask API Server            │
                 │  /api/downloads  /api/events (SSE)    │
                 └──────────┬──────────────┬────────────┘
                            │              │
              ┌─────────────▼──┐    ┌──────▼──────────────┐
              │ DownloadEngine │    │   TorrentSession     │
              │                │    │  (libtorrent wrap)   │
              │  • task queue  │    │  • magnet links      │
              │  • 5 concurrent│    │  • .torrent files    │
              │  • scheduler   │    │  • seeding/peers     │
              └────────┬───────┘    └─────────────────────┘
                       │
          ┌────────────▼─────────────┐
          │       DownloadTask        │
          │  • N segment threads      │
          │  • byte-range HTTP        │
          │  • pause/stop events      │
          │  • speed/ETA tracking     │
          └───────────────────────────┘
```

---

## Environment Variables

| Variable           | Default       | Description               |
|--------------------|---------------|---------------------------|
| `FDM_DOWNLOAD_DIR` | `./downloads` | Where files are saved     |
| `PORT`             | `5000`        | Web server port           |

---

## Extending

- **Browser extension**: Use the REST API. A Chrome extension can intercept downloads and POST to `/api/downloads`.
- **Persistence**: Add SQLite via `sqlite3` in `DownloadEngine._tasks` to survive restarts.
- **Auth**: Add Flask-Login or JWT to the API for multi-user setups.
- **Scheduling**: Add `start_time` field and check it in `_schedule_loop`.
=======
# NJ-s-Downloader
>>>>>>> 206e7305e28dfbf910c7cf208c1cd87d9ef59ebf
