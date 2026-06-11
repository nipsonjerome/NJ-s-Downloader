"""
Core download engine — segmented multi-threaded HTTP downloader with pause/resume.
"""

import os
import uuid
import time
import threading
import requests
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path


class Status(str, Enum):
    QUEUED      = "queued"
    DOWNLOADING = "downloading"
    PAUSED      = "paused"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


@dataclass
class Segment:
    index:      int
    start:      int
    end:        int          # -1 = open ended
    downloaded: int = 0
    done:       bool = False


@dataclass
class DownloadTask:
    id:            str
    url:           str
    filename:      str
    dest_dir:      str
    status:        Status         = Status.QUEUED
    total_size:    int            = 0          # bytes; 0 = unknown
    downloaded:    int            = 0
    speed:         float          = 0.0        # bytes/s
    eta:           int            = 0          # seconds
    segments:      list           = field(default_factory=list)
    error:         Optional[str]  = None
    created_at:    float          = field(default_factory=time.time)
    started_at:    Optional[float]= None
    completed_at:  Optional[float]= None
    threads:       int            = 8
    category:      str            = "General"
    torrent:       bool           = False

    # runtime-only (not serialised)
    _pause_event:  threading.Event = field(default_factory=threading.Event, repr=False)
    _stop_event:   threading.Event = field(default_factory=threading.Event, repr=False)
    _lock:         threading.Lock  = field(default_factory=threading.Lock, repr=False)

    def to_dict(self):
        d = {
            "id":           self.id,
            "url":          self.url,
            "filename":     self.filename,
            "dest_dir":     self.dest_dir,
            "status":       self.status.value,
            "total_size":   self.total_size,
            "downloaded":   self.downloaded,
            "speed":        round(self.speed, 1),
            "eta":          self.eta,
            "progress":     self.progress,
            "error":        self.error,
            "created_at":   self.created_at,
            "started_at":   self.started_at,
            "completed_at": self.completed_at,
            "threads":      self.threads,
            "category":     self.category,
            "torrent":      self.torrent,
        }
        return d

    @property
    def progress(self) -> float:
        if self.total_size:
            return round(min(self.downloaded / self.total_size * 100, 100), 2)
        return 0.0

    @property
    def dest_path(self) -> str:
        return os.path.join(self.dest_dir, self.filename)


CHUNK = 64 * 1024   # 64 KB read chunks


