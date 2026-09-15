"""User-selectable dashboard date labels."""
from datetime import datetime
DATE_FORMATS = (("full_cn", "2026年09月09日 · 星期三"), ("compact_cn", "09月09日 · 星期三"), ("iso", "2026-09-09 · 星期三"), ("japanese", "2026年09月09日 · 水曜日"), ("both", "2026年09月09日 · 星期三 / 水曜日"))
_CN = "一二三四五六日"
_JP = "月火水木金土日"
def format_dashboard_date(value: datetime, style: str = "full_cn") -> str:
    if style == "compact_cn": return value.strftime("%m月%d日 · 星期") + _CN[value.weekday()]
    if style == "iso": return value.strftime("%Y-%m-%d · 星期") + _CN[value.weekday()]
    if style == "japanese": return value.strftime("%Y年%m月%d日 · ") + _JP[value.weekday()] + "曜日"
    if style == "both": return value.strftime("%Y年%m月%d日 · 星期") + _CN[value.weekday()] + " / " + _JP[value.weekday()] + "曜日"
    return value.strftime("%Y年%m月%d日 · 星期") + _CN[value.weekday()]
