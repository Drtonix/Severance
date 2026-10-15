"""Пожертвования: ссылки и кошелёк. Файл один и тот же во всех открытых
приложениях — как _style.py: правится в одном, копируется в остальные."""
from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import QApplication, QPushButton, QToolTip

LINKS = (("DonationAlerts", "https://www.donationalerts.com/r/bdub"),
         ("DALINK", "https://dalink.to/bdub"),
         ("CloudTips", "https://pay.cloudtips.ru/p/4a29ea73"))
NETWORK = "USDT TRC-20"
USDT = "TEzUu8mVuNS1faHGobMWifmvErTuKUSkPD"
GAP = "&nbsp;" * 6     # подряд идущие пробелы Qt схлопывает, неразрывные — нет
COPY = "copy:usdt"


class CopyButton(QPushButton):
    """«USDT TRC-20»: щелчок копирует адрес кошелька, на миг на кнопке —
    «Скопировано». Ширина — по длинной из двух надписей: соседи не сдвигаются."""

    def __init__(self, copied, name):
        super().__init__(NETWORK)
        self.copied = copied
        self.setObjectName(name)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(USDT)
        self.clicked.connect(self._copy)

    def sizeHint(self):
        # Считается один раз на шрифт: пересчёт от текущей надписи давал разницу
        # в точку из-за округления, и соседние кнопки вздрагивали.
        hint = super().sizeHint()
        key = self.font().key()
        if getattr(self, "_key", None) != key:
            fm = self.fontMetrics()
            pad = hint.width() - fm.horizontalAdvance(self.text())
            self._key = key
            self._width = max(fm.horizontalAdvance(NETWORK), fm.horizontalAdvance(self.copied)) + pad + 2
        return QSize(self._width, hint.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def _copy(self):
        QApplication.clipboard().setText(USDT)
        self.setText(self.copied)
        QTimer.singleShot(1500, lambda: self.setText(NETWORK))


def link_buttons(copied, name="cardbtn"):
    """Ссылки и кошелёк кнопками — как остальные кнопки карточек."""
    out = []
    for title, url in LINKS:
        b = QPushButton(title)
        b.setObjectName(name)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(url)
        b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        out.append(b)
    out.append(CopyButton(copied, name))
    return out


def links_html():
    """Для окон «О программе»: ссылки и кошелёк, щелчок по кошельку копирует (см. follow)."""
    return GAP.join([f'<a href="{url}">{name}</a>' for name, url in LINKS]
                    + [f'<a href="{COPY}">{NETWORK}</a>'])


def follow(url, copied=""):
    """Ссылки в окне «О программе»: кошелёк — в буфер, «Скопировано» всплывает у
    курсора, чтобы окно не перестраивалось; остальное — веб-адреса."""
    if url == COPY:
        QApplication.clipboard().setText(USDT)
        if copied:
            QToolTip.showText(QCursor.pos(), copied)
        return
    url = QUrl(url)
    if url.scheme().lower() in ("http", "https"):
        QDesktopServices.openUrl(url)
