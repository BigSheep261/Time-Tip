"""Shared application theme."""
APP_NAME = "TimeTip"
PRIMARY = "#5E5CE6"
TEXT = "#1D1D1F"
MUTED = "#6E6E73"
SURFACE = "#FFFFFF"
BACKGROUND = "#F5F5F7"
BORDER = "#E5E5EA"


STYLESHEET = f"""
* {{ font-family: 'Microsoft YaHei UI'; color: {TEXT}; font-size: 14px; }}
QMainWindow {{ background: transparent; }}
#root {{ background: {BACKGROUND}; border: 1px solid #E4E6EF; border-radius: 22px; }}
#logo {{ background: {PRIMARY}; color: white; border-radius: 12px; font-size: 20px; font-weight: 700; }}
#title {{ font-size: 16px; font-weight: 700; }}
#subtitle, #pageSubtitle, #cardHint, #statHint, #sideHint {{ color: {MUTED}; }}
#subtitle {{ font-size: 11px; }}
#windowButton {{ border: none; background: transparent; color: #9A9EAD; font-size: 20px; border-radius: 10px; }}
#windowButton:hover {{ background: #E9EBF3; color: {TEXT}; }}
#sidebar {{ background: rgba(255,255,255,0.75); border: 1px solid {BORDER}; border-radius: 17px; }}
#sectionLabel, #fieldLabel {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
#sideHint {{ font-size: 11px; padding: 5px; line-height: 1.45; }}
#navButton {{ text-align: left; padding: 0 14px; border: none; border-radius: 11px; background: transparent; font-weight: 600; color: #777B8C; }}
#navButton:hover {{ background: #F0F1F8; color: {TEXT}; }}
#navButton:checked {{ background: #ECE9FF; color: {PRIMARY}; }}
#pageTitle {{ font-size: 27px; font-weight: 750; }}
#clock {{ color: {PRIMARY}; font-size: 21px; font-weight: 700; letter-spacing: 1px; }}
#card, #heroCard, #focusCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 17px; }}
#heroCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7667F2, stop:1 #5D4BD0); border: none; }}
#heroCard QLabel {{ color: white; }}
#eyebrow {{ font-size: 12px; font-weight: 700; letter-spacing: 0.5px; }}
#chip {{ background: rgba(255,255,255,0.18); padding: 6px 11px; border-radius: 9px; font-size: 12px; }}
#countdown {{ font-size: 43px; font-weight: 750; letter-spacing: 1px; padding: 8px 0; }}
#cardTitle {{ font-size: 15px; font-weight: 700; }}
QDateTimeEdit, QTimeEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {{ background: #FBFBFD; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 11px; selection-background-color: #DCD7FF; }}
QDateTimeEdit:focus, QTimeEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {{ border: 1px solid {PRIMARY}; }}
#primaryButton {{ background: {PRIMARY}; color: white; border: none; border-radius: 10px; padding: 0 18px; min-height: 40px; font-weight: 700; }}
#primaryButton:hover {{ background: #5745D4; }}
#primaryButton:pressed {{ background: #4837B8; }}
#secondaryButton {{ background: #F0F1F7; color: #505365; border: none; border-radius: 10px; padding: 8px 16px; font-weight: 600; }}
#secondaryButton:hover {{ background: #E5E6F0; }}
#statTitle {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
#statValue {{ font-size: 22px; font-weight: 750; color: {PRIMARY}; }}
#cleanList {{ border: none; background: transparent; }}
#cleanList::item {{ background: #F6F7FB; border-radius: 8px; padding: 9px; margin: 2px 0; }}
#cleanList::item:selected {{ background: #ECE9FF; color: {PRIMARY}; }}
#animeListPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 18px; padding: 10px; outline: none; }}
#animeListPanel::item {{ background: transparent; border: none; padding: 0; margin: 0; }}
#animeListPanel::item:selected {{ background: #F0EDFF; border-radius: 13px; }}
#animeCard {{ background: #FBFBFD; border: 1px solid #ECECF2; border-radius: 13px; }}
#animeCard:hover {{ background: #F6F5FF; border: 1px solid #DCD7FF; }}
#animeCardTitle {{ font-size: 16px; font-weight: 700; color: {TEXT}; }}
#animeCardMeta {{ color: {MUTED}; font-size: 12px; }}
#animeCategoryChip {{ background: #ECE9FF; color: {PRIMARY}; border-radius: 7px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
#animeCover {{ background: #ECE9FF; border-radius: 11px; }}
#animeDialog {{ background: {BACKGROUND}; }}
#animeDialogTitle {{ font-size: 22px; font-weight: 750; color: {TEXT}; }}
#animeDialogHint {{ color: {MUTED}; font-size: 12px; }}
#animeDialogCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 17px; }}
#animeDialogCover {{ background: #ECE9FF; border: 1px solid #DCD7FF; border-radius: 13px; }}
#animeDialogError {{ color: #BA3345; background: #FFF0F2; border: 1px solid #F4CBD2; border-radius: 9px; padding: 8px 11px; }}
#focusTime {{ font-size: 82px; font-weight: 750; color: {PRIMARY}; padding: 16px; }}
#focusCard {{ background: #FCFBFF; }}
QCalendarWidget QWidget {{ alternate-background-color: #FAFAFC; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: #F0EDFF; border-radius: 10px; }}
QCalendarWidget QToolButton {{ color: {TEXT}; background: transparent; border: none; font-weight: 700; padding: 8px; }}
QCalendarWidget QToolButton:hover {{ background: #F0F1F8; border-radius: 8px; }}
QCalendarWidget QAbstractItemView:enabled {{ selection-background-color: {PRIMARY}; selection-color: white; outline: none; }}
QScrollBar:vertical {{ width: 8px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #D8DAE5; border-radius: 4px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QPushButton:focus {{ border: 2px solid #9385F0; }}
QPushButton:disabled {{ color: #8A8D9C; background: #EAECF3; }}
QLineEdit:disabled, QTextEdit:disabled {{ background: #F5F6FA; }}
QCheckBox {{ spacing: 6px; min-height: 30px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; }}
QComboBox {{ min-width: 85px; }}
QMenu {{ background: white; border: 1px solid {BORDER}; padding: 6px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: #ECE9FF; color: {PRIMARY}; }}
#widgetCard {{ background: white; border: 1px solid {BORDER}; border-radius: 18px; }}
#widgetCard[tone="purple"] {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7667F2, stop:1 #5D4BD0); border: none; }}
#widgetCard[tone="green"] {{ background: #EAF5EE; border: 1px solid #D1E7D8; }}
#widgetTitle {{ font-size: 13px; font-weight: 600; color: #686D80; }}
#widgetValue {{ color: {PRIMARY}; }}
#widgetHint, #widgetDetail {{ font-size: 12px; color: #686D80; }}
#widgetCard[tone="purple"] QLabel, #widgetCard[tone="purple"] QPushButton {{ color: white; }}
#widgetCard[tone="green"] #widgetValue {{ color: #236346; }}
#widgetCard[tone="green"] #widgetTitle, #widgetCard[tone="green"] #widgetHint {{ color: #3F6A51; }}
#widgetLink {{ background: transparent; border: none; text-align: left; font-size: 12px; color: {PRIMARY}; padding: 5px 0; }}
#widgetLink:hover {{ text-decoration: underline; }}
#widgetMenu {{ background: #F0F1F7; color: #606579; border: none; border-radius: 8px; font-size: 20px; }}
#widgetCard[tone="purple"] #widgetMenu {{ background: rgba(255,255,255,0.20); }}
#widgetMenu:hover {{ background: #DCD7FF; }}
"""

