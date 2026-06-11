"""
FreeDL — main entry point for the compiled executable.
Starts the Flask server and opens the browser automatically.
"""

import os
import sys
import threading
import webbrowser
import time

# When running as a PyInstaller bundle, adjust paths
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    APP_DIR  = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)
    APP_DIR  = BASE_DIR

# Put bundled packages on path
sys.path.insert(0, BASE_DIR)

# Set download dir next to the exe
DOWNLOAD_DIR = os.path.join(APP_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.environ["FDM_DOWNLOAD_DIR"] = DOWNLOAD_DIR

PORT = 5000

def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{PORT}")

def main():
    # Start browser opener in background
    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    print(f"FreeDL starting on http://localhost:{PORT}")
    print(f"Downloads folder: {DOWNLOAD_DIR}")
    print("Press Ctrl+C to quit.")

    from api.server import app
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()
