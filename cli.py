#!/usr/bin/env python3
"""
FDM CLI — command-line interface for the download engine.

Usage:
    python cli.py add <url> [--filename NAME] [--threads N] [--category CAT]
    python cli.py list
    python cli.py pause   <id>
    python cli.py resume  <id>
    python cli.py cancel  <id>
    python cli.py remove  <id>
    python cli.py watch   <id>        # live progress bar
    python cli.py serve               # start web server
"""

import argparse
import sys
import os
import time
import json
import threading

sys.path.insert(0, os.path.dirname(__file__))
from engine.downloader import DownloadEngine, Status

DOWNLOAD_DIR = os.environ.get("FDM_DOWNLOAD_DIR",
               os.path.join(os.path.dirname(__file__), "downloads"))
engine = DownloadEngine(default_dest=DOWNLOAD_DIR)


# ── helpers ────────────────────────────────────────────────────────────

def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

def fmt_eta(s: int) -> str:
    if s <= 0:
        return "—"
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    if h:   return f"{h}h {m}m"
    if m:   return f"{m}m {s}s"
    return  f"{s}s"

def progress_bar(pct: float, width: int = 30) -> str:
    filled = int(width * pct / 100)
    bar    = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:6.2f}%"


# ── commands ───────────────────────────────────────────────────────────

def cmd_add(args):
    task_id = engine.add(args.url,
                         filename=args.filename or "",
                         threads=args.threads,
                         category=args.category)
    print(f"✓ Queued  id={task_id}")
    print(f"  URL:    {args.url}")
    print(f"  Dest:   {DOWNLOAD_DIR}/{args.filename or '<auto>'}")
    return task_id


def cmd_list(args):
    tasks = engine.list_tasks()
    if not tasks:
        print("No downloads.")
        return
    print(f"\n{'ID':36}  {'File':24}  {'Status':12}  {'Progress':10}  {'Speed':10}  {'ETA'}")
    print("─" * 110)
    for t in tasks:
        prog  = f"{t['progress']:5.1f}%"
        speed = fmt_bytes(int(t['speed'])) + "/s" if t['speed'] else "—"
        eta   = fmt_eta(t['eta'])
        fname = t['filename'][:24]
        print(f"{t['id']}  {fname:<24}  {t['status']:<12}  {prog:<10}  {speed:<10}  {eta}")
    print()


def cmd_pause(args):
    engine.pause(args.id)
    print(f"⏸  Paused {args.id}")


def cmd_resume(args):
    engine.resume(args.id)
    print(f"▶  Resumed {args.id}")


def cmd_cancel(args):
    engine.cancel(args.id)
    print(f"✗  Cancelled {args.id}")


def cmd_remove(args):
    engine.remove(args.id)
    print(f"🗑  Removed {args.id}")


def cmd_watch(args):
    """Live progress display for a single task."""
    print(f"Watching {args.id}  (Ctrl+C to stop)\n")
    try:
        while True:
            task = engine.get(args.id)
            if not task:
                print("Task not found.")
                break
            d = task.to_dict()
            bar   = progress_bar(d['progress'])
            speed = fmt_bytes(int(d['speed'])) + "/s" if d['speed'] else "—"
            eta   = fmt_eta(d['eta'])
            total = fmt_bytes(d['total_size']) if d['total_size'] else "?"
            done  = fmt_bytes(d['downloaded'])
            line  = f"\r{bar}  {done}/{total}  {speed}  ETA {eta}  [{d['status']}]"
            sys.stdout.write(line.ljust(100))
            sys.stdout.flush()
            if d['status'] in ("completed", "failed", "cancelled"):
                print(f"\n\nDone: {d['status']}")
                if d.get('error'):
                    print(f"Error: {d['error']}")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped watching.")


def cmd_serve(args):
    from api.server import app
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting FDM web server at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


# ── main ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        prog="fdm",
        description="Free Download Manager — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Add a new download")
    p_add.add_argument("url")
    p_add.add_argument("--filename", "-f", default="")
    p_add.add_argument("--threads",  "-t", type=int, default=8)
    p_add.add_argument("--category", "-c", default="General")

    # list
    sub.add_parser("list", help="List all downloads")

    # pause / resume / cancel / remove
    for cmd in ("pause", "resume", "cancel", "remove"):
        pp = sub.add_parser(cmd)
        pp.add_argument("id")

    # watch
    p_watch = sub.add_parser("watch", help="Live progress for a download")
    p_watch.add_argument("id")

    # serve
    sub.add_parser("serve", help="Start the web UI server")

    args = p.parse_args()
    cmds = {
        "add":    cmd_add,
        "list":   cmd_list,
        "pause":  cmd_pause,
        "resume": cmd_resume,
        "cancel": cmd_cancel,
        "remove": cmd_remove,
        "watch":  cmd_watch,
        "serve":  cmd_serve,
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
