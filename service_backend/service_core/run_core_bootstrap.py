import os
import sys
import secrets
from pathlib import Path

ROOT = Path(os.getenv("INSTALL_ROOT") or (Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1])).resolve()
os.environ["INSTALL_ROOT"] = str(ROOT)

def initialize_config():
    from dotenv import dotenv_values
    core_env = ROOT / "service_core" / ".env"
    web_env = ROOT / "backend_web" / ".env"
    core_env.parent.mkdir(parents=True, exist_ok=True)
    web_env.parent.mkdir(parents=True, exist_ok=True)
    existing = dotenv_values(core_env) if core_env.exists() else {}
    if not core_env.exists():
        core_env.write_text("CORE_HOST=0.0.0.0\nCORE_PORT=8787\nWEB_HOST=0.0.0.0\nWEB_PORT=8788\nTOKEN_SECRET=" + secrets.token_urlsafe(48) + "\nCLIENT_OS=windows\nCLIENT_ARCH=x64\n", encoding="utf-8")
    if not web_env.exists():
        username = existing.get("AUTH_USERNAME") or "admin"
        password = existing.get("AUTH_PASSWORD") or secrets.token_urlsafe(18)
        web_env.write_text("AUTH_USERNAME=" + username + "\nAUTH_PASSWORD=" + password + "\n", encoding="utf-8")
        info = ROOT / "ProgramData" / "config" / "initial-login.txt"
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text("Time-Tip Service\n\nWeb: http://SERVER-IP:8788\nUsername: " + username + "\nPassword: " + password + "\n\nLogin configuration: backend_web/.env\nKeep this file private. Existing configuration is preserved during upgrades.\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    if "--init-config" in sys.argv:
        raise SystemExit(initialize_config())
    from service_core.runtime import run
    run()
