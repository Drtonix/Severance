"""AppIcon.ico для Windows: те же картинки, что рисует Icon Composer, в семи размерах.

В ICO с Vista можно класть PNG как есть, так что упаковка — заголовок и оглавление.
"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage

SIZES = (16, 24, 32, 48, 64, 128, 256)


def pack(pngs: dict, out: Path):
    head = struct.pack("<HHH", 0, 1, len(pngs))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(pngs)
    for size, data in sorted(pngs.items()):
        side = 0 if size >= 256 else size   # 0 в оглавлении значит 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    out.write_bytes(head + entries + blobs)


def png8(path: Path) -> bytes:
    """ictool пишет 16 бит на канал, а Windows в значках понимает только 8."""
    img = QImage(str(path)).convertToFormat(QImage.Format_ARGB32)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


if __name__ == "__main__":
    QGuiApplication.instance() or QGuiApplication([])
    folder, out = Path(sys.argv[1]), Path(sys.argv[2])
    pack({n: png8(folder / f"{n}.png") for n in SIZES}, out)