def _download_segment(task: DownloadTask, seg: Segment):
    """Download one byte-range segment, writing directly into the pre-allocated file."""
    headers = {}
    if seg.end >= 0:
        headers["Range"] = f"bytes={seg.start + seg.downloaded}-{seg.end}"
    elif seg.downloaded:
        headers["Range"] = f"bytes={seg.start + seg.downloaded}-"

    try:
        resp = requests.get(task.url, headers=headers, stream=True, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        with task._lock:
            task.error = str(exc)
            task.status = Status.FAILED
        return

    try:
        with open(task.dest_path, "r+b") as fh:
            fh.seek(seg.start + seg.downloaded)
            for chunk in resp.iter_content(CHUNK):
                if task._stop_event.is_set():
                    return
                # honour pause
                while task._pause_event.is_set():
                    time.sleep(0.2)
                    if task._stop_event.is_set():
                        return
                fh.write(chunk)
                n = len(chunk)
                seg.downloaded += n
                with task._lock:
                    task.downloaded += n
    except Exception as exc:
        with task._lock:
            task.error = str(exc)
            task.status = Status.FAILED
        return

    seg.done = True


def _run_download(task: DownloadTask):
    """Orchestrate segmented download for a single task."""
    task.started_at = time.time()
    task.status = Status.DOWNLOADING

    # HEAD request to probe server capabilities
    try:
        head = requests.head(task.url, allow_redirects=True, timeout=15)
        head.raise_for_status()
        total = int(head.headers.get("Content-Length", 0))
        accepts_ranges = head.headers.get("Accept-Ranges", "none").lower() == "bytes"
    except Exception as exc:
        task.error = str(exc)
        task.status = Status.FAILED
        return

    task.total_size = total

    # Decide segment count: use multiple only when server supports ranges & size known
    n_segs = task.threads if (accepts_ranges and total > 1_048_576) else 1

    # Build segment list (resume-aware — keep existing if already partial)
    if not task.segments:
        if n_segs > 1:
            seg_size = total // n_segs
            task.segments = [
                Segment(i, i * seg_size,
                        (i + 1) * seg_size - 1 if i < n_segs - 1 else total - 1)
                for i in range(n_segs)
            ]
        else:
            task.segments = [Segment(0, 0, total - 1 if total else -1)]

    # Pre-allocate file (sparse) if not resuming
    if not os.path.exists(task.dest_path) and total:
        with open(task.dest_path, "wb") as fh:
            fh.seek(total - 1)
            fh.write(b"\x00")
    elif not os.path.exists(task.dest_path):
        open(task.dest_path, "wb").close()

    # Count already-downloaded bytes from segment state
    task.downloaded = sum(s.downloaded for s in task.segments)

    # Speed tracking
    _last_bytes = [task.downloaded]
    _last_time  = [time.time()]

    def _speed_tracker():
        while task.status == Status.DOWNLOADING:
            time.sleep(1)
            now = time.time()
            cur = task.downloaded
            elapsed = now - _last_time[0]
            if elapsed > 0:
                task.speed = (cur - _last_bytes[0]) / elapsed
                remaining = task.total_size - cur if task.total_size else 0
                task.eta = int(remaining / task.speed) if task.speed > 0 else 0
            _last_bytes[0] = cur
            _last_time[0]  = now

    speed_thread = threading.Thread(target=_speed_tracker, daemon=True)
    speed_thread.start()

    # Launch segment threads
    pending = [s for s in task.segments if not s.done]
    threads = []
    for seg in pending:
        if task._stop_event.is_set():
            break
        t = threading.Thread(target=_download_segment, args=(task, seg), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    if task._stop_event.is_set() or task.status == Status.FAILED:
        return

    if all(s.done for s in task.segments):
        task.status = Status.COMPLETED
        task.completed_at = time.time()
        task.speed = 0.0
        task.eta   = 0
    else:
        task.status = Status.FAILED
        task.error  = task.error or "One or more segments failed"


class DownloadEngine:
    """
    Thread-safe download manager.

    Public API
    ----------
    add(url, filename, dest_dir, threads, category) -> task_id
    pause(task_id)
    resume(task_id)
    cancel(task_id)
    remove(task_id)
    get(task_id) -> DownloadTask | None
    list_tasks() -> list[dict]
    """

    MAX_CONCURRENT = 5

    def __init__(self, default_dest: str = "./downloads"):
        self._tasks:   dict[str, DownloadTask] = {}
        self._lock     = threading.Lock()
        self._queue:   list[str] = []          # ordered list of queued ids
        self._active:  set[str]  = set()
        self._default_dest = default_dest
        os.makedirs(default_dest, exist_ok=True)

        # scheduler loop
        self._scheduler = threading.Thread(target=self._schedule_loop, daemon=True)
        self._scheduler.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, url: str, filename: str = "",
            dest_dir: str = "", threads: int = 8,
            category: str = "General") -> str:
        if not filename:
            filename = url.split("?")[0].rstrip("/").split("/")[-1] or "download"
        if not dest_dir:
            dest_dir = self._default_dest

        task = DownloadTask(
            id       = str(uuid.uuid4()),
            url      = url,
            filename = filename,
            dest_dir = dest_dir,
            threads  = threads,
            category = category,
        )
        task._pause_event.clear()
        task._stop_event.clear()

        with self._lock:
            self._tasks[task.id] = task
            self._queue.append(task.id)
        return task.id

    def pause(self, task_id: str):
        task = self._get(task_id)
        if task and task.status == Status.DOWNLOADING:
            task._pause_event.set()
            task.status = Status.PAUSED

    def resume(self, task_id: str):
        task = self._get(task_id)
        if not task:
            return
        if task.status == Status.PAUSED:
            task._pause_event.clear()
            task.status = Status.DOWNLOADING
            # resume in a fresh thread
            t = threading.Thread(target=self._run_task, args=(task,), daemon=True)
            t.start()
        elif task.status in (Status.QUEUED, Status.FAILED):
            task.status = Status.QUEUED
            task.error  = None
            with self._lock:
                if task_id not in self._queue:
                    self._queue.append(task_id)

    def cancel(self, task_id: str):
        task = self._get(task_id)
        if task:
            task._stop_event.set()
            task._pause_event.clear()   # unblock if paused
            task.status = Status.CANCELLED
            with self._lock:
                self._active.discard(task_id)
                if task_id in self._queue:
                    self._queue.remove(task_id)

    def remove(self, task_id: str):
        self.cancel(task_id)
        with self._lock:
            self._tasks.pop(task_id, None)

    def get(self, task_id: str) -> Optional[DownloadTask]:
        return self._get(task_id)

    def list_tasks(self) -> list:
        with self._lock:
            return [t.to_dict() for t in self._tasks.values()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def _schedule_loop(self):
        while True:
            time.sleep(0.5)
            with self._lock:
                # clean finished from active set
                done = {tid for tid in self._active
                        if self._tasks.get(tid) and
                        self._tasks[tid].status not in (Status.DOWNLOADING, Status.PAUSED)}
                self._active -= done

                # start new tasks up to concurrency limit
                while self._queue and len(self._active) < self.MAX_CONCURRENT:
                    tid = self._queue.pop(0)
                    task = self._tasks.get(tid)
                    if task and task.status == Status.QUEUED:
                        self._active.add(tid)
                        t = threading.Thread(target=self._run_task, args=(task,), daemon=True)
                        t.start()

    def _run_task(self, task: DownloadTask):
        _run_download(task)
        with self._lock:
            self._active.discard(task.id)
