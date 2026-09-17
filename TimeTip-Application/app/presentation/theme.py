"""Theme registry, semantic colors and live Qt styling.

Register additional themes before creating the window. For runtime registration,
call window.refresh_theme_options() afterwards; the settings UI has no fixed list.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

APP_NAME = "TimeTip"
DEFAULT_THEME_ID = "light"

LIGHT_COLORS = {
    "primary": "#5E5CE6", "text": "#1D1D1F", "muted": "#6E6E73",
    "surface": "#FFFFFF", "background": "#F5F5F7", "border": "#E5E5EA",
    "root_border": "#E4E6EF", "sidebar": "#FDFDFE", "window_icon": "#9A9EAD",
    "window_hover": "#E9EBF3", "nav_text": "#777B8C", "hover": "#F0F1F8",
    "accent_soft": "#ECE9FF", "accent_hover": "#DCD7FF", "accent_subtle": "#F0EDFF",
    "primary_button": "#5E5CE6", "primary_hover": "#5745D4", "primary_pressed": "#4837B8",
    "on_primary": "#FFFFFF", "hero_start": "#7667F2", "hero_end": "#5D4BD0",
    "input": "#FBFBFD", "secondary": "#F0F1F7", "secondary_text": "#505365",
    "secondary_hover": "#E5E6F0", "list_item": "#F6F7FB", "card_border": "#ECECF2",
    "card_hover": "#F6F5FF", "row_hover": "#F8F7FF", "focus_surface": "#FCFBFF",
    "calendar_alternate": "#FAFAFC", "scroll_handle": "#D8DAE5", "focus_ring": "#9385F0",
    "disabled_text": "#8A8D9C", "disabled": "#EAECF3", "input_disabled": "#F5F6FA",
    "danger": "#BA3345", "danger_bg": "#FFF0F2", "danger_hover": "#F9D9DE",
    "danger_button_hover": "#A52D3E", "danger_button_pressed": "#8F2635",
    "danger_border": "#F4CBD2", "success": "#237255", "warning": "#B26020",
    "green_bg": "#EAF5EE", "green_border": "#D1E7D8", "green_value": "#236346",
    "green_text": "#3F6A51", "widget_text": "#686D80", "widget_menu_text": "#606579",
}

DARK_COLORS = {
    **LIGHT_COLORS,
    "primary": "#B4A7FF", "text": "#ECEEF5", "muted": "#A2A8BA",
    "surface": "#202431", "background": "#151822", "border": "#343A4C",
    "root_border": "#3C4255", "sidebar": "#1B1F2B", "window_icon": "#A2A8BA",
    "window_hover": "#303648", "nav_text": "#ADB3C6", "hover": "#2A3042",
    "accent_soft": "#353051", "accent_hover": "#494067", "accent_subtle": "#302C48",
    "primary_button": "#6B59C9", "primary_hover": "#7663D8", "primary_pressed": "#5949AE",
    "hero_start": "#504388", "hero_end": "#392F66", "input": "#191D29",
    "secondary": "#303547", "secondary_text": "#DEE1EE", "secondary_hover": "#3C4257",
    "list_item": "#272C3B", "card_border": "#363B4D", "card_hover": "#2C2941",
    "row_hover": "#2B293D", "focus_surface": "#242236", "calendar_alternate": "#252A39",
    "scroll_handle": "#535C74", "focus_ring": "#B4A7FF", "disabled_text": "#828A9E",
    "disabled": "#292E3C", "input_disabled": "#252A37", "danger": "#FF9CAC",
    "danger_bg": "#422935", "danger_hover": "#583343", "danger_border": "#684051",
    "danger_button_hover": "#FFB0BD", "danger_button_pressed": "#E77F91",
    "success": "#82D7AC", "warning": "#F4B77D", "green_bg": "#21392F",
    "green_border": "#355547", "green_value": "#9CE0B8", "green_text": "#ADCFBC",
    "widget_text": "#ABB2C6", "widget_menu_text": "#BBC2D7",
}


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    description: str
    colors: Mapping[str, str]
    is_dark: bool = False

    def __post_init__(self):
        # Copy so a caller cannot silently mutate an already registered theme.
        object.__setattr__(self, "colors", MappingProxyType(dict(self.colors)))


_THEMES: dict[str, Theme] = {}


def register_theme(theme: Theme) -> None:
    """Public extension point. A complete color map keeps all pages consistent."""
    if not theme.id or not theme.label or theme.id in _THEMES:
        raise ValueError("Theme ID and label must be nonempty; IDs must be unique.")
    missing = LIGHT_COLORS.keys() - theme.colors.keys()
    if missing:
        raise ValueError(f"Missing theme colors: {', '.join(sorted(missing))}")
    if any(not QColor(value).isValid() for value in theme.colors.values()):
        raise ValueError("Theme colors must be valid Qt colors.")
    _THEMES[theme.id] = theme


def available_themes() -> tuple[Theme, ...]:
    return tuple(_THEMES.values())


def get_theme(theme_id: str) -> Theme:
    """Unknown or removed saved themes fall back to the default."""
    return _THEMES.get(theme_id, _THEMES[DEFAULT_THEME_ID])


register_theme(Theme("light", "日间模式", "明亮清爽的浅色界面。", LIGHT_COLORS))
register_theme(Theme("dark", "夜间模式", "柔和的深色背景，适合夜间使用。", DARK_COLORS, is_dark=True))

# Backwards-compatible defaults for existing importers and the static app icon.
PRIMARY, TEXT, MUTED, SURFACE, BACKGROUND, BORDER = (
    LIGHT_COLORS[key] for key in ("primary", "text", "muted", "surface", "background", "border")
)


_STYLESHEET_TEMPLATE = """
* {{ font-family: 'Microsoft YaHei UI'; color: {text}; font-size: 14px; }}
QMainWindow {{ background: transparent; }}
QDialog, QMessageBox {{ background: {background}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 6px; }}
#root {{ background: {background}; border: 1px solid {root_border}; border-radius: 22px; }}
#title {{ font-size: 16px; font-weight: 700; }}
#subtitle, #pageSubtitle, #cardHint, #statHint, #sideHint {{ color: {muted}; }}
#subtitle {{ font-size: 11px; }}
#windowButton {{ border: none; background: transparent; color: {window_icon}; font-size: 20px; border-radius: 10px; }}
#windowButton:hover {{ background: {window_hover}; color: {text}; }}
#sidebar {{ background: {sidebar}; border: 1px solid {border}; border-radius: 17px; }}
#sectionLabel, #fieldLabel {{ color: {muted}; font-size: 12px; font-weight: 600; }}
#sideHint {{ font-size: 11px; padding: 5px; line-height: 1.45; }}
#navButton {{ text-align: left; padding: 0 14px; border: none; border-radius: 11px; background: transparent; font-weight: 600; color: {nav_text}; }}
#navButton:hover {{ background: {hover}; color: {text}; }}
#navButton:checked {{ background: {accent_soft}; color: {primary}; }}
#pageTitle {{ font-size: 27px; font-weight: 750; }}
#clock {{ color: {primary}; font-size: 21px; font-weight: 700; letter-spacing: 1px; }}
#card, #heroCard, #focusCard {{ background: {surface}; border: 1px solid {border}; border-radius: 17px; }}
#heroCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {hero_start}, stop:1 {hero_end}); border: none; }}
#heroCard QLabel {{ color: {on_primary}; }}
#eyebrow {{ font-size: 12px; font-weight: 700; letter-spacing: 0.5px; }}
#chip {{ background: rgba(255,255,255,0.18); padding: 6px 11px; border-radius: 9px; font-size: 12px; }}
#countdown {{ font-size: 43px; font-weight: 750; letter-spacing: 1px; padding: 8px 0; }}
#cardTitle {{ font-size: 15px; font-weight: 700; }}
QDateTimeEdit, QTimeEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {{ background: {input}; border: 1px solid {border}; border-radius: 10px; padding: 8px 11px; selection-background-color: {accent_hover}; }}
QDateTimeEdit:focus, QTimeEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {{ border: 1px solid {primary}; }}
#primaryButton {{ background: {primary_button}; color: {on_primary}; border: none; border-radius: 10px; padding: 0 18px; min-height: 40px; font-weight: 700; }}
#primaryButton:hover {{ background: {primary_hover}; }}
#primaryButton:pressed {{ background: {primary_pressed}; }}
#dangerButton {{ background: {danger}; color: {on_primary}; border: none; border-radius: 10px; padding: 0 18px; min-height: 40px; font-weight: 700; }}
#dangerButton:hover {{ background: {danger_button_hover}; }}
#dangerButton:pressed {{ background: {danger_button_pressed}; }}
#secondaryButton {{ background: {secondary}; color: {secondary_text}; border: none; border-radius: 10px; padding: 8px 16px; font-weight: 600; }}
#secondaryButton:hover {{ background: {secondary_hover}; }}
#memoFormatToolbar {{ background: transparent; border: none; spacing: 1px; padding: 0; }}
#memoFormatToolbar QToolButton {{ background: transparent; color: {secondary_text}; border: none; border-radius: 6px; min-width: 26px; min-height: 34px; padding: 0 2px; }}
#memoFormatToolbar QToolButton:hover {{ background: {hover}; }}
#memoFormatToolbar QToolButton:checked {{ background: {accent_soft}; color: {primary}; }}
#memoFormatToolbar QToolButton:disabled {{ color: {disabled_text}; background: transparent; }}
#memoFormatToolbar QToolButton:focus {{ border: 1px solid {focus_ring}; }}
#memoFormatToolbar QToolButton::menu-indicator {{ image: none; width: 0; }}
#memoFormatToolbar::separator {{ width: 1px; margin: 8px 2px; background: {border}; }}
#memoFontCombo, #memoFontSize {{ min-height: 36px; padding: 4px 7px; border-radius: 8px; }}
#statTitle {{ color: {muted}; font-size: 12px; font-weight: 600; }}
#statValue {{ font-size: 22px; font-weight: 750; color: {primary}; }}
#cleanList {{ border: none; background: transparent; }}
#cleanList::item {{ background: {list_item}; border-radius: 8px; padding: 9px; margin: 2px 0; }}
#cleanList::item:selected {{ background: {accent_soft}; color: {primary}; }}
#jmQueueTabs::pane {{ border: none; background: transparent; padding-top: 8px; }}
#jmQueueTabs QTabBar::tab {{ background: {secondary}; color: {secondary_text}; border: none; border-radius: 8px; padding: 9px 16px; margin-right: 8px; }}
#jmQueueTabs QTabBar::tab:selected {{ background: {accent_soft}; color: {primary}; font-weight: 700; }}
#jmQueueTabs QTabBar::tab:hover {{ background: {secondary_hover}; }}
#animeListPanel {{ background: {surface}; border: 1px solid {border}; border-radius: 18px; padding: 10px; outline: none; }}
#animeListPanel::item {{ background: transparent; border: none; padding: 0; margin: 0; }}
#animeListPanel::item:selected {{ background: {accent_subtle}; border-radius: 13px; }}
#animeCard {{ background: {input}; border: 1px solid {card_border}; border-radius: 13px; }}
#animeCard:hover {{ background: {card_hover}; border: 1px solid {accent_hover}; }}
#animeCardActions {{ background: transparent; }}
#animeEditButton {{ background: {accent_soft}; color: {primary}; border: none; border-radius: 9px; padding: 7px 10px; font-weight: 700; }}
#animeEditButton:hover {{ background: {accent_hover}; }}
#animeDeleteButton {{ background: {danger_bg}; color: {danger}; border: none; border-radius: 9px; padding: 7px 10px; font-weight: 700; }}
#animeDeleteButton:hover {{ background: {danger_hover}; }}
#animeStepButton {{ background: {accent_subtle}; color: {primary}; border: none; border-radius: 10px; font-size: 20px; font-weight: 700; }}
#animeStepButton:hover {{ background: {accent_hover}; }}
#animeProgressInput {{ padding-left: 10px; padding-right: 6px; }}
#animeProgressInput::up-button, #animeProgressInput::down-button {{ width: 0px; height: 0px; border: none; }}
#episodeListPanel {{ background: {surface}; border: 1px solid {border}; border-radius: 16px; padding: 10px; outline: none; }}
#episodeListPanel::item {{ background: transparent; border: none; padding: 0; margin: 0 0 8px 0; }}
#episodeRow {{ background: {surface}; border: 1px solid {card_border}; border-radius: 10px; }}
#episodeRow:hover {{ background: {row_hover}; border-color: {accent_hover}; }}
#episodeNumber {{ color: {primary}; font-weight: 700; }}
#episodeName {{ color: {text}; }}
#animeCardTitle {{ font-size: 16px; font-weight: 700; color: {text}; }}
#animeCardMeta {{ color: {muted}; font-size: 12px; }}
#tarotSpreadButton {{ background: {input}; color: {text}; border: 1px solid {card_border}; border-radius: 11px; padding: 8px 12px; text-align: left; font-weight: 700; }}
#tarotSpreadButton:hover {{ background: {card_hover}; border-color: {accent_hover}; }}
#tarotSpreadButton:pressed {{ background: {accent_soft}; }}
#tarotCard {{ background: {input}; border: 1px solid {card_border}; border-radius: 14px; }}
#tarotCard[revealed="true"] {{ background: {focus_surface}; border-color: {accent_hover}; }}
#tarotPosition {{ color: {muted}; font-size: 12px; font-weight: 700; }}
#tarotOrientation {{ background: {accent_soft}; color: {primary}; border-radius: 7px; padding: 3px 7px; font-size: 11px; font-weight: 700; }}
#tarotBack {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {hero_start}, stop:1 {hero_end}); color: {on_primary}; border: none; border-radius: 11px; font-size: 20px; font-weight: 700; }}
#tarotBack:hover {{ background: {primary_hover}; }}
#tarotBack:disabled {{ background: {accent_soft}; color: {primary}; font-size: 21px; }}
#tarotCardName {{ color: {muted}; font-size: 12px; }}
#tarotMeaning {{ color: {text}; font-size: 14px; }}
#tarotQuestion {{ color: {primary}; background: {accent_subtle}; border-radius: 8px; padding: 8px 10px; }}
#tarotSummary {{ color: {secondary_text}; background: {accent_subtle}; border: 1px solid {accent_hover}; border-radius: 10px; padding: 10px 12px; }}
#animeCategoryChip {{ background: {accent_soft}; color: {primary}; border-radius: 7px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
#animeCover {{ background: {accent_soft}; border-radius: 11px; }}
#countdownCard {{ background: {input}; border: 1px solid {card_border}; border-radius: 13px; }}
#countdownCard:hover {{ background: {card_hover}; border: 1px solid {accent_hover}; }}
#countdownCardBadge {{ background: {accent_soft}; color: {primary}; border-radius: 11px; font-size: 24px; }}
#countdownCardTitle {{ font-size: 16px; font-weight: 700; color: {text}; }}
#countdownCardMeta {{ color: {muted}; font-size: 12px; }}
#countdownCardValue {{ color: {primary}; font-size: 17px; font-weight: 700; }}
#animeDialog {{ background: {background}; }}
#animeDialogTitle {{ font-size: 22px; font-weight: 750; color: {text}; }}
#animeDialogHint {{ color: {muted}; font-size: 12px; }}
#animeDialogCard {{ background: {surface}; border: 1px solid {border}; border-radius: 17px; }}
#animeDialogCover {{ background: {accent_soft}; border: 1px solid {accent_hover}; border-radius: 13px; }}
#animeDialogError {{ color: {danger}; background: {danger_bg}; border: 1px solid {danger_border}; border-radius: 9px; padding: 8px 11px; }}
#focusTime {{ font-size: 82px; font-weight: 750; color: {primary}; padding: 16px; }}
#focusCard {{ background: {focus_surface}; }}
QCalendarWidget QWidget {{ alternate-background-color: {calendar_alternate}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {accent_subtle}; border-radius: 10px; }}
QCalendarWidget QToolButton {{ color: {text}; background: transparent; border: none; font-weight: 700; padding: 8px; }}
QCalendarWidget QToolButton:hover {{ background: {hover}; border-radius: 8px; }}
QCalendarWidget QAbstractItemView:enabled {{ selection-background-color: {primary_button}; selection-color: {on_primary}; outline: none; }}
QScrollBar:vertical {{ width: 8px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {scroll_handle}; border-radius: 4px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QPushButton:focus {{ border: 2px solid {focus_ring}; }}
QPushButton:disabled {{ color: {disabled_text}; background: {disabled}; }}
QLineEdit:disabled, QTextEdit:disabled {{ background: {input_disabled}; }}
QCheckBox {{ spacing: 6px; min-height: 30px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; }}
QComboBox {{ min-width: 85px; }}
QComboBox QAbstractItemView {{ background: {surface}; color: {text}; border: 1px solid {border}; selection-background-color: {accent_soft}; selection-color: {primary}; outline: none; }}
QLabel#cardHint[feedbackState="error"] {{ color: {danger}; }}
QLabel#cardHint[feedbackState="success"] {{ color: {success}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 6px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {primary}; }}
#widgetCard {{ background: {surface}; border: 1px solid {border}; border-radius: 18px; }}
#widgetCard[tone="purple"] {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {hero_start}, stop:1 {hero_end}); border: none; }}
#widgetCard[tone="green"] {{ background: {green_bg}; border: 1px solid {green_border}; }}
#widgetTitle {{ font-size: 13px; font-weight: 600; color: {widget_text}; }}
#widgetValue {{ color: {primary}; }}
#widgetHint, #widgetDetail {{ font-size: 12px; color: {widget_text}; }}
#widgetCard[tone="purple"] QLabel, #widgetCard[tone="purple"] QPushButton {{ color: {on_primary}; }}
#widgetCard[tone="green"] #widgetValue {{ color: {green_value}; }}
#widgetCard[tone="green"] #widgetTitle, #widgetCard[tone="green"] #widgetHint {{ color: {green_text}; }}
#widgetLink {{ background: transparent; border: none; text-align: left; font-size: 12px; color: {primary}; padding: 5px 0; }}
#widgetLink:hover {{ text-decoration: underline; }}
#widgetMenu {{ background: {secondary}; color: {widget_menu_text}; border: none; border-radius: 8px; font-size: 20px; }}
#widgetCard[tone="purple"] #widgetMenu {{ background: rgba(255,255,255,0.20); }}
#widgetMenu:hover {{ background: {accent_hover}; }}
"""


def build_stylesheet(theme: Theme) -> str:
    return _STYLESHEET_TEMPLATE.format_map(theme.colors)


def apply_theme(app: QApplication, theme_id: str) -> Theme:
    """Repaint existing widgets, popups and dialogs without recreating any UI."""
    theme = get_theme(theme_id)
    colors = theme.colors
    palette = QPalette()
    roles = {
        "Window": "background", "WindowText": "text", "Base": "input",
        "AlternateBase": "calendar_alternate", "Text": "text", "Button": "secondary",
        "ButtonText": "text", "ToolTipBase": "surface", "ToolTipText": "text",
        "Highlight": "primary_button", "HighlightedText": "on_primary",
        "Link": "primary", "LinkVisited": "primary", "PlaceholderText": "muted",
        "Light": "border", "Midlight": "secondary_hover", "Mid": "border",
        "Dark": "root_border", "Shadow": "background", "BrightText": "on_primary",
        "Accent": "primary",
    }
    for role, key in roles.items():
        qt_role = getattr(QPalette.ColorRole, role, None)
        if qt_role is not None:
            palette.setColor(qt_role, QColor(colors[key]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled_text"]))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(theme))
    return theme


def set_feedback_state(widget: QWidget, state: str) -> None:
    widget.setProperty("feedbackState", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


STYLESHEET = build_stylesheet(get_theme(DEFAULT_THEME_ID))

