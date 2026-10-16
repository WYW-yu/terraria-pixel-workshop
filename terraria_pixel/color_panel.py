"""选色面板：HSB 拾色器（色相条 + 饱和度/明度区 + 数值）、历史用色、经典色板。

参考的是「色盘 + 历史 + 经典 + 值」三页的常见画图软件布局；纯 Qt 实现，不依赖外部控件。
纯函数部分（颜色换算、经典色板、历史记录）与界面分离，方便单测。
"""
from __future__ import annotations
import numpy as np

from PySide6.QtCore import Qt, Signal, QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget)
from .pixels import color_text

HISTORY_LIMIT = 18
SWATCH = 22


# ---------- 纯函数（可单测） ----------

def rgb_to_hsv(rgb) -> tuple[float, float, float]:
    """RGB(0-255) → (色相 0-360, 饱和度 0-1, 明度 0-1)。纯算术，避免整数色相带来的取整误差。"""
    r, g, b = [min(255, max(0, int(v))) / 255.0 for v in rgb[:3]]
    mx, mn = max(r, g, b), min(r, g, b)
    value = mx
    saturation = 0.0 if mx <= 0 else (mx - mn) / mx
    if mx <= mn:
        hue = 0.0
    elif mx == r:
        hue = (60.0 * ((g - b) / (mx - mn))) % 360.0
    elif mx == g:
        hue = 60.0 * ((b - r) / (mx - mn)) + 120.0
    else:
        hue = 60.0 * ((r - g) / (mx - mn)) + 240.0
    return hue % 360.0, saturation, value


