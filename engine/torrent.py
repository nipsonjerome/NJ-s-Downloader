"""
Torrent engine — wraps libtorrent for magnet/torrent file support.
Falls back gracefully with a clear error if libtorrent is not installed.
"""

import os
import time
import threading
from typing import Optional

try:
    import libtorrent as lt
    HAS_LIBTORRENT = True
except ImportError:
    HAS_LIBTORRENT = False


class TorrentSession:
    """Manages all active torrent handles."""

    def __init__(self, save_path: str = "./downloads"):
        self.save_path = save_path
        self._handles: dict[str, object] = {}   # task_id -> handle
        self._meta:    dict[str, dict]   = {}   # task_id -> metadata dict
        self._lock     = threading.Lock()

        if HAS_LIBTORRENT:
            self._session = lt.session()
            self._session.listen_on(6881, 6891)
            settings = self._session.get_settings()
            settings['alert_mask'] = lt.alert.category_t.all_categories
            self._session.apply_settings(settings)

            self._alert_thread = threading.Thread(target=self._process_alerts, daemon=True)
            self._alert_thread.start()

    def add_magnet(self, task_id: str, magnet_uri: str) -> dict:
        if not HAS_LIBTORRENT:
            return {"error": "libtorrent not installed. Run: pip install libtorrent"}

        params = lt.parse_magnet_uri(magnet_uri)
        params.save_path = self.save_path
        handle = self._session.add_torrent(params)

        meta = {
            "id":       task_id,
            "name":     magnet_uri[:60] + "...",
            "status":   "fetching_metadata",
            "progress": 0.0,
            "speed_dl": 0,
            "speed_ul": 0,
            "peers":    0,
            "seeds":    0,
            "eta":      0,
            "total":    0,
            "done":     0,
        }
        with self._lock:
            self._handles[task_id] = handle
            self._meta[task_id]    = meta
        return meta

    def add_torrent_file(self, task_id: str, torrent_path: str) -> dict:
        if not HAS_LIBTORRENT:
            return {"error": "libtorrent not installed. Run: pip install libtorrent"}

        info   = lt.torrent_info(torrent_path)
        params = {"ti": info, "save_path": self.save_path}
        handle = self._session.add_torrent(params)

        meta = {
            "id":       task_id,
            "name":     info.name(),
            "status":   "queued",
            "progress": 0.0,
            "speed_dl": 0,
            "speed_ul": 0,
            "peers":    0,
            "seeds":    0,
            "eta":      0,
            "total":    info.total_size(),
            "done":     0,
        }
        with self._lock:
            self._handles[task_id] = handle
            self._meta[task_id]    = meta
        return meta

    def get_status(self, task_id: str) -> Optional[dict]:
        with self._lock:
            if task_id not in self._handles:
                return None
            handle = self._handles[task_id]
            s      = handle.status()
            meta   = self._meta[task_id]

            STATE_MAP = {
                0: "queued",
                1: "checking",
                2: "fetching_metadata",
                3: "downloading",
                4: "finished",
                5: "seeding",
                6: "allocating",
                7: "checking_resume",
            }
            meta["status"]   = STATE_MAP.get(s.state, "unknown")
            meta["progress"] = round(s.progress * 100, 2)
            meta["speed_dl"] = s.download_rate
            meta["speed_ul"] = s.upload_rate
            meta["peers"]    = s.num_peers
            meta["seeds"]    = s.num_seeds
            meta["total"]    = s.total_wanted
            meta["done"]     = s.total_wanted_done
            if s.download_rate > 0 and s.total_wanted > s.total_wanted_done:
                meta["eta"] = int((s.total_wanted - s.total_wanted_done) / s.download_rate)
            else:
                meta["eta"] = 0
            if hasattr(s, 'name') and s.name:
                meta["name"] = s.name
            return dict(meta)

    def list_torrents(self) -> list:
        with self._lock:
            return [self.get_status(tid) for tid in self._handles]

    def pause(self, task_id: str):
        with self._lock:
            h = self._handles.get(task_id)
            if h:
                h.pause()
                self._meta[task_id]["status"] = "paused"

    def resume(self, task_id: str):
        with self._lock:
            h = self._handles.get(task_id)
            if h:
                h.resume()
                self._meta[task_id]["status"] = "downloading"

    def remove(self, task_id: str, delete_files: bool = False):
        with self._lock:
            h = self._handles.pop(task_id, None)
            self._meta.pop(task_id, None)
            if h and HAS_LIBTORRENT:
                flags = lt.options_t.delete_files if delete_files else 0
                self._session.remove_torrent(h, flags)

    def _process_alerts(self):
        while True:
            alerts = self._session.pop_alerts()
            for _alert in alerts:
                pass   # extend here: log errors, fire events, etc.
            time.sleep(0.5)
