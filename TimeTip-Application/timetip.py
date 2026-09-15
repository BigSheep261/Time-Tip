"""TimeTip source entry point and backwards-compatible public imports."""
from app.bootstrap import main
from app.infrastructure.store import Store
from app.presentation.window import TimeTipWindow, make_app_icon
from app.version import APP_VERSION, DISPLAY_VERSION
from app.presentation.theme import (APP_NAME, STYLESHEET, Theme, available_themes,
                                    build_stylesheet, register_theme)

if __name__ == "__main__":
    main()
