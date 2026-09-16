import logging
from logging.handlers import RotatingFileHandler
from waitress import create_server
from .config import CORE_HOST, CORE_PORT, LOG_DIR
from .db import init_db
from .app import app
from .web_process import start_web

def run():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_DIR / "service.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    init_db()
    web = start_web()
    server = create_server(app, host=CORE_HOST, port=CORE_PORT, threads=8)
    logging.info("Core started on %s:%s", CORE_HOST, CORE_PORT)
    try:
        server.run()
    finally:
        server.close()
        if web:
            web.close()
