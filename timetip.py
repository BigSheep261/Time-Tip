"""TimeTip source entry point and backwards-compatible public imports."""
from app.bootstrap import main
from app.infrastructure.store import Store
from app.presentation.window import TimeTipWindow, make_app_icon
from app.presentation.theme import APP_NAME, STYLESHEET

if __name__ == "__main__":
    main()
