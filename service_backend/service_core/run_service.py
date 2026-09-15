import threading
import time
from service_core.app import run
from service_core.github_sync import sync_github

def daily_sync():
    while True:
        try:
            sync_github()
        except Exception:
            pass
        time.sleep(24 * 60 * 60)

threading.Thread(target=daily_sync, daemon=True).start()
run()
