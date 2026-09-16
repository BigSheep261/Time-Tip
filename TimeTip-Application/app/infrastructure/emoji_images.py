"""Content identities for static images and complete animations."""
from __future__ import annotations

import hashlib
import struct

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage, QImageReader


def image_fingerprint(image: QImage) -> bytes:
    normalized = image.convertToFormat(QImage.Format.Format_RGBA8888)
    digest = hashlib.sha256(struct.pack("!II", normalized.width(), normalized.height()))
    digest.update(bytes(normalized.constBits())[:normalized.sizeInBytes()])
    return digest.digest()


def emoji_fingerprint(data: bytes) -> str | None:
    """Ignore filenames/encoding for stills; include every frame and delay for animations."""
    source = QBuffer()
    source.setData(data)
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source)
    reader.setDecideFormatFromContent(True)
    frames = []
    while reader.canRead():
        image = reader.read()
        if image.isNull():
            return None
        frames.append((image_fingerprint(image), reader.nextImageDelay()))
        if not reader.supportsAnimation():
            break
    if not frames:
        return None
    if len(frames) == 1:
        return "image:" + frames[0][0].hex()
    digest = hashlib.sha256()
    for pixels, delay in frames:
        digest.update(pixels)
        digest.update(struct.pack("!i", delay))
    return "animation:" + digest.hexdigest()
