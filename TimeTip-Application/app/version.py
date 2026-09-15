"""Application version shared by the UI, updater and release tooling."""

APP_NAME = "TimeTip"
APP_VERSION = "1.4.7"
DISPLAY_VERSION = "V" + APP_VERSION


def version_tuple(value: str) -> tuple[int, ...]:
    raw = str(value).strip().lstrip("vV")
    parts = raw.split(".")
    if not raw or not parts or any(not part.isdigit() for part in parts):
        raise ValueError("无效版本号")
    return tuple(int(part) for part in parts)


def is_newer(remote: str, current: str = APP_VERSION) -> bool:
    left, right = version_tuple(remote), version_tuple(current)
    size = max(len(left), len(right))
    return (left + (0,) * (size - len(left))) > (right + (0,) * (size - len(right)))