def hsv_to_rgb(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
    hue = float(hue) % 360.0
    saturation = max(0.0, min(1.0, float(saturation)))
    value = max(0.0, min(1.0, float(value)))
    chroma = value * saturation
    x = chroma * (1 - abs((hue / 60.0) % 2 - 1))
    m = value - chroma
    if hue < 60:
        rgb = (chroma, x, 0.0)
    elif hue < 120:
        rgb = (x, chroma, 0.0)
    elif hue < 180:
        rgb = (0.0, chroma, x)
    elif hue < 240:
        rgb = (0.0, x, chroma)
    elif hue < 300:
        rgb = (x, 0.0, chroma)
    else:
        rgb = (chroma, 0.0, x)
    return tuple(int(round((channel + m) * 255)) for channel in rgb)


def hex_text(rgb) -> str:
    return color_text(rgb)


def parse_hex(text: str):
    """解析 #RGB / #RRGGBB / RRGGBB，失败返回 None。"""
    value = text.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    try:
        number = int(value, 16)
    except ValueError:
        return None
    return (number >> 16) & 255, (number >> 8) & 255, number & 255


def classic_swatches(columns: int = 12, rows: int = 5) -> list[tuple[int, int, int]]:
    """经典色板：上面几行按色相排布、亮度递减，最后一行是灰阶。"""
    colors = []
    for row in range(max(1, rows - 1)):
        for column in range(columns):
            hue = column * 360.0 / columns
            saturation = max(0.3, 1.0 - row * 0.18)
            value = max(0.35, 1.0 - row * 0.14)
            colors.append(hsv_to_rgb(hue, saturation, value))
    greys = [hsv_to_rgb(0, 0, v) for v in (0.98, 0.8, 0.62, 0.45, 0.28, 0.12)]
    colors += greys + [hsv_to_rgb(0, 0, 0.02)] * max(0, columns - len(greys))
    return colors


class ColorHistory:
    """最近用过的颜色（去重、限量）。"""

    def __init__(self, limit: int = HISTORY_LIMIT):
        self.limit = limit
        self.items: list[tuple[int, int, int]] = []

    def push(self, rgb) -> None:
        value = tuple(int(min(255, max(0, v))) for v in rgb)
        if value in self.items:
            self.items.remove(value)
        self.items.insert(0, value)
        del self.items[self.limit:]

    def clear(self) -> None:
        self.items.clear()


# ---------- 控件 ----------

class HueStrip(QWidget):
    """色相条：横向 0–360，可点可拖。"""

    changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hue = 0.0
        self._image = self._build()

    def _build(self) -> QImage:
        image = QImage(360, 1, QImage.Format.Format_RGB32)
        for x in range(360):
            image.setPixel(x, 0, QColor.fromHsv(x, 255, 255).rgb())
        return image

    def set_hue(self, hue: float):
        self.hue = max(0.0, min(359.0, hue))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawImage(QRect(0, 0, self.width(), self.height()), self._image)
        p.setPen(QPen(QColor("#0d1220"), 2))
        x = self.hue / 359.0 * (self.width() - 1)
        p.drawEllipse(QPoint(int(x), self.height() // 2), 7, 7)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(QPoint(int(x), self.height() // 2), 5, 5)

    def _set_from_pos(self, x: int):
        ratio = max(0.0, min(1.0, x / max(1, self.width() - 1)))
        self.set_hue(round(ratio * 359))
        self.changed.emit(self.hue)

    def mousePressEvent(self, event):
        self._set_from_pos(int(event.position().x()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_pos(int(event.position().x()))


class GradientSlider(QWidget):
    """一维滑块：背景由回调给出（用于饱和度/明度）。"""

    changed = Signal(float)

    def __init__(self, gradient, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.value = 1.0
        self._gradient = gradient          # (value01) -> QImage(宽度1)
        self._image = None

    def refresh(self):
        self._image = self._gradient(self.value)
        self.update()

    def set_value(self, value: float):
        self.value = max(0.0, min(1.0, value))
        self._image = self._gradient(self.value)
        self.update()

    def paintEvent(self, event):
        if self._image is None:
            self._image = self._gradient(self.value)
        p = QPainter(self)
        p.drawImage(QRect(0, 0, self.width(), self.height()), self._image)
        p.setPen(QPen(QColor("#0d1220"), 2))
        x = self.value * (self.width() - 1)
        p.drawEllipse(QPoint(int(x), self.height() // 2), 7, 7)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(QPoint(int(x), self.height() // 2), 5, 5)

    def _set_from_pos(self, x: int):
        self.set_value(x / max(1, self.width() - 1))
        self.changed.emit(self.value)

    def mousePressEvent(self, event):
        self._set_from_pos(int(event.position().x()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_pos(int(event.position().x()))


class SVSquare(QWidget):
    """饱和度（横）× 明度（纵）方块，颜色随当前色相变化。"""

    changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(150, 108)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.hue = 0.0
        self.saturation = 1.0
        self.value = 1.0
        self._image = None
        self._image_size = (0, 0)

    def set_hsv(self, hue: float, saturation: float, value: float):
        if abs(hue - self.hue) > 0.5 or self._image is None:
            self._image = None
        self.hue, self.saturation, self.value = hue, saturation, value
        self.update()

    def _ensure_image(self, width: int, height: int):
        if self._image is not None and self._image_size == (width, height):
            return
        image = QImage(width, height, QImage.Format.Format_RGB32)
        pure = np.array(hsv_to_rgb(self.hue, 1, 1))
        saturation = np.linspace(0, 1, width)[None, :, None]
        value = np.linspace(1, 0, height)[:, None, None]
        pixels = np.ascontiguousarray(np.rint((255 * (1 - saturation) + pure * saturation) * value), dtype=np.uint8)
        self._image = QImage(pixels.data, width, height, pixels.strides[0], QImage.Format.Format_RGB888).copy()
        self._image_size = (width, height)

    def paintEvent(self, event):
        width = max(1, self.width() - 2)
        height = max(1, self.height() - 2)
        self._ensure_image(width, height)
        p = QPainter(self)
        p.drawImage(QRect(1, 1, width, height), self._image)
        p.setPen(QPen(QColor("#34435c"), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        cx = 1 + int(self.saturation * (width - 1))
        cy = 1 + int((1 - self.value) * (height - 1))
        p.setPen(QPen(QColor("#0d1220"), 2))
        p.drawEllipse(QPoint(cx, cy), 7, 7)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(QPoint(cx, cy), 5, 5)

    def _set_from_pos(self, x: float, y: float):
        width = max(1, self.width() - 2)
        height = max(1, self.height() - 2)
        self.saturation = max(0.0, min(1.0, (x - 1) / max(1, width - 1)))
        self.value = 1.0 - max(0.0, min(1.0, (y - 1) / max(1, height - 1)))
        self.update()
        self.changed.emit(self.saturation, self.value)

    def mousePressEvent(self, event):
        self._set_from_pos(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_pos(event.position().x(), event.position().y())


class SwatchRow(QWidget):
    """一行颜色小方块（历史用色），点一下取色。"""

    picked = Signal(object)

    def __init__(self, columns: int = 9, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.colors: list[tuple[int, int, int]] = []
        self.setMinimumHeight(SWATCH * 2 + 6)

    def set_colors(self, colors):
        self.colors = list(colors)
        self.update()

    def _cell_at(self, pos: QPoint):
        size = SWATCH + 3
        column = pos.x() // size
        row = pos.y() // size
        if 0 <= column < self.columns:
            index = row * self.columns + column
            if 0 <= index < len(self.colors):
                return index
        return None

    def paintEvent(self, event):
        p = QPainter(self)
        for index, color in enumerate(self.colors):
            column = index % self.columns
            row = index // self.columns
            if (row + 1) * (SWATCH + 3) > self.height() + 3:
                break
            p.fillRect(QRect(column * (SWATCH + 3), row * (SWATCH + 3), SWATCH, SWATCH), QColor(*color))
            p.setPen(QPen(QColor("#2a354d"), 1))
            p.drawRect(column * (SWATCH + 3), row * (SWATCH + 3), SWATCH, SWATCH)

    def mousePressEvent(self, event):
        index = self._cell_at(event.position().toPoint())
        if index is not None:
            self.picked.emit(self.colors[index])


class ClassicGrid(QWidget):
    """经典色板网格。"""

    picked = Signal(object)

    def __init__(self, columns: int = 12, rows: int = 5, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows = rows
        self.colors = classic_swatches(columns, rows)
        self.selected_color = None
        self.setMinimumHeight(rows * 16)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(self.columns * 22, self.rows * 22)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 同一个整数边长用于绘制与点击，剩余宽度居中留白。
        self.setFixedHeight(self.cell_size() * self.rows)

    def cell_size(self):
        return max(1, self.width() // self.columns)

    def cell_rect(self, index):
        size = self.cell_size()
        left = (self.width() - self.columns * size) // 2
        return QRect(left + index % self.columns * size, index // self.columns * size, size, size)

    def set_color(self, rgb):
        self.selected_color = tuple(rgb)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        for index, color in enumerate(self.colors):
            rect = self.cell_rect(index)
            p.fillRect(rect, QColor(*color))
            if color == self.selected_color:
                p.setPen(QPen(QColor('#000000'), 3))
                p.drawRect(rect.adjusted(1, 1, -2, -2))
                p.setPen(QPen(QColor('#ffffff'), 1))
                p.drawRect(rect.adjusted(1, 1, -2, -2))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        for index, color in enumerate(self.colors):
            if self.cell_rect(index).contains(event.position().toPoint()):
                self.picked.emit(color)
                return


class ColorPanel(QWidget):
    """「颜色」面板：色盘 / 经典 / 值 三页，外带历史用色。"""

    color_changed = Signal(object)          # (r, g, b)
    color_committed = Signal(object)        # 用户确认过的颜色（写进历史）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = ColorHistory()
        self.rgb = (255, 255, 255)
        self.previous_rgb = self.rgb
        self._loading = False
        self._build()
        self.set_color((255, 255, 255))

    # ---- 界面 ----
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(QLabel("颜色"))
        head.addStretch()
        self.current_swatch = QLabel()
        self.current_swatch.setFixedSize(28, 28)
        self.previous_swatch = QPushButton()
        self.previous_swatch.clicked.connect(lambda: self.pick_color(self.previous_rgb))
        self.previous_swatch.setFixedSize(28, 28)
        head.addWidget(QLabel("当前"))
        head.addWidget(self.current_swatch)
        head.addWidget(QLabel("上次"))
        head.addWidget(self.previous_swatch)
        outer.addLayout(head)
        self.transparent_button = QPushButton('透明色（露出背景）')
        self.transparent_button.setToolTip('用画笔或填充将像素变透明；PNG和草稿保留透明层。')
        self.transparent_button.clicked.connect(lambda: self.pick_color((0, 0, 0, 0)))
        outer.addWidget(self.transparent_button)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #34435c; border-radius: 6px; background: #141b2b; }"
            "QTabBar::tab { background: #1b2437; color: #a4b1c8; padding: 4px 10px;"
            " border: 1px solid #34435c; border-bottom: none; border-top-left-radius: 6px;"
            " border-top-right-radius: 6px; }"
            "QTabBar::tab:selected { background: #2a354d; color: #edf2fc; }")
        outer.addWidget(self.tabs)

        # 色盘页
        disc = QWidget()
        disc_layout = QVBoxLayout(disc)
        disc_layout.setContentsMargins(4, 4, 4, 4)
        disc_layout.setSpacing(6)
        self.square = SVSquare()
        disc_layout.addWidget(self.square, 1)
        self.hue_strip = HueStrip()
        disc_layout.addWidget(self.hue_strip)
        self.sat_slider = GradientSlider(lambda value: self._sat_image(value))
        disc_layout.addWidget(self.sat_slider)
        self.val_slider = GradientSlider(lambda value: self._val_image(value))
        disc_layout.addWidget(self.val_slider)
        history_row = QHBoxLayout()
        history_row.addWidget(QLabel("历史"))
        history_row.addStretch()
        clear = QPushButton("清除")
        clear.setObjectName("small")
        clear.clicked.connect(self.clear_history)
        history_row.addWidget(clear)
        disc_layout.addLayout(history_row)
        self.history_row = SwatchRow()
        disc_layout.addWidget(self.history_row)
        self.tabs.addTab(disc, "色盘")

        # 经典页
        classic = QWidget()
        classic_layout = QVBoxLayout(classic)
        classic_layout.setContentsMargins(4, 4, 4, 4)
        self.grid = ClassicGrid()
        classic_layout.addWidget(self.grid)
        classic_layout.addStretch()
        self.tabs.addTab(classic, "经典")

        # 值页
        values = QWidget()
        values_layout = QVBoxLayout(values)
        values_layout.setContentsMargins(4, 4, 4, 4)
        values_layout.setSpacing(6)
        hex_row = QHBoxLayout()
        hex_row.addWidget(QLabel("颜色代码"))
        self.hex_input = QLineEdit()
        self.hex_input.setMaxLength(7)
        self.hex_input.editingFinished.connect(self._hex_entered)
        hex_row.addWidget(self.hex_input)
        values_layout.addLayout(hex_row)
        self.spins = {}
        for key, name in (("r", "红"), ("g", "绿"), ("b", "蓝")):
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.valueChanged.connect(self._spin_changed)
            row.addWidget(spin)
            values_layout.addLayout(row)
            self.spins[key] = spin
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("当前颜色"))
        preview_row.addStretch()
        self.value_preview = QLabel()
        self.value_preview.setFixedSize(56, 56)
        self.value_preview.setToolTip("当前HEX / RGB对应的颜色；修改数值时实时更新。")
        preview_row.addWidget(self.value_preview)
        values_layout.addLayout(preview_row)
        values_layout.addStretch()
        self.tabs.addTab(values, "颜色数值")

        self.square.changed.connect(self._square_changed)
        self.hue_strip.changed.connect(self._hue_changed)
        self.sat_slider.changed.connect(self._sat_changed)
        self.val_slider.changed.connect(self._val_changed)
        self.history_row.picked.connect(self.pick_color)
        self.grid.picked.connect(self.pick_color)

    def _sat_image(self, _value) -> QImage:
        hue, value = self.hue_strip.hue, self.square.value
        image = QImage(240, 1, QImage.Format.Format_RGB32)
        for x in range(240):
            image.setPixel(x, 0, QColor(*hsv_to_rgb(hue, x / 239, value)).rgb())
        return image

    def _val_image(self, _value) -> QImage:
        hue, saturation = self.hue_strip.hue, self.square.saturation
        image = QImage(240, 1, QImage.Format.Format_RGB32)
        for x in range(240):
            image.setPixel(x, 0, QColor(*hsv_to_rgb(hue, saturation, x / 239)).rgb())
        return image

    # ---- 颜色同步 ----
    def set_color(self, rgb, *, remember=False):
        value = tuple(int(min(255, max(0, v))) for v in rgb)
        self._loading = True
        if value != self.rgb:
            self.previous_rgb = self.rgb
        self.rgb = value
        hue, saturation, val = rgb_to_hsv(value)
        if saturation == 0:
            hue = self.hue_strip.hue
        if val == 0:
            saturation = self.square.saturation
        self.square.set_hsv(hue, saturation, val)
        self.hue_strip.set_hue(hue)
        self.sat_slider.set_value(saturation)
        self.val_slider.set_value(val)
        self.hex_input.setText('#%02X%02X%02X' % value[:3])
        self.spins["r"].setValue(value[0])
        self.spins["g"].setValue(value[1])
        self.spins["b"].setValue(value[2])
        self.current_swatch.setStyleSheet(
            f"background: {'rgba' if len(value)==4 else 'rgb'}{value}; border: 1px solid #34435c; border-radius: 4px;")
        self.previous_swatch.setStyleSheet(
            f"background: {'rgba' if len(self.previous_rgb)==4 else 'rgb'}{self.previous_rgb}; border: 1px solid #34435c; border-radius: 4px;")
        self.current_swatch.setText('透' if len(value)==4 and value[3]==0 else '')
        self.previous_swatch.setText('透' if len(self.previous_rgb)==4 and self.previous_rgb[3]==0 else '')
        self.current_swatch.setToolTip("当前绘画颜色：" + hex_text(value))
        self.previous_swatch.setToolTip("点击恢复上次颜色：" + hex_text(self.previous_rgb))
        self.value_preview.setStyleSheet(
            f"background: {'rgba' if len(value)==4 else 'rgb'}{value}; border: 1px solid #a4b1c8; border-radius: 5px;")
        self.value_preview.setText('透明' if len(value)==4 and value[3]==0 else '')
        self.value_preview.setToolTip(hex_text(value))
        self.grid.set_color(value)
        self._loading = False
        if remember:
            self.history.push(value)
            self.history_row.set_colors(self.history.items)

    def pick_color(self, rgb):
        """外部/历史/经典色板选色：直接成为当前色并记进历史。"""
        self.set_color(rgb, remember=True)
        self.color_changed.emit(self.rgb)
        self.color_committed.emit(self.rgb)

    def clear_history(self):
        self.history.clear()
        self.history_row.set_colors([])

    # ---- 控件回调 ----
    def _emit(self):
        if self._loading:
            return
        self.color_changed.emit(self.rgb)

    def _sync_from_hsv(self):
        hue = self.hue_strip.hue
        self.set_color(hsv_to_rgb(hue, self.square.saturation, self.square.value))

    def _square_changed(self, saturation, value):
        self.square.saturation, self.square.value = saturation, value
        self._sync_from_hsv()
        self._emit()

    def _hue_changed(self, hue):
        self.hue_strip.set_hue(hue)
        self.square.set_hsv(hue, self.square.saturation, self.square.value)
        self._sync_from_hsv()
        self._emit()

    def _sat_changed(self, value):
        self.square.saturation = value
        self._sync_from_hsv()
        self._emit()

    def _val_changed(self, value):
        self.square.value = value
        self._sync_from_hsv()
        self._emit()

    def _hex_entered(self):
        parsed = parse_hex(self.hex_input.text())
        if parsed is None:
            self.hex_input.setText(hex_text(self.rgb))
            return
        self.set_color(parsed, remember=True)
        self._emit()

    def _spin_changed(self, _value):
        if self._loading:
            return
        value = (self.spins["r"].value(), self.spins["g"].value(), self.spins["b"].value())
        self.set_color(value)
        self._emit()
