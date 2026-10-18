"""Qt 桌面界面：后台转换、像素预览、材料清单和结果导出。"""
from __future__ import annotations

import sys
import os
import tempfile
import threading
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QRectF, QPointF, QEvent
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QImage,
                          QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QDoubleSpinBox, QGridLayout,
    QDialog, QListWidget, QListWidgetItem, QSplitter, QColorDialog, QStackedWidget, QTabWidget)

from .image_io import SUPPORTED_EXT, detect_grid, load_image_rgb, load_image_pixels
from .interactive import parse_width
from .formats import ConversionCancelled, VERSION_DESCRIPTIONS, PREVIEW_DESCRIPTIONS
from .pixels import material_pixels, color_text, validate_schematic_size
from .draft_paths import draft_folder, open_folder, remember_draft, list_drafts
from .history import HistoryStore, load_record


STYLE = """
QWidget { color: #edf2fc; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 12px; }
QMainWindow, QDialog, QMessageBox { background: #101522; }
#root, #sidebar { background: transparent; }
QFrame#card { background: rgba(25, 33, 50, 238); border: 1px solid #34435c; border-radius: 14px; }
QLabel#eyebrow { color: #83afff; font-size: 10px; font-weight: 700; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#section { font-size: 15px; font-weight: 700; }
QLabel#muted { color: #a4b1c8; }
QLabel#chip { background: #293e61; color: #83afff; border-radius: 12px; padding: 5px 12px; }
QLabel#metric { font-size: 21px; font-weight: 700; }
QLabel#field { color: #c4cee1; font-size: 11px; }
QPushButton { background: #25334b; border: 1px solid #34435c; border-radius: 8px;
              padding: 8px 13px; color: #edf2fc; }
QPushButton:hover { background: #293e61; border-color: #3a5280; }
QPushButton:pressed { background: #293e61; }
QPushButton:disabled { color: #65748e; background: #1c2638; border-color: #1c2638; }
QPushButton#primary { background: #83afff; color: #101d38; font-size: 14px;
                      font-weight: 700; border: none; padding: 13px; }
QPushButton#primary:hover { background: #9dc0ff; }
QPushButton#primary:disabled { background: #293e61; color: #65748e; }
QPushButton#tab { background: transparent; border: none; padding: 7px 14px; color: #a4b1c8; }
QPushButton#tab:checked { background: #293e61; color: #83afff; }
QPushButton#small { padding: 5px 10px; font-size: 11px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #101827; border: 1px solid #34435c;
                               border-radius: 7px; padding: 8px; selection-background-color: #3a5280; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #83afff; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: #65748e; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox QAbstractItemView { background: #25334b; selection-background-color: #3a5280; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #34435c;
                       border-radius: 4px; background: #101827; }
QCheckBox::indicator:checked { background: #83afff; border: 1px solid #83afff; }
QProgressBar { background: #101827; border: none; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #83afff; border-radius: 3px; }
QTableWidget { background: transparent; border: none; gridline-color: #34435c;
               selection-background-color: #293e61; alternate-background-color: #192132; }
QHeaderView::section { background: #192132; color: #a4b1c8; border: none;
                       border-bottom: 1px solid #34435c; padding: 7px; font-size: 11px; }
QTableWidget::item { border-bottom: 1px solid #34435c; padding: 5px; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #34435c; }
QSplitter::handle:hover { background: #83afff; }
QScrollBar:vertical { background: #192132; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #34435c; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #25334b; color: #edf2fc; border: 1px solid #34435c; padding: 8px; }
"""


_background = None


def paint_background(painter, rect, opacity=.25):
    global _background
    if _background is None:
        assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets"
        _background = QPixmap(str(assets / "background.jpg"))
    if _background.isNull():
        return
    painter.save()
    painter.setOpacity(opacity)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    size = min(rect.width() * .85, rect.height() * .95)
    target = QRectF(rect.right() - size - 16, rect.top() + (rect.height() - size) / 2, size, size)
    painter.drawPixmap(target, _background, QRectF(_background.rect()))
    painter.restore()


