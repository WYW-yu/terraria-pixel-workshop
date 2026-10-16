"""用户主动进入的多屏取色：点击选色，Esc取消；不保存屏幕图像。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QCursor
from PySide6.QtWidgets import QApplication, QWidget


class ScreenOverlay(QWidget):
    picked = Signal(object)
    cancelled = Signal()

    def __init__(self, geometry, snapshot, cursor):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.snapshot = snapshot
        self.image = snapshot.toImage()
        self.setGeometry(geometry)
        self.setCursor(cursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.point = None

    def sample(self, point):
        image = self.image
        x = min(image.width()-1, max(0, int(point.x()*image.width()/self.width())))
        y = min(image.height()-1, max(0, int(point.y()*image.height()/self.height())))
        color = image.pixelColor(x, y)
        return color.red(), color.green(), color.blue()

    def mouseMoveEvent(self, event):
        self.point = event.position()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.sample(event.position()))
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        if self.point is not None:
            from .pixels import color_text
            text = color_text(self.sample(self.point)) + ' · 点击取色 / Esc取消'
            x = max(0, min(self.width()-300, int(self.point.x())+20))
            y = max(0, min(self.height()-40, int(self.point.y())+20))
            painter.fillRect(x, y, 300, 32, QColor('#101522'))
            painter.setPen(QColor('white'))
            painter.drawText(x+8, y+21, text)


class ScreenPicker:
    def __init__(self, owner, cursor, picked):
        self.owner, self.picked = owner, picked
        self.windows = []
        # 在显示任何覆盖窗之前取所有屏幕，避免后一个屏幕包含前一个覆盖窗。
        snapshots = [(s.geometry(), s.grabWindow(0)) for s in QApplication.screens()]
        if not snapshots or any(p.isNull() for _, p in snapshots):
            raise RuntimeError('无法读取屏幕颜色。')
        for geometry, snapshot in snapshots:
            window = ScreenOverlay(geometry, snapshot, cursor)
            window.picked.connect(self.finish)
            window.cancelled.connect(self.cancel)
            self.windows.append(window)
        for window in self.windows:
            window.show()
            window.raise_()
            if window.geometry().contains(QCursor.pos()):
                window.activateWindow()
                window.setFocus()

    def finish(self, rgb):
        self.cancel()
        self.picked(rgb)

    def cancel(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.windows.clear()
        self.owner.window().activateWindow()
