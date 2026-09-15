import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(os.getenv('INSTALL_ROOT') or (Path(sys.executable).resolve().parent.parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1])).resolve()
load_dotenv(ROOT / "service_core" / ".env")
load_dotenv(ROOT / "backend_web" / ".env", override=True)
INSTALL_ROOT = Path(os.getenv("INSTALL_ROOT", ROOT)).resolve()
DATA_ROOT = Path(os.getenv("DATA_DIR", INSTALL_ROOT / "ProgramData")).resolve()
DB_PATH = Path(os.getenv("DB_PATH", DATA_ROOT / "database" / "service.sqlite3")).resolve()
PACKAGE_ROOT = Path(os.getenv("PACKAGE_DIR", DATA_ROOT / "packages")).resolve()
GITHUB_PACKAGE_DIR = PACKAGE_ROOT / "github"
MANUAL_PACKAGE_DIR = PACKAGE_ROOT / "manual"
LOG_DIR = Path(os.getenv("LOG_DIR", DATA_ROOT / "logs")).resolve()
CORE_HOST = os.getenv("CORE_HOST", "0.0.0.0")
CORE_PORT = int(os.getenv("CORE_PORT", "8787"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8788"))
WEB_DIR = Path(os.getenv("WEB_DIR", ROOT / "backend_web" / "dist")).resolve()
WEB_COMMAND = os.getenv("WEB_COMMAND", "")
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "change-me")
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "change-this-secret")
TOKEN_TTL_SECONDS = 3 * 24 * 60 * 60
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "release")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
PACKAGE_EXTENSIONS = tuple(x.strip().lower() for x in os.getenv("PACKAGE_EXTENSIONS", ".exe").split(",") if x.strip())
CLIENT_OS = os.getenv("CLIENT_OS", "windows")
CLIENT_ARCH = os.getenv("CLIENT_ARCH", "x64")
for directory in (DATA_ROOT, DB_PATH.parent, GITHUB_PACKAGE_DIR, MANUAL_PACKAGE_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