class BackgroundSurface(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101522"))
        paint_background(painter, self.rect(), .28)


def label(text, role=None):
    widget = QLabel(text)
    if role:
        widget.setObjectName(role)
    return widget


def button(text, callback, role=None):
    widget = QPushButton(text)
    if role:
        widget.setObjectName(role)
    widget.clicked.connect(callback)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    return widget, layout


def to_pixmap(rgb):
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    image = QImage(rgb.data, w, h, rgb.strides[0], (QImage.Format.Format_RGBA8888 if rgb.shape[2] == 4 else QImage.Format.Format_RGB888)).copy()
    return QPixmap.fromImage(image)


class Worker(QThread):
    loaded = Signal(object)
    converted = Signal(object)
    failed = Signal(str)
    stopped = Signal()
    progress = Signal(int, str)
    restored = Signal(object)

    def __init__(self, path, options=None, parent=None, task="preview"):
        super().__init__(parent)
        self.path = path
        self.options = options
        self.task = task
        self.abort = threading.Event()

    def run(self):
        try:
            if self.task == "history":
                result = load_record(self.path)
                if self.abort.is_set():
                    raise ConversionCancelled()
                self.restored.emit(result)
            elif self.options is None:
                rgb = load_image_pixels(self.path)
                cols = detect_grid(rgb)
                if self.abort.is_set():
                    raise ConversionCancelled()
                self.loaded.emit((self.path, rgb, cols))
            else:
                from .pipeline import prepare_pixel_preview, generate_material_versions, export_preview
                operation = {'export': export_preview, 'materials': generate_material_versions}.get(self.task, prepare_pixel_preview)
                result = operation(self.path, **self.options,
                    progress=self.progress.emit, cancelled=self.abort.is_set)
                self.converted.emit(result)
        except ConversionCancelled:
            self.stopped.emit()
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class PreviewCanvas(QWidget):
    """缩放、拖动画布、网格及逐格材料提示；绘图始终在 GUI 线程。"""
    hover = Signal(str)
    zoom_changed = Signal(float)
    choose = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.pixmap = None
        self.grid = self.palette = None
        self.cell_shape = None
        self.zoom = 1.0
        self.fitted = True
        self.offset = QPointF()
        self.drag_at = None
        self.show_grid = False
        self.smooth = True

    def set_image(self, rgb, grid=None, palette=None, cell_shape=None):
        self.pixels = rgb
        self.pixmap = to_pixmap(rgb)
        self.grid, self.palette = grid, palette
        self.cell_shape = grid.shape if grid is not None else cell_shape
        self.smooth = grid is None
        self.fit()

    def fit(self):
        self.fitted = True
        self.offset = QPointF()
        self.update()
        self.zoom_changed.emit(self.effective_zoom())

    def effective_zoom(self):
        if not self.pixmap:
            return 1.0
        if self.fitted:
            return min(max(1, self.width() - 50) / self.pixmap.width(),
                       max(1, self.height() - 40) / self.pixmap.height())
        return self.zoom

    def image_rect(self):
        z = self.effective_zoom()
        w, h = self.pixmap.width() * z, self.pixmap.height() * z
        return QRectF((self.width() - w) / 2 + self.offset.x(),
                      (self.height() - h) / 2 + self.offset.y(), w, h)

    def set_zoom(self, value):
        self.zoom = max(0.02, min(32.0, value))
        self.fitted = False
        self.update()
        self.zoom_changed.emit(self.zoom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.zoom_changed.emit(self.effective_zoom())

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101522"))
        if not self.pixmap:
            self._empty_scene(p)
            return
        paint_background(p, self.rect(), .16)
        rect = self.image_rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.smooth)
        p.drawPixmap(rect, self.pixmap, QRectF(self.pixmap.rect()))
        if self.show_grid and self.cell_shape is not None:
            h, w = self.cell_shape
            cell = rect.width() / w
            if cell >= 6:
                # 深色底线加浅色细线，亮色和暗色材料上均可辨认。
                # 只绘制视口内网格，放大后仍保持轻量。
                for x in range(max(0, int(-rect.x() / cell)), min(w, int((self.width() - rect.x()) / cell)) + 1):
                    sx = rect.x() + x * cell
                    self._grid_line(p, QPointF(sx, rect.top()), QPointF(sx, rect.bottom()))
                for y in range(max(0, int(-rect.y() / cell)), min(h, int((self.height() - rect.y()) / cell)) + 1):
                    sy = rect.y() + y * cell
                    self._grid_line(p, QPointF(rect.left(), sy), QPointF(rect.right(), sy))

    @staticmethod
    def _grid_line(painter, start, end):
        painter.setPen(QPen(QColor(0, 0, 0, 120), 3))
        painter.drawLine(start, end)
        painter.setPen(QPen(QColor(235, 250, 240, 180), 1))
        painter.drawLine(start, end)

    def grid_status(self):
        if self.cell_shape is None:
            return "当前图片无色块网格"
        if not self.show_grid:
            return ""
        cell = self.image_rect().width() / self.cell_shape[1]
        return "请放大以显示网格" if cell < 6 else "网格已显示"

    def _empty_scene(self, painter):
        paint_background(painter, self.rect(), .85)
        painter.fillRect(self.rect(), QColor(16, 21, 34, 90))
        painter.setPen(QColor("#edf2fc"))
        painter.setFont(QFont("Microsoft YaHei UI", 18, QFont.Weight.Bold))
        painter.drawText(QRectF(0, self.height() - 110, self.width(), 36), Qt.AlignmentFlag.AlignCenter, "选择图片，开始预览")
        painter.setPen(QColor("#a4b1c8"))
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(QRectF(0, self.height() - 68, self.width(), 26), Qt.AlignmentFlag.AlignCenter, "拖入图片，或点击选择图片")

    def wheelEvent(self, event):
        if not self.pixmap:
            return
        before = self.image_rect()
        point = event.position()
        relative = QPointF((point.x() - before.x()) / before.width(),
                           (point.y() - before.y()) / before.height())
        self.set_zoom(self.effective_zoom() * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
        after = self.image_rect()
        self.offset += point - QPointF(after.x() + relative.x() * after.width(),
                                      after.y() + relative.y() * after.height())
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.pixmap:
                self.drag_at = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                self.choose.emit()

    def mouseMoveEvent(self, event):
        if self.drag_at is not None:
            self.offset += event.position() - self.drag_at
            self.drag_at = event.position()
            self.update()
        if self.pixmap and self.grid is not None:
            rect = self.image_rect()
            point = event.position()
            if rect.contains(point):
                x = int((point.x() - rect.x()) / rect.width() * self.grid.shape[1])
                y = int((point.y() - rect.y()) / rect.height() * self.grid.shape[0])
                if 0 <= y < self.grid.shape[0] and 0 <= x < self.grid.shape[1]:
                    idx = int(self.grid[y, x])
                    if idx == -1:
                        self.hover.emit(f"坐标 ({x}, {y}) · 透明（不放材料）")
                        return
                    cand = self.palette.candidates[idx]
                    bid = cand.block.get("wall_id", cand.block.get("tile_id"))
                    kind = "墙" if "wall_id" in cand.block else "方块"
                    self.hover.emit(f"第 {x + 1} 列 · 第 {y + 1} 行    {self.palette.describe(idx)}    {kind} ID {bid}")
                    return
        if self.pixmap and self.cell_shape is not None and self.grid is None:
            rect = self.image_rect()
            point = event.position()
            if rect.contains(point):
                h, w = self.cell_shape
                x = int((point.x()-rect.x()) / rect.width() * w)
                y = int((point.y()-rect.y()) / rect.height() * h)
                if 0 <= x < w and 0 <= y < h:
                    ph, pw = self.pixels.shape[:2]
                    color = self.pixels[min(ph-1, y*ph//h), min(pw-1, x*pw//w)]
                    self.hover.emit(f"坐标 ({x}, {y}) · 第{x+1}列 / 第{y+1}行 · {color_text(color)}")
                    return
        self.hover.emit(self.default_hint())

    def mouseReleaseEvent(self, event):
        self.drag_at = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.pixmap else Qt.CursorShape.PointingHandCursor)

    def default_hint(self):
        text = "滚轮缩放 · 按住鼠标拖动画布"
        if self.grid is not None and self.palette is not None:
            text += " · 移到像素上查看材料"
        return text

    def leaveEvent(self, event):
        self.hover.emit(self.default_hint())


class ExportDialog(QDialog):
    def __init__(self, schematic=True, versions=("fine", "wall", "map"), parent=None, *, available=("fine", "wall", "map")):
        super().__init__(parent)
        self.setWindowTitle("选择要保存的版本")
        self.setMinimumSize(420, 320)
        self.setSizeGripEnabled(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(label("保存当前预览", "section"))
        note = label("保存时直接使用当前预览，不重新转换图片。\n混合版、背景墙版用于主画面观看；地图版用于游戏地图观看。\n地图版可用允许的物块和背景墙，采用地图代表色匹配；地图版图纸不加夜明涂层。", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.choices = {}
        for key, text in (("fine", "混合版"), ("wall", "背景墙版"), ("map", "地图版")):
            choice = QCheckBox(text)
            choice.setChecked(key in versions and key in available)
            choice.setEnabled(key in available)
            if key not in available:
                choice.setToolTip("这份旧作品没有该版本的数据；重新预览原图后可生成。")
            choice.toggled.connect(self.update_selection)
            self.choices[key] = choice
            layout.addWidget(choice)
            description = label(VERSION_DESCRIPTIONS[key], "muted")
            description.setWordWrap(True)
            layout.addWidget(description)
        self.schematic = QCheckBox("同时保存所选版本的游戏建筑图纸（TEdit）")
        self.schematic.setChecked(schematic)
        layout.addWidget(self.schematic)
        row = QHBoxLayout()
        row.addWidget(button("返回预览", self.reject))
        self.save_button = button("保存所选版本", self.accept, "primary")
        row.addWidget(self.save_button)
        layout.addLayout(row)
        self.update_selection()

    def selected_versions(self):
        return tuple(key for key, choice in self.choices.items() if choice.isChecked())

    def update_selection(self, *args):
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(bool(self.selected_versions()))


class CanvasSizeDialog(QDialog):
    """新建像素画布：选尺寸和底色。"""

    PRESETS = ((16, 16), (32, 32), (48, 48), (64, 64), (128, 128))
    BACKGROUNDS = (("透明", (0, 0, 0, 0)), ("白色", (255, 255, 255)), ("黑色", (0, 0, 0)), ("中灰", (128, 128, 128)))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建像素画布")
        self.setMinimumWidth(360)
        self.custom = (255, 255, 255)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)
        outer.addWidget(label("画布尺寸（像素格）", "field"))
        row = QHBoxLayout()
        self.width_input = QSpinBox()
        self.width_input.setRange(1, 2147483647)
        self.width_input.setValue(64)
        self.width_input.setSuffix(" 宽")
        self.height_input = QSpinBox()
        self.height_input.setRange(1, 2147483647)
        self.height_input.setValue(64)
        self.height_input.setSuffix(" 高")
        row.addWidget(self.width_input)
        row.addWidget(self.height_input)
        outer.addLayout(row)
        presets = QHBoxLayout()
        presets.addWidget(label("常用", "field"))
        for w, h in self.PRESETS:
            presets.addWidget(button(f"{w}×{h}", lambda _=False, a=w, b=h: self.set_size(a, b), "small"))
        presets.addStretch()
        outer.addLayout(presets)
        outer.addWidget(label("底色", "field"))
        colors = QHBoxLayout()
        self.background = QComboBox()
        for name, _rgb in self.BACKGROUNDS:
            self.background.addItem(name)
        self.background.addItem("自定义…")
        self.background.setCurrentIndex(1)  # 白色仍为默认，透明底色由用户选择。
        self.background.currentIndexChanged.connect(self._background_changed)
        colors.addWidget(self.background, 1)
        self.color_button = button("选颜色…", self.choose_background, "small")
        colors.addWidget(self.color_button)
        outer.addLayout(colors)
        self.hint = label("画布建好后可自由绘制，确认当前像素画后再生成三种材料版本。", "muted")
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(button("取消", self.reject, "small"))
        footer.addWidget(button("创建", self.accept, "primary"))
        outer.addLayout(footer)

    def set_size(self, width, height):
        self.width_input.setValue(width)
        self.height_input.setValue(height)

    def _background_changed(self, index):
        if index < len(self.BACKGROUNDS):
            self.custom = self.BACKGROUNDS[index][1]

    def choose_background(self):
        color = QColorDialog.getColor(QColor(*self.custom), self, "选择底色")
        if color.isValid():
            self.custom = (color.red(), color.green(), color.blue())
            self.background.setCurrentIndex(len(self.BACKGROUNDS))   # 切到“自定义”
            self.color_button.setStyleSheet(f"background: rgb{self.custom};")

    def size_values(self):
        return self.width_input.value(), self.height_input.value()

    def background_rgb(self):
        return self.custom


class HistoryDialog(QDialog):
    def __init__(self, store, output_root, parent=None, draft_base=None):
        super().__init__(parent)
        self.setWindowTitle("历史记录 / 草稿")
        self.resize(760, 520)
        self.setMinimumSize(560, 360)
        self.setSizeGripEnabled(True)
        self.store, self.output_root = store, output_root
        self.selected_directory = None
        self.selected_draft = None
        self.draft_base = Path(draft_base) if draft_base is not None else store.path.parent
        self.deleted_directories = []
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane {background:#101522;border:1px solid #34435c;border-radius:8px;} "
            "QTabBar::tab {background:#192132;color:#a4b1c8;padding:10px 18px;border:1px solid #34435c;} "
            "QTabBar::tab:selected {background:#293e61;color:#edf2fc;} "
            "QTabWidget > QWidget > QWidget {background:#101522;}")
        outer.addWidget(self.tabs)
        works = QWidget()
        self.tabs.addTab(works, "生成的作品")
        layout = QVBoxLayout(works)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(label("已经生成并保存的作品", "section"))
        note = label("双击记录直接查看。也可以导入旧版的“输出”文件夹或单个作品文件夹。", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        from PySide6.QtCore import QSize
        self.list.setIconSize(QSize(72, 64))
        self.list.setStyleSheet("QListWidget {background:#192132;border:1px solid #34435c;border-radius:8px;} QListWidget::item {padding:10px;} QListWidget::item:selected {background:#293e61;}")
        self.list.itemDoubleClicked.connect(self.open_selected)
        self.list.currentItemChanged.connect(lambda *_: self.open_button.setEnabled(self.list.currentItem() is not None))
        layout.addWidget(self.list, 1)
        self.empty_note = label("暂无作品记录。保存作品或成功导入世界后会显示在这里；草稿请切换到“像素画草稿”页。", "muted")
        self.empty_note.setWordWrap(True)
        layout.addWidget(self.empty_note)
        delete_row = QHBoxLayout()
        self.delete_button = button("删除选中记录及文件…", self.delete_selected)
        self.clear_button = button("清空全部记录及文件…", self.clear_all)
        delete_row.addWidget(self.delete_button)
        delete_row.addWidget(self.clear_button)
        delete_row.addStretch()
        layout.addLayout(delete_row)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        row = QHBoxLayout()
        row.addWidget(button("导入以前的结果…", self.import_folder))
        row.addWidget(button("刷新", self.refresh))
        row.addStretch()
        row.addWidget(button("关闭", self.reject))
        self.open_button = button("打开选中记录", self.open_selected, "primary")
        row.addWidget(self.open_button)
        layout.addLayout(row)
        drafts = QWidget()
        self.tabs.addTab(drafts, "像素画草稿")
        draft_layout = QVBoxLayout(drafts)
        draft_note = label("保存了一半的画在这里。双击草稿继续编辑，或导入其他位置的 .tpdraft 文件。", "muted")
        draft_note.setWordWrap(True)
        draft_layout.addWidget(draft_note)
        self.draft_list = QListWidget()
        self.draft_list.setStyleSheet(self.list.styleSheet())
        self.draft_list.itemDoubleClicked.connect(self.open_selected_draft)
        draft_layout.addWidget(self.draft_list, 1)
        self.draft_empty_note = label("没有找到草稿。可点击“导入草稿文件…”选择以前保存的文件。", "muted")
        self.draft_empty_note.setWordWrap(True)
        draft_layout.addWidget(self.draft_empty_note)
        draft_row = QHBoxLayout()
        self.import_draft_button = button("导入草稿文件…", self.import_draft)
        draft_row.addWidget(self.import_draft_button)
        draft_row.addWidget(button("刷新", self.refresh_drafts))
        draft_row.addStretch()
        draft_row.addWidget(button("关闭", self.reject))
        self.open_draft_button = button("打开草稿继续画", self.open_selected_draft, "primary")
        self.draft_list.currentItemChanged.connect(lambda current, old: self.open_draft_button.setEnabled(current is not None))
        draft_row.addWidget(self.open_draft_button)
        draft_layout.addLayout(draft_row)
        self.refresh()
        self.refresh_drafts()

    def refresh_drafts(self):
        self.draft_list.clear()
        try:
            paths = list_drafts(self.draft_base)
        except OSError as exc:
            QMessageBox.warning(self, "无法读取草稿目录", str(exc))
            paths = []
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.draft_list.addItem(item)
        self.draft_empty_note.setVisible(not paths)
        self.open_draft_button.setEnabled(bool(paths))
        if paths:
            self.draft_list.setCurrentRow(0)

    def import_draft(self):
        try:
            folder = open_folder(self.draft_base)
        except OSError as exc:
            QMessageBox.warning(self, "无法读取草稿目录", str(exc))
            return
        filename, _ = QFileDialog.getOpenFileName(self, "选择像素画草稿", str(folder), "像素画草稿 (*.tpdraft)")
        if filename:
            self.selected_draft = Path(filename)
            self.accept()

    def open_selected_draft(self, *args):
        item = self.draft_list.currentItem()
        if item:
            self.selected_draft = Path(item.data(Qt.ItemDataRole.UserRole))
            self.accept()

    def refresh(self):
        self.list.clear()
        for entry in self.store.entries(self.output_root):
            item = QListWidgetItem(entry["title"])
            item.setData(Qt.ItemDataRole.UserRole, str(entry["directory"]))
            item.setToolTip("\n".join(filter(None, (entry.get("world_import_summary"), str(entry["directory"])))))
            if entry.get("thumbnail_rgb") is not None:
                item.setIcon(QIcon(to_pixmap(entry["thumbnail_rgb"])))
            elif entry["thumbnail"]:
                pixmap = QPixmap(str(entry["thumbnail"])).scaled(72, 64,
                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
                item.setIcon(QIcon(pixmap))
            self.list.addItem(item)
        self.empty_note.setVisible(self.list.count() == 0)
        self.open_button.setEnabled(self.list.count() > 0)
        self.clear_button.setEnabled(self.list.count() > 0)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._selection_changed()

    def _selection_changed(self):
        self.delete_button.setEnabled(bool(self.list.selectedItems()))

    def delete_selected(self):
        self._delete_items(self.list.selectedItems())

    def clear_all(self):
        self._delete_items([self.list.item(i) for i in range(self.list.count())])

    def _delete_items(self, items):
        if not items:
            return
        directories = [Path(item.data(Qt.ItemDataRole.UserRole)) for item in items]
        try:
            plans = [self.store.deletion_plan(path) for path in directories]
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "无法确认删除范围", str(exc))
            return
        count = sum(len(plan["files"]) for plan in plans)
        message = QMessageBox(self)
        message.setWindowTitle("确认删除作品")
        message.setIcon(QMessageBox.Icon.Warning)
        message.setText(f"删除 {len(plans)} 条记录及其 {count} 个生成文件？")
        message.setInformativeText("将删除作品图纸和历史数据（旧版还包括预览和清单）。此操作无法撤销。\n原始图片、其他文件和子文件夹会保留。展开详细信息可查看完整文件路径。")
        details = []
        for plan in plans:
            details.append(str(plan["directory"]))
            details.extend("  " + str(path) for path in plan["files"])
        message.setDetailedText("\n".join(details))
        confirm = message.addButton("删除记录和文件", QMessageBox.ButtonRole.DestructiveRole)
        cancel = message.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(cancel)
        message.setEscapeButton(cancel)
        message.exec()
        if message.clickedButton() is not confirm:
            return
        deleted, errors = self.store.delete_records(directories, confirmed_plans=plans)
        self.deleted_directories.extend(deleted)
        self.refresh()
        if errors:
            QMessageBox.warning(self, "部分内容未删除", "\n".join(errors))

    def import_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择以前的输出文件夹或作品文件夹", self.output_root)
        if not path:
            return
        entries = self.store.entries(path)
        root = Path(path).resolve()
        imported = [entry for entry in entries if entry["directory"] == root or entry["directory"].parent == root]
        if not imported:
            QMessageBox.information(self, "没有找到结果", "请选择含有“作品记录.json”和“作品数据.npz”的作品文件夹，或包含这些作品的输出目录。\n.tpdraft 草稿请切换到“像素画草稿”页导入。")
            return
        try:
            for entry in reversed(imported):
                self.store.remember(entry["directory"])
        except OSError as exc:
            QMessageBox.warning(self, "历史索引无法保存", str(exc))
        self.output_root = path
        self.refresh()

    def open_selected(self, *args):
        item = self.list.currentItem()
        if item:
            self.selected_directory = Path(item.data(Qt.ItemDataRole.UserRole))
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("泰拉瑞拉像素工坊")
        self.resize(1440, 960)
        self.setMinimumSize(900, 620)
        self.setAcceptDrops(True)
        self.source_path = self.source_rgb = self.result = None
        self.source_size = None
        self.worker = None
        self.busy = False
        self.closing = False
        self.mode = 0
        self.editors = []
        self.editor_color_state = None
        self._canvas_files = []
        self.generated_options = None
        self.preview_dirty = False
        self.operation = "preview"
        self.save_schematics = True
        self.history = HistoryStore(self.base_dir() / "历史记录.json", self.base_dir() / "输出")
        self.controls = []
        self._build()
        self._update_estimate()
        QApplication.instance().installEventFilter(self)

    def _build(self):
        root = BackgroundSurface()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(18)
        header = QHBoxLayout()
        branding = QVBoxLayout()
        branding.setSpacing(3)
        branding.addWidget(label("泰拉瑞拉像素工坊", "title"))
        header.addLayout(branding)
        header.addStretch()
        self.settings_toggle = button("设置面板", lambda: None, "small")
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(True)
        self.settings_toggle.toggled.connect(lambda checked: self.sidebar_panel.setVisible(checked))
        header.addWidget(self.settings_toggle)
        self.materials_toggle = button("材料面板", lambda: None, "small")
        self.materials_toggle.setCheckable(True)
        self.materials_toggle.setChecked(False)
        self.materials_toggle.toggled.connect(self.toggle_materials_panel)
        header.addWidget(self.materials_toggle)
        self.focus_button = button("专注预览", self.focus_preview, "small")
        header.addWidget(self.focus_button)
        self.fullscreen_button = button("全屏", self.toggle_fullscreen, "small")
        self.fullscreen_button.setShortcut("F11")
        header.addWidget(self.fullscreen_button)
        self.history_button = button("历史记录 / 草稿", self.show_history)
        self.history_button.setToolTip("查看已保存或导入世界的作品，或切换到草稿页继续绘画。")
        header.addWidget(self.history_button)
        self.controls.append(self.history_button)
        outer.addLayout(header)
        self.workspace_pages = QStackedWidget()
        outer.addWidget(self.workspace_pages, 1)
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_pages.addWidget(self.body_splitter)
        self.body_splitter.setHandleWidth(7)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(270)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(14)
        scroll = QScrollArea()
        self.settings_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setWidget(sidebar)
        scroll.setMinimumWidth(280)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_panel = QWidget()
        side_column = QVBoxLayout(self.sidebar_panel)
        side_column.setContentsMargins(0, 0, 0, 0)
        side_column.setSpacing(14)
        side_column.addWidget(scroll, 1)
        self.body_splitter.addWidget(self.sidebar_panel)

        source_card, layout = card()
        layout.addWidget(label("01  /  选择图片", "section"))
        self.file_name = label("还没有选择图片", "muted")
        self.file_name.setWordWrap(True)
        layout.addWidget(self.file_name)
        self.select_button = button("＋  选择图片", self.choose_image)
        layout.addWidget(self.select_button)
        self.new_canvas_button = button("＋  新建像素画布", self.new_canvas, "small")
        self.new_canvas_button.setToolTip("从零手绘像素画，确认当前画布后生成三种材料版本。")
        layout.addWidget(self.new_canvas_button)
        self.open_draft_button = button("打开草稿 / 图片继续画", self.open_draft, "small")
        self.open_draft_button.setToolTip("打开保存的像素草稿，或按原始像素尺寸导入PNG等图片继续编辑。")
        layout.addWidget(self.open_draft_button)
        self.controls.append(self.open_draft_button)
        self.source_info = label("支持 PNG、JPG、WebP 等\n也可以直接拖入图片", "muted")
        self.source_info.setWordWrap(True)
        layout.addWidget(self.source_info)
        side.addWidget(source_card)
        self.controls.append(self.select_button)
        self.controls.append(self.new_canvas_button)

        settings_card, layout = card()
        layout.addWidget(label("02  /  转换设置", "section"))
        layout.addWidget(label("图片横向分成几格", "field"))
        self.width_input = QLineEdit("128")
        self.width_input.setPlaceholderText("例如 128，或 /2")
        self.width_input.setToolTip("数字表示像素列数；/2 表示原图宽度的一半")
        self.width_input.textChanged.connect(self._settings_changed)
        layout.addWidget(self.width_input)
        presets = QHBoxLayout()
        for value in (64, 128, 256):
            b = button(str(value), lambda checked=False, v=value: self.width_input.setText(str(v)), "small")
            presets.addWidget(b)
            self.controls.append(b)
        self.recommend = button("推荐", self.use_recommendation, "small")
        presets.addWidget(self.recommend)
        self.controls.append(self.recommend)
        layout.addLayout(presets)
        self.grid_note = label("宽度越大，细节与材料数量越多", "muted")
        self.grid_note.setWordWrap(True)
        layout.addWidget(self.grid_note)
        row = QHBoxLayout()
        scale_column = QVBoxLayout()
        scale_column.addWidget(label("每个色块的大小", "field"))
        self.scale_input = QComboBox()
        self.scale_input.addItems(["1 × 1", "2 × 2", "3 × 3", "4 × 4"])
        self.scale_input.setToolTip("1×1：一个色块用一个方块。2×2：长宽翻倍，用量变为4倍；不会增加图片细节。")
        self.scale_input.currentIndexChanged.connect(self._settings_changed)
        scale_column.addWidget(self.scale_input)
        row.addLayout(scale_column)
        layout.addLayout(row)
        self.estimate = label("选择图片后显示成品尺寸", "muted")
        self.estimate.setWordWrap(True)
        layout.addWidget(self.estimate)
        self.coating_input = QCheckBox("加夜明涂层，减少环境光影响")
        self.coating_input.setToolTip("用于混合版、背景墙版：不照亮周围。物块仍受游戏虚化变暗规则影响，预览已按虚化颜色匹配。关闭后还会受环境光影响。地图版图纸不添加夜明涂层；导入世界时以导入窗口的选项为准。")
        self.coating_input.setChecked(True)
        self.coating_input.stateChanged.connect(self._settings_changed)
        layout.addWidget(self.coating_input)
        note = label("物块可见且可穿过；预览已计入虚化变暗", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        side.addWidget(settings_card)
        self.controls.extend([self.width_input, self.scale_input, self.coating_input])

        algorithm_card, layout = card()
        layout.addWidget(label("像素化与颜色", "section"))
        layout.addWidget(label("图片缩小方式", "field"))
        self.sampling_input = QComboBox()
        for text, value in (("自动选择（推荐）", "auto"), ("保留原有像素块", "nearest"),
                            ("平滑缩小图片", "area"), ("缩小后突出轮廓", "edge")):
            self.sampling_input.addItem(text, value)
        self.sampling_input.setToolTip("自动识别已有像素画，尽量保留色块；照片和插画平滑缩小后适度突出轮廓。")
        self.sampling_input.currentIndexChanged.connect(self._settings_changed)
        layout.addWidget(self.sampling_input)
        self.sampling_note = label("", "muted")
        self.sampling_note.setWordWrap(True)
        sampling_notes = {
            "auto": "已有像素画尽量保留色块；照片和插画缩小后适度突出轮廓。",
            "nearest": "直接取原图颜色，不混合相邻像素；适合已有像素画。",
            "area": "合并附近颜色，减轻细纹闪烁；细小轮廓可能变柔和。",
            "edge": "缩小后加强明暗边缘；适合照片、插画，不能恢复已丢失的细节。",
        }
        self.sampling_input.currentIndexChanged.connect(
            lambda _: self.sampling_note.setText(sampling_notes[self.sampling_input.currentData()]))
        self.sampling_note.setText(sampling_notes["auto"])
        layout.addWidget(self.sampling_note)
        row = QHBoxLayout()
        for title, attr in (("简化图片颜色", "color_input"), ("交错材料混色", "dither_input")):
            column = QVBoxLayout()
            column.addWidget(label(title, "field"))
            widget = QComboBox()
            if attr == "color_input":
                for value in (0, 8, 16, 32, 64, 128, 256):
                    widget.addItem("不限" if value == 0 else f"{value} 色", value)
                widget.setToolTip("先把图片减少到所选颜色数，色块更统一；不是实际用到的材料种数。不限则保留原图颜色。")
            else:
                for text, value in (("关闭（纯色块）", "none"), ("规则点阵", "bayer"), ("柔和过渡", "floyd")):
                    widget.addItem(text, value)
                widget.setToolTip("仅用于混合版、背景墙版。规则点阵按规律交错材料；柔和过渡分散颜色误差。地图版按地图代表色匹配，不使用交错混色。")
            setattr(self, attr, widget)
            widget.currentIndexChanged.connect(self._settings_changed)
            column.addWidget(widget)
            row.addLayout(column)
            self.controls.append(widget)
        layout.addLayout(row)
        note = label("交错混色仅用于混合版、背景墙版；地图版按地图代表色匹配", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(label("合并近似材料", "field"))
        self.merge_input = QComboBox()
        for text, value in (("关闭（保留全部材料组合）", 0), ("轻微（推荐）", 1.5),
                            ("适中（进一步减少材料）", 3), ("较强（可能损失细节）", 5)):
            self.merge_input.addItem(text, value)
        self.merge_input.setCurrentIndex(1)
        self.merge_input.currentIndexChanged.connect(self._settings_changed)
        layout.addWidget(self.merge_input)
        self.controls.append(self.merge_input)
        note = label("生成三版本时，把颜色极近的材料组合统一，优先保留用量多的材料。"
                     "不改变像素画；混合版和背景墙版还会限制纹理差异。调整后需重新确认生成。", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.merge_result_note = label("", "muted")
        self.merge_result_note.setWordWrap(True)
        self.merge_result_note.hide()
        layout.addWidget(self.merge_result_note)
        self.advanced_toggle = QCheckBox("更多调整：轮廓、颜色和混色程度")
        layout.addWidget(self.advanced_toggle)
        advanced = QWidget()
        fields = QGridLayout(advanced)
        fields.setContentsMargins(0, 0, 0, 0)
        for i, (title, attr, low, high, default, explanation) in enumerate((
            ("轮廓清晰程度", "detail_input", 0, 1, 0.4, "越大边缘越明显；仅在突出轮廓时生效"),
            ("明暗差别", "contrast_input", 0, 2, 1, "1保持原样；越大，亮处与暗处差别越大"),
            ("颜色鲜艳程度", "saturation_input", 0, 2, 1, "1保持原样；0变灰；大于1更鲜艳"),
            ("画面提亮程度", "gamma_input", 0.2, 3, 1, "1保持原样；大于1提亮；小于1变暗"),
            ("交错混色程度", "strength_input", 0, 1, 0.75, "0不混色；越大交错越多；需先开启混色"))):
            column = QVBoxLayout()
            column.addWidget(label(title, "field"))
            widget = QDoubleSpinBox()
            widget.setRange(low, high)
            widget.setSingleStep(0.05)
            widget.setDecimals(2)
            widget.setValue(default)
            widget.setToolTip(explanation)
            widget.valueChanged.connect(self._settings_changed)
            setattr(self, attr, widget)
            column.addWidget(widget)
            note = label(explanation, "muted")
            note.setWordWrap(True)
            column.addWidget(note)
            fields.addLayout(column, i // 2, i % 2)
            self.controls.append(widget)
        advanced.hide()
        self.advanced_toggle.toggled.connect(advanced.setVisible)
        layout.addWidget(advanced)
        side.addWidget(algorithm_card)
        self.controls.extend([self.sampling_input, self.advanced_toggle])

        export_card, layout = card()
        layout.addWidget(label("03  /  预览与保存", "section"))
        self.output_input = QLineEdit(str(self.base_dir() / "输出"))
        self.output_input.setToolTip("每次生成单独保存，不会覆盖以前的结果")
        self.output_input.textChanged.connect(self._export_settings_changed)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_input, 1)
        self.output_button = button("…", self.choose_output)
        self.output_button.setFixedWidth(36)
        output_row.addWidget(self.output_button)
        layout.addLayout(output_row)
        self.generate_button = button("生成像素画  →", self.generate, "primary")
        self.generate_button.setEnabled(False)
        layout.addWidget(self.generate_button)
        self.confirm_button = button("确认像素画并生成三版本", self.confirm_pixels, "primary")
        self.confirm_button.setEnabled(False)
        self.confirm_button.setToolTip("使用当前像素画生成混合版、背景墙版和地图版，不再次缩小或调色。")
        layout.addWidget(self.confirm_button)
        self.export_button = button("保存TEdit文件", self.choose_export)
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("预览满意后选择要保存的版本；保存时直接使用当前结果。")
        layout.addWidget(self.export_button)
        self.world_button = button("导入到世界 .wld…", self.show_world_import)
        self.world_button.setEnabled(False)
        self.world_button.setToolTip("把当前材料结果放到世界的指定位置，直接保存或另存；成功后自动保存作品历史记录。")
        layout.addWidget(self.world_button)
        self.stage_label = label("请选择图片", "muted")
        self.stage_label.setWordWrap(True)
        layout.addWidget(self.stage_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.cancel_button = button("取消处理", self.cancel, "small")
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        side_column.addWidget(export_card)
        self.controls.extend([self.output_input, self.output_button])
        side.addStretch()

        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setHandleWidth(7)
        self.body_splitter.addWidget(self.workspace_splitter)
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        self.body_splitter.setSizes([310, 1090])
        preview_card, preview = card()
        tabs_row = QHBoxLayout()
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for i, title in ((0, "原图"), (4, "像素画"), (1, "混合版"), (3, "背景墙版"), (5, "地图版")):
            tab = QPushButton(title)
            tab.setObjectName("tab")
            tab.setCheckable(True)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.setEnabled(i == 0)
            self.tab_group.addButton(tab, i)
            tabs_row.addWidget(tab)
        self.tab_group.button(0).setChecked(True)
        self.tab_group.idClicked.connect(self.set_mode)
        tabs_row.addStretch()
        self.preview_state = label("等待图片", "muted")
        tabs_row.addWidget(self.preview_state)
        preview.addLayout(tabs_row)
        self.preview_description = label(PREVIEW_DESCRIPTIONS[0], "muted")
        self.preview_description.setWordWrap(True)
        self.preview_description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        preview.addWidget(self.preview_description)
        self.png_actions = QWidget()
        png_row = QHBoxLayout(self.png_actions)
        png_row.setContentsMargins(0, 0, 0, 0)
        png_row.addStretch()
        self.png_button = button("导出像素画 PNG", self.export_pixel_png, "small")
        self.png_button.setToolTip("导出像素画；可选择保留网格，不包含界面背景。")
        png_row.addWidget(self.png_button)
        self.edit_button = button("编辑像素画", self.open_editor, "small")
        self.edit_button.setToolTip("在当前窗口逐格修改这一版：像素画色库不限，"
                                   "混合版、背景墙版使用贴图色；地图版使用地图色。")
        png_row.addWidget(self.edit_button)
        self.png_actions.hide()
        preview.addWidget(self.png_actions)
        self.canvas = PreviewCanvas()
        self.canvas.choose.connect(self.choose_image)
        preview.addWidget(self.canvas, 1)
        toolbar = QHBoxLayout()
        self.preview_hint = label("滚轮缩放 · 按住鼠标拖动画布", "muted")
        self.preview_hint.setMinimumWidth(10)
        self.preview_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.preview_hint.setFixedHeight(24)
        toolbar.addWidget(self.preview_hint, 1)
        self.canvas.hover.connect(self._hover)
        self.zoom_label = label("适应画布", "muted")
        self.zoom_label.setFixedWidth(64)
        toolbar.addWidget(self.zoom_label)
        self.canvas.zoom_changed.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))
        toolbar.addWidget(button("适应", self.canvas.fit, "small"))
        toolbar.addWidget(button("1:1", lambda: self.canvas.set_zoom(1), "small"))
        self.grid_toggle = QCheckBox("色块网格")
        self.grid_toggle.setEnabled(False)
        self.grid_toggle.setToolTip("显示像素色块边界，方便逐格查看材料；每个色块为2×2时，一格对应游戏里的4个方块。只影响查看，不影响图片或图纸。")
        self.grid_toggle.toggled.connect(self.toggle_grid)
        toolbar.addWidget(self.grid_toggle)
        self.canvas.zoom_changed.connect(self.update_grid_status)
        preview.addLayout(toolbar)
        self.workspace_splitter.addWidget(preview_card)
        self.preview_card = preview_card
        self.details_panel = QWidget()
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(0, 8, 0, 0)
        details_layout.setSpacing(10)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.metrics = []
        for title in ("成品尺寸 / 方块", "总材料数量", "材料种类 / 当前方案"):
            widget, layout = card()
            layout.setContentsMargins(16, 11, 16, 11)
            layout.setSpacing(3)
            value = label("—", "metric")
            self.metrics.append(value)
            layout.addWidget(value)
            layout.addWidget(label(title, "muted"))
            stats_row.addWidget(widget)
        details_layout.addLayout(stats_row)

        material_card, materials = card()
        material_card.setMinimumHeight(135)
        material_header = QHBoxLayout()
        self.material_title = label("材料清单", "section")
        material_header.addWidget(self.material_title)
        material_header.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索材料 / 喷漆")
        self.search.setFixedWidth(160)
        self.search.textChanged.connect(self.filter_materials)
        material_header.addWidget(self.search)
        self.folder_button = button("打开文件夹 ↗", self.open_folder, "small")
        self.folder_button.setEnabled(False)
        material_header.addWidget(self.folder_button)
        materials.addLayout(material_header)
        from .material_picker import MaterialTable
        self.table = MaterialTable(0, 3)
        self.table.setHorizontalHeaderLabels(["方块 / 墙", "喷漆", "数量"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.material_empty = label("生成后，在这里查看每种方块、喷漆和所需数量。", "muted")
        self.material_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        materials.addWidget(self.material_empty, 1)
        materials.addWidget(self.table, 1)
        self.table.hide()
        details_layout.addWidget(material_card, 1)
        self.workspace_splitter.addWidget(self.details_panel)
        self.workspace_splitter.setStretchFactor(0, 4)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([700, 230])
        self.details_panel.hide()
        footer = QHBoxLayout()
        self.footer = label("颜色基准：虚化物块 / 背景墙 + 夜明涂层", "muted")
        self.footer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.footer.setFixedHeight(24)
        footer.addWidget(self.footer, 1)
        from . import __version__
        self.version_label = label(f"v{__version__}", "muted")
        footer.addWidget(self.version_label)
        self.author_label = label("byWYW雨", "muted")
        footer.addWidget(self.author_label)
        outer.addLayout(footer)

    @staticmethod
    def base_dir():
        return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]

    def _hover(self, text):
        self.preview_hint.setToolTip(text)
        metrics = self.preview_hint.fontMetrics()
        self.preview_hint.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, self.preview_hint.width()))

    def choose_image(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择要搭建的图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
        if path:
            self.load_source(path)

    def load_source(self, path):
        if self.busy or self.editors:
            return
        path = Path(path)
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXT:
            QMessageBox.warning(self, "无法打开图片", "请选择 PNG、JPG、WebP 等支持的图片文件。")
            return
        self._set_busy(True)
        self.stage_label.setText("正在读取图片…")
        self.progress_bar.setRange(0, 0)
        self.worker = Worker(path, parent=self)
        self.worker.loaded.connect(self._source_loaded)
        self._connect_worker()
        self.worker.start()

    def _source_loaded(self, data):
        self.source_path, self.source_rgb, self.grid_cols = data
        self.result = None
        self.preview_dirty = False
        self.generated_options = None
        self.mode = 0
        self.png_actions.hide()
        self.tab_group.button(0).setChecked(True)
        for i in (1, 3, 4, 5):
            self.tab_group.button(i).setEnabled(False)
        self.file_name.setText(self.source_path.name)
        self.file_name.setToolTip(str(self.source_path))
        h, w = self.source_rgb.shape[:2]
        self.source_size = (w, h)
        self.source_info.setText(f"{w:,} × {h:,} 像素  ·  {self.source_path.suffix[1:].upper()}")
        self.recommended_width = self.grid_cols or min(w, 256)
        self.width_input.setText(str(self.recommended_width))
        self.grid_note.setText(f"识别到 {self.grid_cols} 列像素网格，建议一格一方块" if self.grid_cols
                               else f"建议宽度 {self.recommended_width}，也支持 /2、/4")
        self.canvas.set_image(self.source_rgb)
        self.preview_state.setText("原图预览")
        self.table.setRowCount(0)
        self.table.hide()
        self.material_empty.show()
        self.material_empty.setText("先生成像素画，确认后再生成三种材料版本。")
        self.preview_description.setText(PREVIEW_DESCRIPTIONS[0])
        self.metrics[2].setText("—")
        self.folder_button.setEnabled(False)
        self.stage_label.setText("图片已加载")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._update_estimate()

    def use_recommendation(self):
        if self.source_path:
            self.width_input.setText(str(self.recommended_width))

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出文件夹", self.output_input.text())
        if path:
            self.output_input.setText(path)

    def _options(self):
        if self.source_path is None:
            return None
        w, h = self.source_size
        width = parse_width(self.width_input.text(), w)
        if width is None:
            raise ValueError("目标宽度请填写正整数，或使用 /2、/4 等比例。")
        height = max(1, round(h * width / w))
        scale = self.scale_input.currentIndex() + 1
        output = self.output_input.text().strip()
        return dict(width=width, scale=scale,
                    coating=self.coating_input.isChecked(), out_dir=output,
                    sampling=self.sampling_input.currentData(), color_limit=self.color_input.currentData(),
                    dither=self.dither_input.currentData(), detail=self.detail_input.value(),
                    contrast=self.contrast_input.value(), saturation=self.saturation_input.value(),
                    gamma=self.gamma_input.value(), dither_strength=self.strength_input.value(),
                    material_merge=self.merge_input.currentData())

    def _settings_changed(self, *args):
        self._update_estimate()
        if self.result and not self.busy:
            if self.sender() in (self.scale_input, self.coating_input, self.dither_input,
                                 self.strength_input, self.merge_input):
                self.result.processing = dict(self.result.processing,
                                              materials_stale=self.result.grid is not None,
                                              pixels_confirmed=False)
                self._show_result(prefer_pixel=True)
                self._update_png_action()
                self.stage_label.setText("材料设置已修改，确认当前像素画后重新生成三版本")
                return
            self.preview_dirty = True
            self.export_button.setEnabled(False)
            self._update_png_action()
            self.stage_label.setText("像素画设置已修改，请重新生成像素画后确认")
            self.preview_state.setText("上次预览 · 设置已修改")

    def _export_settings_changed(self, *args):
        # 输出位置不影响已经算好的像素效果。
        pass

    def _update_estimate(self):
        try:
            options = self._options()
            if options is None:
                self.generate_button.setEnabled(False)
                return
            w, h = self.source_size
            gw, scale = options["width"], options["scale"]
            gh = max(1, round(h * gw / w))
            self.estimate.setText(f"像素网格 {gw:,} × {gh:,}\n成品 {gw * scale:,} × {gh * scale:,} 方块 · {gw * gh * scale * scale:,} 格")
            if self.result is None:
                self.metrics[0].setText(f"{gw * scale:,} × {gh * scale:,}")
                self.metrics[1].setText(f"{gw * gh * scale * scale:,}")
            self.generate_button.setEnabled(not self.busy and self.source_path is not None)
        except ValueError as exc:
            self.estimate.setText(str(exc))
            self.generate_button.setEnabled(False)

    def _set_busy(self, busy):
        self.busy = busy
        self.progress_bar.setVisible(busy)
        self._update_png_action()
        for control in self.controls:
            control.setEnabled(not busy)
        for control in (self.settings_toggle, self.materials_toggle, self.focus_button,
                        self.history_button):
            control.setEnabled(not busy and not self.editors)
        self.generate_button.setEnabled(not busy and self.source_path is not None)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.generate_button.setText("正在处理…" if busy else "生成像素画  →")
        self.export_button.setEnabled(not busy and self.result is not None and
                                      self.result.grid is not None and not self.preview_dirty and
                                      not self.result.processing.get('materials_stale'))
        if not busy:
            self._update_estimate()

    def generate(self):
        if self.busy or self.source_path is None:
            return
        try:
            options = self._options()
        except ValueError as exc:
            QMessageBox.warning(self, "请检查转换设置", str(exc))
            return
        if options is None:
            return
        options.pop("out_dir")
        self.operation = "preview"
        self.pending_options = options
        self._set_busy(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("正在生成像素画…")
        self.worker = Worker(self.source_path, options, self)
        self.worker.converted.connect(self._converted)
        self.worker.progress.connect(self._progress)
        self._connect_worker()
        self.worker.start()

    def _connect_worker(self):
        self.worker.failed.connect(self._failed)
        self.worker.stopped.connect(self._cancelled)
        self.worker.finished.connect(self._finished)

    def confirm_pixels(self):
        if self.busy or self.editors or self.preview_dirty or self.result is None:
            return False
        return self._start_material_generation(self.result)

    def _start_material_generation(self, result):
        if self.busy or result.processed_rgb is None:
            return False
        if result.grid is not None:
            answer = QMessageBox.question(self, '重新生成三版本？',
                '将根据当前像素画重新生成三种材料方案，替换这三版当前的编辑结果。已保存的作品文件不受影响。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.result = result
        self.preview_dirty = False
        self.operation = 'materials'
        self._show_result(prefer_pixel=True)
        options = dict(scale=self.scale_input.currentIndex() + 1, coating=self.coating_input.isChecked(),
                       dither=self.dither_input.currentData(), dither_strength=self.strength_input.value(),
                       material_merge=self.merge_input.currentData())
        self._set_busy(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText('正在根据当前像素画生成三版本…')
        self.worker = Worker(result, options, self, task='materials')
        self.worker.converted.connect(self._converted)
        self.worker.progress.connect(self._progress)
        self._connect_worker()
        self.worker.start()
        return True

    def confirm_edited_pixels(self, result, pixels):
        """编辑器直接确认其当前画布，包括尚未点应用的笔画。"""
        if self.busy or self.result is not result:
            return False
        from dataclasses import replace
        pixels = np.array(pixels, dtype=np.uint8, copy=True)
        changed = not np.array_equal(result.processed_rgb, pixels)
        subject = replace(result, processed_rgb=pixels,
                          processing=dict(result.processing, pixels_confirmed=False,
                                          materials_stale=result.grid is not None and (changed or result.processing.get('materials_stale', False))))
        return self._start_material_generation(subject)

    def _progress(self, value, text):
        self.progress_bar.setValue(value)
        self.stage_label.setText(f"{text}  ·  {value}%")

    def _converted(self, result):
        self.result = result
        self.preview_dirty = False
        if self.operation == "preview":
            self.generated_options = self.pending_options.copy()
        self._show_result(prefer_pixel=self.operation == "preview")
        self.progress_bar.setValue(100)
        if self.operation == "export":
            try:
                self.history.remember(result.out_dir)
                self.stage_label.setText("保存完成，可从历史记录重新查看")
            except OSError:
                self.stage_label.setText("结果已保存；历史索引写入失败，可从历史记录导入文件夹")
        elif self.operation == "materials":
            self.stage_label.setText("三版本已生成，可分别编辑，再保存TEdit文件或导入世界")
        else:
            self.stage_label.setText("像素画已生成，可先编辑；满意后确认并生成三版本")

    def _show_result(self, prefer_pixel=False):
        result = self.result
        reports = result.processing.get('material_merge_report', {})
        summary = ['上次生成时材料组合数：'] if reports else []
        for version, title in (('fine', '混合版'), ('wall', '背景墙版'), ('map', '地图版')):
            if version in reports:
                report = reports[version]
                summary.append(f"{title} {report['before']} → {report['after']} 种")
        self.merge_result_note.setText('\n'.join(summary))
        self.merge_result_note.setVisible(bool(summary))
        self.tab_group.button(0).setEnabled(self.source_rgb is not None)
        for i, version, grid in ((1, "fine", result.grid), (3, "wall", result.grid_wall),
                                 (5, "map", result.grid_map)):
            self.tab_group.button(i).setEnabled(not result.processing.get('materials_stale') and
                                               (grid is not None or version in result.saved_images))
        self.tab_group.button(4).setEnabled(result.processed_rgb is not None)
        self.tab_group.button(5).setText('地图版')
        preferred = {"fine": 1, "wall": 3, "map": 5}.get(next(iter(result.versions), ''), 4)
        first = 4 if (prefer_pixel or result.grid is None or result.processing.get('materials_stale')) and result.processed_rgb is not None else preferred
        self.tab_group.button(first).setChecked(True)
        self.set_mode(first)
        self.folder_button.setEnabled(result.out_dir is not None and result.out_dir.is_dir())
        self.footer.setText(f"已保存到  {result.out_dir}" if result.out_dir else "当前为预览，尚未保存作品或图纸")
        self.footer.setToolTip(str(result.out_dir or "预览不会创建输出文件"))

    def choose_export(self):
        if self.busy or self.result is None or self.preview_dirty or self.result.grid is None or self.result.processing.get('materials_stale'):
            return
        available = tuple(v for v, grid in (("fine", self.result.grid), ("wall", self.result.grid_wall),
                                            ("map", self.result.grid_map)) if grid is not None)
        dialog = ExportDialog(self.save_schematics, self.result.versions, self, available=available)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.save_schematics = dialog.schematic.isChecked()
            self.save_current(dialog.selected_versions(), dialog.schematic.isChecked())

    def _update_png_action(self):
        self.png_actions.setVisible(self.mode in (1, 3, 4, 5))
        self.png_button.setVisible(self.mode == 4)
        editable = self.result is not None and not self.busy and not self.preview_dirty
        self.png_button.setEnabled(editable and self.mode == 4 and self.result.processed_rgb is not None)
        has_grid = self.result is not None and self.result.grid is not None and not self.result.processing.get('materials_stale')
        self.confirm_button.setEnabled(editable and not self.editors and self.result.processed_rgb is not None and
                                       (not has_grid or self.result.processing.get('materials_stale', False)))
        self.export_button.setEnabled(editable and has_grid and not self.editors)
        self.world_button.setEnabled(editable and has_grid and not self.editors)
        self.edit_button.setEnabled(editable and not self.editors and (self.result.processed_rgb is not None
                                                  if self.mode == 4 else has_grid))

    def show_world_import(self):
        if self.busy or self.editors or self.preview_dirty or self.result is None or self.result.grid is None or self.result.processing.get('materials_stale'):
            return
        from .world_dialog import WorldImportDialog
        version = {1: 'fine', 3: 'wall', 5: 'map'}.get(self.mode, 'fine')
        dialog = WorldImportDialog(self.result, version, self,
                                   output_root=self.output_input.text().strip() or self.history.default_root,
                                   history=self.history)
        dialog.saved.connect(self._world_saved)
        dialog.exec()

    def _world_saved(self, outcome):
        record = outcome['record']
        if record is not None:
            self.result.out_dir = record.out_dir
            self.result.processing = record.processing.copy()
            self.folder_button.setEnabled(True)
        self.stage_label.setText('世界已保存；作品记录保存失败' if outcome['history_error'] else
                                 '世界和作品记录已保存，可从“历史记录 / 草稿”重新打开')
        self.footer.setText(f'世界文件：{outcome["path"]}')
        self.footer.setToolTip(str(outcome['path']))

    def _track_editor(self, editor):
        self.editors.append(editor)
        editor.closed.connect(lambda: self._editor_closed(editor))
        self.workspace_pages.addWidget(editor)
        self.workspace_pages.setCurrentWidget(editor)
        for control in (self.settings_toggle, self.materials_toggle, self.focus_button, self.history_button):
            control.setEnabled(False)
        self.footer.setText(editor.windowTitle())
        QTimer.singleShot(0, editor.canvas.fit)
        self._update_png_action()

    def new_canvas(self):
        """新建一块空白画布，进入主窗口中的编辑工作区。"""
        if self.busy or self.editors:
            return
        dialog = CanvasSizeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.size_values()
        from .editor import EditCanvas
        from .editor_window import PixelEditorWindow

        try:
            canvas = EditCanvas.blank(width, height, dialog.background_rgb())
        except ValueError as exc:
            QMessageBox.warning(self, "画布尺寸不合适", str(exc))
            return
        editor = PixelEditorWindow(canvas=canvas, on_convert=self.convert_canvas, parent=self,
                                   color_state=self.editor_color_state)
        self._track_editor(editor)

    def open_draft(self, checked=False, filename=None):
        if self.busy or self.editors:
            return
        try:
            folder = open_folder(self.base_dir())
        except OSError as exc:
            QMessageBox.warning(self, "无法创建草稿文件夹", str(exc))
            return
        if filename is None:
            filename, _ = QFileDialog.getOpenFileName(self, "打开草稿或像素图片继续编辑", str(folder),
                "草稿与图片 (*.tpdraft *.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;像素草稿 (*.tpdraft);;图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
        if not filename:
            return
        from .drafts import load_draft, import_image, EXTENSION
        from .editor_window import PixelEditorWindow
        path = Path(filename)
        try:
            is_draft = path.suffix.lower() == EXTENSION
            draft = load_draft(path) if is_draft else import_image(path)
            editor = PixelEditorWindow(canvas=draft.canvas, draft=draft if is_draft else None,
                draft_path=path if is_draft else None, color_state=None if is_draft else self.editor_color_state,
                on_convert=self.convert_canvas, parent=self)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法打开草稿或图片", str(exc))
            return
        try:
            remember_draft(self.base_dir(), path) if is_draft else None
        except OSError:
            pass
        self._track_editor(editor)

    def convert_canvas(self, rgb):
        """确认新画布或导入草稿的当前像素，直接生成材料，不再次调色。"""
        if self.busy:
            return False
        pixels = np.asarray(rgb, dtype=np.uint8)
        if pixels.ndim != 3 or pixels.shape[2] not in (3, 4) or not all(pixels.shape[:2]):
            QMessageBox.warning(self, "画布格式不正确", "画布需为RGB或RGBA像素数组。")
            return False
        temporary = tempfile.TemporaryDirectory(prefix="pixel-canvas-")
        folder = Path(temporary.name)
        path = folder / "手绘像素画.png"
        try:
            Image.fromarray(pixels).save(path)
        except OSError as exc:
            temporary.cleanup()
            QMessageBox.warning(self, "无法准备画布", str(exc))
            return False
        self._canvas_files.append(temporary)
        self._source_loaded((path, pixels.copy(), None))
        # 先登记为当前图片，再读设置（设置校验依赖已载入的原图）。
        self.source_path = path
        self.source_rgb = pixels
        self.source_size = (pixels.shape[1], pixels.shape[0])
        self.grid_cols = None
        self.file_name.setText("手绘像素画")
        self.source_info.setText(f"{pixels.shape[1]} × {pixels.shape[0]} 像素 · 新建画布")
        # 手绘像素画默认一像素对一格：宽度按画布宽度、采样用“保留原有像素块”，避免被重采样。
        self.width_input.setText(str(pixels.shape[1]))
        nearest = self.sampling_input.findData("nearest")
        if nearest >= 0:
            self.sampling_input.setCurrentIndex(nearest)
        from .pipeline import Result
        result = Result(processed_rgb=pixels.copy(), width=pixels.shape[1], height=pixels.shape[0],
                        source_path=path, source_name=path.name, name='手绘像素画',
                        original_size=self.source_size, source_preview=pixels.copy(), versions=(),
                        processing=dict(width=pixels.shape[1], sampling='nearest', sampling_used='nearest',
                                        detail=0, contrast=1, saturation=1, gamma=1, color_limit=0))
        return self._start_material_generation(result)

    def open_editor(self):
        """在主窗口编辑当前这一版；材料版改完仍是可搭建的材料。"""
        if self.busy or self.preview_dirty or self.result is None or self.mode == 0 or self.editors:
            return
        target = {1: "fine", 3: "wall", 4: "pixel", 5: "map"}[self.mode]
        from .editor_window import PixelEditorWindow

        result = self.result
        editor = PixelEditorWindow(result, target, on_apply=lambda: self._editor_applied(result, target),
                                   on_convert=(lambda rgb: self.confirm_edited_pixels(result, rgb)) if target == "pixel" else None, parent=self,
                                   color_state=self.editor_color_state)
        self._track_editor(editor)

    def _editor_closed(self, editor):
        """退出编辑工作区，返回预览并释放编辑器。"""
        try:
            self.editor_color_state = editor.color_state()
            self.editors = [item for item in self.editors if item is not editor]
            self.workspace_pages.setCurrentWidget(self.body_splitter)
            self.workspace_pages.removeWidget(editor)
            editor.deleteLater()
            for control in (self.settings_toggle, self.materials_toggle, self.focus_button, self.history_button):
                control.setEnabled(not self.busy)
            self.footer.setText("正在转换…" if self.busy else "已返回预览，可继续查看、编辑或保存作品")
            self._update_png_action()
        except RuntimeError:
            pass

    def _editor_applied(self, result, target=None):
        """编辑窗口点了「应用」：刷新预览，保存时用编辑后的画面。"""
        if self.result is not result:
            return
        if target == 'pixel':
            self._show_result(prefer_pixel=True)
            self.stage_label.setText("已应用当前像素画；确认后生成三版本")
            self.footer.setText("像素画可保存草稿或导出PNG；确认后再生成材料方案")
        else:
            self.set_mode(self.mode)
            self.stage_label.setText("已应用本版编辑，其他两版不变；保存时使用当前结果")
            self.footer.setText("编辑尚未保存；请在主窗口保存TEdit文件为新作品")
        self._update_png_action()

    def export_pixel_png(self):
        if self.busy or self.result is None or self.preview_dirty or self.mode != 4:
            return
        from .png_export import export_png
        default = (self.result.out_dir or self.base_dir()) / f"{self.result.name or '像素画'}.png"
        try:
            path = export_png(self, self.result.processed_rgb, default)
            if path:
                self.stage_label.setText(f"PNG已导出：{path.name}")
        except (OSError, ValueError, MemoryError) as exc:
            QMessageBox.warning(self, "PNG导出失败", str(exc))

    def save_current(self, versions, make_schematic):
        if self.busy or self.result is None or self.preview_dirty or self.result.grid is None or self.result.processing.get('materials_stale'):
            return
        output = self.output_input.text().strip()
        if not output:
            QMessageBox.warning(self, "请选择保存位置", "请填写输出文件夹。")
            return
        if not versions:
            QMessageBox.warning(self, "请选择版本", "请至少勾选一个版本。")
            return
        if make_schematic:
            try:
                validate_schematic_size(self.result.width, self.result.height, self.result.scale)
            except ValueError as exc:
                QMessageBox.warning(self, "图纸尺寸超出限制", str(exc))
                return
        self.operation = "export"
        self._set_busy(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("正在保存当前预览…")
        self.worker = Worker(self.result, dict(out_dir=output, versions=versions,
            make_schematic=make_schematic), self, task="export")
        self.worker.converted.connect(self._converted)
        self.worker.progress.connect(self._progress)
        self._connect_worker()
        self.worker.start()

    def show_history(self):
        if self.busy or self.editors:
            return
        dialog = HistoryDialog(self.history, self.output_input.text(), self, draft_base=self.base_dir())
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if self.result and self.result.out_dir in dialog.deleted_directories:
            self.result.out_dir = None
            for attr in ("schematic", "schematic_wall", "schematic_map", "schematic_map_wall"):
                setattr(self.result, attr, None)
            self.folder_button.setEnabled(False)
            self.footer.setText("作品文件已删除；当前画面仍可查看")
            self.footer.setToolTip("")
            self.stage_label.setText("作品已删除；当前预览可重新保存" if self.result.grid is not None else "旧版作品已删除")
        if accepted and dialog.selected_draft:
            self.open_draft(filename=dialog.selected_draft)
        elif accepted and dialog.selected_directory:
            self.open_history(dialog.selected_directory)

    def open_history(self, directory):
        if self.busy or self.editors:
            return
        self.operation = "history"
        self._set_busy(True)
        self.progress_bar.setRange(0, 0)
        self.stage_label.setText("正在打开历史记录…")
        self.worker = Worker(directory, parent=self, task="history")
        self.worker.restored.connect(self._history_loaded)
        self._connect_worker()
        self.worker.start()

    def _history_loaded(self, result):
        self.result = result
        self.preview_dirty = False
        self.source_path = result.source_path if result.source_path and result.source_path.is_file() else None
        self.source_rgb = result.source_preview
        self.source_size = result.original_size if all(result.original_size) else (result.width, result.height)
        self.recommended_width = result.width
        self.file_name.setText(result.source_name)
        self.source_info.setText(f"历史记录 · {result.width} × {result.height} 格")
        self.grid_note.setText("直接读取已保存的结果，无需重新生成")
        values = result.processing
        for control in self.controls:
            control.blockSignals(True)
        self.width_input.setText(str(result.width))
        self.scale_input.setCurrentIndex(result.scale - 1)
        self.coating_input.setChecked(values.get("coating", True))
        for control, key, default in ((self.sampling_input, "sampling", "auto"),
                                     (self.color_input, "color_limit", 0),
                                     (self.dither_input, "dither", "none"),
                                     (self.merge_input, "material_merge", 0)):
            control.setCurrentIndex(max(0, control.findData(values.get(key, default))))
        for control, key, default in ((self.detail_input, "detail", .4),
            (self.contrast_input, "contrast", 1), (self.saturation_input, "saturation", 1),
            (self.gamma_input, "gamma", 1), (self.strength_input, "dither_strength", .75)):
            control.setValue(values.get(key, default))
        for control in self.controls:
            control.blockSignals(False)
        self.sampling_input.currentIndexChanged.emit(self.sampling_input.currentIndex())
        self.preview_dirty = False
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText("已打开历史记录；可查看或再次导出" if result.grid is not None else
                                 "已打开旧版结果；可查看已有图片")
        self._show_result()
        try:
            self.history.remember(result.out_dir)
        except OSError:
            self.footer.setText("已打开结果；历史索引无法写入，下次可再次导入此文件夹")

    def _finished(self):
        worker = self.worker
        self.worker = None
        self._set_busy(False)
        worker.deleteLater()
        if self.closing:
            self.close()

    def _failed(self, message):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("处理失败，请检查图片或保存位置")
        if not self.closing:
            QMessageBox.warning(self, "处理未完成", message)

    def _cancelled(self):
        self.progress_bar.setValue(0)
        self.stage_label.setText("已取消，保留上次完成的预览或结果")

    def cancel(self):
        if self.worker:
            self.worker.abort.set()
            self.cancel_button.setEnabled(False)
            self.stage_label.setText("正在停止，请稍候…")

    def set_mode(self, mode):
        if mode in (1, 3, 5) and self.result is not None and self.result.processing.get('materials_stale'):
            mode = 4
            self.tab_group.button(4).setChecked(True)
        self.mode = mode
        self.preview_description.setText(PREVIEW_DESCRIPTIONS[mode])
        self.preview_state.setToolTip("")
        self._update_png_action()
        self._hover("滚轮缩放 · 按住鼠标拖动画布")
        if mode == 0:
            if self.source_rgb is not None:
                self.canvas.set_image(self.source_rgb)
            self.update_grid_status()
            self.preview_state.setText("原图预览")
            self.table.hide()
            self.material_empty.show()
            self.material_empty.setText("切换到生成方案，即可查看材料清单。")
            self.metrics[2].setText("—")
            return
        if self.result is None:
            return
        result = self.result
        if result.grid is None and mode in (1, 3, 5):
            shape = (result.height, result.width) if result.processing.get("width") else None
            self.canvas.set_image(result.saved_images[{1: "fine", 3: "wall", 5: "map"}[mode]], cell_shape=shape)
            self.canvas.smooth = False
            self.update_grid_status()
            self.preview_state.setText("旧版已保存图片")
            self.table.hide()
            self.material_empty.show()
            self.material_empty.setText("旧版没有保存逐格材料数据；仅能查看原有图片。")
            self.metrics[0].setText(f"{result.width * result.scale:,} × {result.height * result.scale:,}")
            self.metrics[1].setText("—")
            self.metrics[2].setText("—")
            return
        if mode == 4:
            shape = (result.height, result.width) if result.grid is not None or result.processing.get("width") else None
            self.canvas.set_image(result.processed_rgb, cell_shape=shape)
            self.update_grid_status()
            self.canvas.smooth = False
            used = {"nearest": "保留原有像素块", "area": "平滑缩小图片", "edge": "缩小后突出轮廓"}.get(result.processing.get("sampling_used"), "已缩小图片")
            self.preview_state.setText(f"{used} · 材料匹配前")
            self.table.hide()
            self.material_empty.show()
            self.material_empty.setText("这是缩小和调色后的图片颜色，尚未替换为游戏材料，可与混合版、背景墙版对比。")
            self.metrics[2].setText(f"{len(np.unique(result.processed_rgb.reshape(-1, result.processed_rgb.shape[2]), axis=0))} 色")
            return
        grid, palette = {1: (result.grid, result.palette),
                         3: (result.grid_wall, result.palette_wall),
                         5: (result.grid_map, result.palette_map)}[mode]
        if grid is None or palette is None:
            return
        self.canvas.set_image(material_pixels(grid, palette), grid, palette)
        self.update_grid_status()
        self.preview_state.setText({1: "贴图色 · 方块 + 喷漆", 3: "贴图色 · 背景墙 + 喷漆",
                                   5: "地图色 · " + self.tab_group.button(5).text()}[mode])
        self.metrics[0].setText(f"{result.width * result.scale:,} × {result.height * result.scale:,}")
        self.metrics[1].setText(f"{np.count_nonzero(grid >= 0) * result.scale * result.scale:,}")
        values, counts = np.unique(grid[grid >= 0], return_counts=True)
        counter = Counter(dict(zip(map(int, values), map(int, counts))))
        bases = {("wall" if "wall_id" in palette.candidates[i].block else "tile",
                  palette.candidates[i].block.get("wall_id", palette.candidates[i].block.get("tile_id"))) for i in counter}
        self.metrics[2].setText(f"{len(bases)} 种")
        self.material_title.setText(f"材料清单  ·  {len(counter)} 种组合")
        self.table.dismiss_tooltip()
        self.table.setRowCount(len(counter))
        for row, (idx, count) in enumerate(counter.most_common()):
            cand = palette.candidates[idx]
            kind = "墙" if "wall_id" in cand.block else "物块"
            from .material_picker import material_tooltip
            note = material_tooltip(cand.block)
            item = QTableWidgetItem((kind + " · " if mode in (5,) else "") + cand.block["name_zh"] + (" ※" if note else ""))
            swatch = QPixmap(14, 14)
            swatch.fill(QColor(*cand.rgb))
            item.setIcon(QIcon(swatch))
            item.setToolTip(note)
            self.table.setItem(row, 0, item)
            paint = QTableWidgetItem(cand.paint["name_zh"])
            self.table.setItem(row, 1, paint)
            amount = QTableWidgetItem(f"{count * result.scale * result.scale:,}")
            amount.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            amount.setForeground(QColor("#83afff"))
            self.table.setItem(row, 2, amount)
            self.table.setRowHeight(row, 33)
        self.material_empty.hide()
        self.table.show()
        if not counter:
            self.table.hide()
            self.material_empty.setText("画面全部透明，无需放置材料。")
            self.material_empty.show()
        self.filter_materials()

    def filter_materials(self):
        query = self.search.text().strip().lower()
        for row in range(self.table.rowCount()):
            text = " ".join(self.table.item(row, col).text() for col in range(2))
            self.table.setRowHidden(row, query not in text.lower())

    def toggle_grid(self, enabled):
        self.canvas.show_grid = enabled
        self.canvas.update()
        self.update_grid_status()

    def update_grid_status(self, *args):
        available = self.canvas.cell_shape is not None
        self.grid_toggle.setEnabled(available)
        # 不增加动态文字，保持复选框位置固定，便于连续点击。

    def focus_preview(self):
        self.settings_toggle.setChecked(False)
        self.materials_toggle.setChecked(False)

    def toggle_materials_panel(self, visible):
        self.details_panel.setVisible(visible)
        if visible:
            height = max(500, self.workspace_splitter.height())
            self.workspace_splitter.setSizes([int(height * .7), int(height * .3)])

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setText("全屏")
        else:
            self.showFullScreen()
            self.fullscreen_button.setText("退出全屏")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            event.accept()
        else:
            super().keyPressEvent(event)

    def open_folder(self):
        if self.result and self.result.out_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.out_dir)))

    def _dropped_image(self, mime):
        if self.busy or self.editors or not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXT:
                    return path
        return None

    def eventFilter(self, watched, event):
        # 输入框、表格等子控件会吞掉文件拖放，统一在主窗口范围内接收。
        if (event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
                and isinstance(watched, QWidget) and watched.window() is self
                and QApplication.activeModalWidget() is None):
            path = self._dropped_image(event.mimeData())
            if path is not None:
                event.acceptProposedAction()
                if event.type() == QEvent.Type.Drop:
                    self.load_source(path)
                return True
            if event.mimeData().hasUrls():
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if self._dropped_image(event.mimeData()) is not None:
            event.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event):
        path = self._dropped_image(event.mimeData())
        if path is not None:
            self.load_source(path)
            event.acceptProposedAction()

    def closeEvent(self, event):
        for editor in list(self.editors):
            if not editor.close():
                event.ignore()
                return
        if self.worker and self.worker.isRunning():
            self.closing = True
            self.cancel()
            event.ignore()
        else:
            for temporary in self._canvas_files:
                temporary.cleanup()
            self._canvas_files.clear()
            event.accept()


def configure_app(app):
    from .localization import configure_chinese
    configure_chinese(app)
    # 离屏渲染及精简 Windows 环境未必能自动发现字体，显式注册系统中文字体。
    if sys.platform == "win32":
        font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            font = font_dir / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(STYLE)


def run_gui(image_path=None):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    configure_app(app)
    app.setApplicationName("TerrariaPixelArt")
    window = MainWindow()
    icon = Path(getattr(sys, "_MEIPASS", MainWindow.base_dir())) / "icon.ico"
    if icon.exists():
        window.setWindowIcon(QIcon(str(icon)))
    window.show()
    if image_path:
        QTimer.singleShot(0, lambda: window.load_source(image_path))
    return app.exec()
