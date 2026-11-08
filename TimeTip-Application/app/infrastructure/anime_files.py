"""Local video imports with no replacement of existing files."""
from __future__ import annotations

import os
from pathlib import Path
import shutil


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}


def move_anime_video(source: Path, folder: Path) -> Path:
    """Move a video; preserve its source if copying to another drive fails."""
    source, folder = Path(source), Path(folder)
    if not folder.is_dir():
        raise ValueError("目标文件夹不存在，请先在番剧编辑窗口中重新设置。")
    if source.is_symlink() or not source.is_file() or source.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("请选择本地视频文件。")
    source, folder = source.resolve(), folder.resolve()
    if source.parent == folder:
        raise ValueError("文件已在目标文件夹中，无需移动。")
    destination = folder / source.name
    if os.path.lexists(destination):
        raise FileExistsError("目标文件夹中已有同名文件，已跳过。")

    # Windows rename is a fast same-drive move and refuses existing targets.
    if os.name == "nt":
        try:
            source.rename(destination)
            return destination
        except FileExistsError:
            raise FileExistsError("目标文件夹中已有同名文件，已跳过。") from None
        except OSError:
            pass  # Cross-drive moves require copying before removing the source.

    # Exclusive creation also protects against a target appearing during import.
    with source.open("rb") as reader:
        writer = destination.open("xb")
        try:
            with writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
            shutil.copystat(source, destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    try:
        source.unlink()
    except OSError:
        destination.unlink(missing_ok=True)
        raise
    return destination
