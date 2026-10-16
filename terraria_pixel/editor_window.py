"""主窗口中的像素画编辑工作区（PySide6）。

- 像素画页：色库不限，可调任意颜色；
- 混合版 / 背景墙版：色库分别来自物块和背景墙的合集、以及仅背景墙（含喷漆），上色自动吸附到最近材料；
- 支持画笔、填充、取色、撤销/重做、重置、缩放拖动，材料版带色库搜索。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QShortcut, QKeySequence, QCursor, QPolygonF
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QSizePolicy, QSplitter, QVBoxLayout,
    QWidget, QCheckBox, QScrollArea, QTreeWidgetItem, QSpinBox)

from .color_panel import ColorPanel
from .desktop import STYLE, button, card, label, to_pixmap, paint_background
from .editor import TARGET_LABELS, TARGET_PIXEL, EditCanvas
from .drafts import Draft, EXTENSION, fingerprint, save_draft
from .pixels import color_text
from .draft_paths import draft_folder, remember_draft
from .cursors import drawing_cursor
from .material_picker import MaterialTree, material_tooltip

GRID_MIN_ZOOM = 6.0
MIN_ZOOM, MAX_ZOOM = 0.02, 48.0


def eyedropper_cursor():
    """滴管尖端是点击位置，白色描边在亮暗画面上都可见。"""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = QPolygonF([QPointF(3, 28), QPointF(6, 20), QPointF(19, 7),
                      QPointF(25, 13), QPointF(12, 26), QPointF(3, 28)])
    painter.setPen(QPen(QColor('#ffffff'), 3))
    painter.setBrush(QColor('#182235'))
    painter.drawPolygon(body)
    painter.setPen(QPen(QColor('#182235'), 1))
    painter.drawPolygon(body)
    painter.setPen(QPen(QColor('#ffffff'), 3))
    painter.drawLine(QPointF(15, 6), QPointF(26, 17))
    painter.setPen(QPen(QColor('#182235'), 1))
    painter.drawLine(QPointF(15, 6), QPointF(26, 17))
    painter.setPen(QPen(QColor('#ffffff'), 2))
    painter.setBrush(QColor('#182235'))
    painter.drawEllipse(QRectF(21, 1, 9, 9))
    painter.end()
    return QCursor(pixmap, 3, 28)


class EditorCanvas(QWidget):
    """可编辑画布：左键画、右键取色、中键或 Alt+左键拖动、滚轮缩放。"""

    changed = Signal()
    picked = Signal(str)
    hovered = Signal(str)
    stroke_finished = Signal()
    selection_changed = Signal(str)

    def __init__(self, canvas: EditCanvas):
        super().__init__()
        self.canvas = canvas
        self.setMinimumSize(360, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pixmap = None
        self.zoom = max(4.0, min(24.0, 600 / max(1, canvas.width)))
        self.offset = QPointF(0, 0)
        self.fitted = True
        self.show_grid = True
        self.selection = None
        self._selection_start = None
        self.tool = "brush"
        self.brush_size = 1
        self.color = (255, 255, 255)      # 像素画当前颜色
        self.index = canvas.index_at(0, 0) if canvas.is_material else 0
        self.color = canvas.color_at(0, 0)
        self._drag_from = None
        self._pan_from = None
        self._last_cell = None
        self._stroke_cell = None
        self.rebuild()
        self._picker_cursor = eyedropper_cursor()
        self._tool_cursors = {"picker": self._picker_cursor, "brush": drawing_cursor("brush"), "fill": drawing_cursor("fill")}
        self.set_tool(self.tool)

    def set_tool(self, name):
        self.tool = name
        self.setCursor(self._tool_cursors.get(name, Qt.CursorShape.CrossCursor))

    # ---------- 绘制 ----------

    def rebuild(self):
        self.pixmap = to_pixmap(self.canvas.rgb)
        self.update()

    def image_rect(self) -> QRectF:
        w = self.canvas.width * self.zoom
        h = self.canvas.height * self.zoom
        return QRectF((self.width() - w) / 2 + self.offset.x(),
                      (self.height() - h) / 2 + self.offset.y(), w, h)

    def cell_at(self, pos) -> tuple[int, int] | None:
        rect = self.image_rect()
        if not rect.contains(pos):
            return None
        x = int((pos.x() - rect.x()) / self.zoom)
        y = int((pos.y() - rect.y()) / self.zoom)
        if 0 <= x < self.canvas.width and 0 <= y < self.canvas.height:
            return x, y
        return None

    def fit(self):
        self.fitted = True
        self._fit_geometry()

    def _fit_geometry(self):
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, min((self.width() - 24) / max(1, self.canvas.width),
                                                     (self.height() - 24) / max(1, self.canvas.height))))
        self.offset = QPointF(0, 0)
        self.update()

    def set_zoom(self, value: float, anchor=None):
        old = self.image_rect()
        anchor = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        image_x = (anchor.x() - old.x()) / self.zoom
        image_y = (anchor.y() - old.y()) / self.zoom
        self.fitted = False
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, value))
        new = self.image_rect()
        self.offset += QPointF(anchor.x() - new.x() - image_x * self.zoom,
                               anchor.y() - new.y() - image_y * self.zoom)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitted:
            self._fit_geometry()

    def clear_selection(self):
        self.selection = None
        self._selection_start = None
        self.selection_changed.emit("")
        self.update()

    def _select_to(self, pos):
        rect = self.image_rect()
        x = min(self.canvas.width - 1, max(0, int((pos.x() - rect.x()) / self.zoom)))
        y = min(self.canvas.height - 1, max(0, int((pos.y() - rect.y()) / self.zoom)))
        sx, sy = self._selection_start
        self.selection = (min(sx, x), min(sy, y), max(sx, x), max(sy, y))
        x0, y0, x1, y1 = self.selection
        self.selection_changed.emit(f"选区 {x1-x0+1} × {y1-y0+1} 格 · 画笔和填充仅修改选区")
        self.update()

    def _inside_selection(self, cell):
        if self.selection is None:
            return True
        x0, y0, x1, y1 = self.selection
        return x0 <= cell[0] <= x1 and y0 <= cell[1] <= y1

    def set_grid(self, visible):
        self.show_grid = visible
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0b0f18"))
        paint_background(p, self.rect(), .18)
        if not self.pixmap:
            p.end()
            return
        rect = self.image_rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawPixmap(rect, self.pixmap, QRectF(0, 0, self.pixmap.width(), self.pixmap.height()))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        if self.show_grid and self.zoom >= GRID_MIN_ZOOM:
            pen = QPen(QColor(0, 0, 0, 75))
            pen.setWidth(1)
            p.setPen(pen)
            x0 = max(0, int(-rect.x() / self.zoom))
            x1 = min(self.canvas.width, int((self.width() - rect.x()) / self.zoom) + 1)
            y0 = max(0, int(-rect.y() / self.zoom))
            y1 = min(self.canvas.height, int((self.height() - rect.y()) / self.zoom) + 1)
            for x in range(x0, x1 + 1):
                gx = rect.x() + x * self.zoom
                p.drawLine(int(gx), int(rect.y()), int(gx), int(rect.bottom()))
                p.setPen(QPen(QColor(255, 255, 255, 55), 1))
                p.drawLine(int(gx) + 1, int(rect.y()), int(gx) + 1, int(rect.bottom()))
                p.setPen(pen)
            for y in range(y0, y1 + 1):
                gy = rect.y() + y * self.zoom
                p.drawLine(int(rect.x()), int(gy), int(rect.right()), int(gy))
                p.setPen(QPen(QColor(255, 255, 255, 55), 1))
                p.drawLine(int(rect.x()), int(gy) + 1, int(rect.right()), int(gy) + 1)
                p.setPen(pen)
        # 双色边界在纯白、纯黑及相近蓝色的画面上都能看清。
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#000000"), 3))
        p.drawRect(rect)
        p.setPen(QPen(QColor("#dce8ff"), 1))
        p.drawRect(rect)
        if self.selection is not None:
            x0, y0, x1, y1 = self.selection
            selected = QRectF(rect.x() + x0 * self.zoom, rect.y() + y0 * self.zoom,
                              (x1-x0+1) * self.zoom, (y1-y0+1) * self.zoom)
            p.setPen(QPen(QColor("#101522"), 3))
            p.drawRect(selected)
            p.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine))
            p.drawRect(selected)
        if self._last_cell is not None and self.zoom >= 3:
            x, y = self._last_cell
            size = self.brush_size if self.tool == 'brush' else 1
            left, top = x - (size - 1) // 2, y - (size - 1) // 2
            x0, y0 = max(0, left), max(0, top)
            x1, y1 = min(self.canvas.width, left + size), min(self.canvas.height, top + size)
            if self.selection is not None and self.tool == 'brush':
                sx0, sy0, sx1, sy1 = self.selection
                x0, y0 = max(x0, sx0), max(y0, sy0)
                x1, y1 = min(x1, sx1 + 1), min(y1, sy1 + 1)
            cell_rect = QRectF(rect.x() + x0 * self.zoom, rect.y() + y0 * self.zoom,
                               max(0, x1 - x0) * self.zoom, max(0, y1 - y0) * self.zoom)
            p.setPen(QPen(QColor("#000000"), 3))
            p.drawRect(cell_rect)
            p.setPen(QPen(QColor("#83afff"), 1))
            p.drawRect(cell_rect)
        p.end()

    # ---------- 交互 ----------

    def _to_cell(self, pos) -> tuple[int, int] | None:
        return self.cell_at(pos)

    def _paint(self, cell, *, pick_only=False):
        x, y = cell
        if pick_only or self.tool == "picker":
            self.color = self.canvas.color_at(x, y)
            self.picked_rgb = self.color
            index = self.canvas.index_at(x, y)
            if index is not None:
                self.index = index
                self.picked.emit(f"材料：{self.canvas.label_of(index)}")
            else:
                self.picked.emit(f"颜色：{self._hex(self.color)}")
            self.update()
            return
        if not self._inside_selection(cell):
            return
        if self.tool == "fill":
            changed = self.canvas.fill(x, y, rgb=self.color, index=self.index, bounds=self.selection)
        else:
            changed = self.canvas.brush(x, y, self.brush_size, rgb=self.color, index=self.index, bounds=self.selection)
        if changed:
            self.rebuild()
            self.changed.emit()

    @staticmethod
    def _hex(color) -> str:
        return color_text(color)

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        cell = self._to_cell(event.position())
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.fitted = False
            self._pan_from = event.position()
            return
        if cell is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._paint(cell, pick_only=True)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self.tool == "select":
                self._selection_start = cell
                self._select_to(event.position())
                return
            self._drag_from = event.position().toPoint()
            self._last_cell = cell
            self._stroke_cell = cell
            self.canvas.begin_stroke()
            self._paint(cell)

    def mouseMoveEvent(self, event):
        pos = event.position()
        cell = self._to_cell(pos)
        if self._pan_from is not None:
            delta = pos - self._pan_from
            self.offset += delta
            self._pan_from = pos
            self.update()
            return
        if self._selection_start is not None:
            self._select_to(pos)
            return
        if cell is None:
            self._stroke_cell = None
            self._last_cell = None
            self.hovered.emit("")
            self.update()
            return
        self._last_cell = cell
        self.hovered.emit(f"({cell[0]}, {cell[1]})  " + self.canvas.label_of(self.canvas.index_at(*cell))
                          if self.canvas.is_material else f"({cell[0]}, {cell[1]})  {self._hex(self.canvas.color_at(*cell))}")
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.tool == "brush" and self._stroke_cell is not None:
                x0, y0 = self._stroke_cell
                x1, y1 = cell
                steps = max(abs(x1 - x0), abs(y1 - y0))
                changed = 0
                for i in range(1, steps + 1):
                    x = round(x0 + (x1 - x0) * i / steps)
                    y = round(y0 + (y1 - y0) * i / steps)
                    if self._inside_selection((x, y)):
                        changed += self.canvas.brush(x, y, self.brush_size, rgb=self.color, index=self.index, bounds=self.selection)
                if changed:
                    self.rebuild()
                    self.changed.emit()
            else:
                self._paint(cell)
            self._stroke_cell = cell
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._selection_start is not None:
            self._select_to(event.position())
            self._selection_start = None
            return
        self.canvas.end_stroke()
        self._drag_from = None
        self._pan_from = None
        self._stroke_cell = None
        self.stroke_finished.emit()

    def leaveEvent(self, event):
        self._last_cell = None
        self.hovered.emit("")
        self.update()

    def wheelEvent(self, event):
        step = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.set_zoom(self.zoom * step, event.position())

    def keyPressEvent(self, event):
        super().keyPressEvent(event)


class PixelEditorWindow(QWidget):
    """可嵌入主窗口的编辑工作区。"""

    closed = Signal()

    TOOLS = (("brush", "画笔", "左键画，拖动连画（B）"),
             ("fill", "填充", "把相连的同色区域整块换掉（F）"),
             ("picker", "取色笔", "点一下吸走该格颜色／材料（I），右键随时可吸"),
             ("select", "框选", "拖动框选矩形区域（M），点“填满选区”统一填色；Esc取消选区"))

    def __init__(self, result=None, target: str = TARGET_PIXEL, on_apply=None,
                 on_convert=None, parent=None, canvas: EditCanvas | None = None,
                 color_state=None, draft=None, draft_path=None):
        super().__init__(parent)
        # QStackedWidget 会重设 parent；保留主窗口引用以找到便携程序的草稿目录。
        self.host_window = parent
        if canvas is None:
            if result is None:
                raise ValueError("要么给一份结果，要么给一块画布。")
            canvas = EditCanvas.from_result(result, target)
        self.result = result
        self.canvas_model = canvas
        self.target = canvas.target
        self.canvas_mode = result is None
        self.on_apply = on_apply
        self.on_convert = on_convert
        self.draft_path = Path(draft_path) if draft_path else None
        self._draft_checkpoint = fingerprint(canvas) if draft_path else None
        self.setWindowTitle(("新建像素画布" if self.canvas_mode else f"编辑像素画 · {TARGET_LABELS[self.target]}")
                            + f"（{canvas.width} × {canvas.height}）")
        if parent is None:
            self.resize(1120, 740)
        self.setStyleSheet(STYLE)
        self._build()
        if draft is not None:
            self.color_panel.history.items = list(draft.history)
            self.color_panel.history_row.set_colors(draft.history)
            self._panel_color_changed(draft.color)
            self.set_tool(draft.tool)
            self.canvas.selection = draft.selection
            if draft.selection:
                x0, y0, x1, y1 = draft.selection
                self._selection_changed(f"选区 {x1-x0+1} × {y1-y0+1} 格 · 画笔和填充仅修改选区")
        elif color_state is not None:
            self.color_panel.history.items = list(color_state['history'])
            self.color_panel.history_row.set_colors(color_state['history'])
            self._panel_color_changed(color_state['color'])
        self._sync_controls()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self._refresh_after_edit)
        self.canvas.stroke_finished.connect(self._finish_stroke)
        self.shortcuts = []
        for key, action in (("B", lambda: self.set_tool("brush")), ("F", lambda: self.set_tool("fill")),
                            ("I", lambda: self.set_tool("picker")), ("M", lambda: self.set_tool("select")),
                            ("Esc", self.canvas.clear_selection), ("Ctrl+S", self.save_draft), ("Ctrl+Z", self.undo),
                            ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(action)
            self.shortcuts.append(shortcut)

    # ---------- 界面 ----------

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        bar_card, bar = card()
        row = QHBoxLayout()
        row.setSpacing(8)
        bar.addLayout(row)
        row.addWidget(label("工具", "field"))
        for name, title, tip in self.TOOLS:
            btn = button(title, lambda _=False, n=name: self.set_tool(n), "small")
            btn.setCheckable(True)
            btn.setToolTip(tip)
            setattr(self, f"tool_{name}", btn)
            row.addWidget(btn)
        row.addWidget(label('画笔粗细', 'field'))
        self.brush_size_input = QSpinBox()
        self.brush_size_input.setRange(1, 64)
        self.brush_size_input.setValue(1)
        self.brush_size_input.setSuffix(' 格')
        self.brush_size_input.setFixedWidth(90)
        self.brush_size_input.setToolTip('方形画笔的边长，1格为原来的细画笔；仅影响画笔工具。')
        self.brush_size_input.valueChanged.connect(self._brush_size_changed)
        row.addWidget(self.brush_size_input)
        self.draft_button = button("保存草稿", self.save_draft, "small")
        self.draft_button.setToolTip("保存未完成的像素画，关闭后可用“打开草稿 / 图片”继续（Ctrl+S）。")
        self.screen_pick_button = button("屏幕取色", self.pick_screen, "small")
        self.screen_pick_button.setToolTip("选择取色笔后，可从其他窗口或桌面取色；Esc取消。")
        row.addWidget(self.screen_pick_button)
        row.addSpacing(12)
        row.addWidget(label("色库", "field"))
        self.palette_name = label("", "muted")
        row.addWidget(self.palette_name)
        row.addStretch()
        self.current_swatch = QLabel("  ")
        self.current_swatch.setFixedSize(26, 22)
        self.current_name = label("", "muted")
        self.current_name.setFixedWidth(120)
        self.current_name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.current_name.setToolTip("当前颜色或材料")
        row.addWidget(self.current_swatch)
        row.addWidget(self.current_name)
        self.snap_hint = label("", "muted")
        self.snap_hint.hide()
        outer.addWidget(bar_card)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)

        side_card, side = card()
        side.setSpacing(6)
        side.addWidget(label("色库搜索", "field"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索物体或油漆，展开后选色")
        self.search.textChanged.connect(self.filter_palette)
        side.addWidget(self.search)
        self.palette_list = MaterialTree()
        self.palette_list.setIconSize(QPixmap(16, 16).size())
        self.palette_list.setStyleSheet("QTreeWidget { background: #141b2b; color: #edf2fc;"
                                       " border: 1px solid #34435c; border-radius: 6px; }")
        self.palette_list.currentItemChanged.connect(self.palette_item_changed)
        side.addWidget(self.palette_list, 1)
        self.side_hint = label("先展开物体，再选择油漆颜色。※ 表示透光墙。", "muted")
        self.side_hint.setWordWrap(True)
        side.addWidget(self.side_hint)
        self.side_card = side_card
        side_card.setMinimumWidth(200)
        split.addWidget(side_card)

        view_card, view = card()
        view.setSpacing(8)
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        self.undo_btn = button("撤销", self.undo, "small")
        self.redo_btn = button("重做", self.redo, "small")
        self.reset_btn = button("重置", self.reset, "small")
        fit_btn = button("适应窗口", lambda: self.canvas.fit(), "small")
        for b in (self.undo_btn, self.redo_btn, self.reset_btn, fit_btn):
            tools_row.addWidget(b)
        self.grid_button = QCheckBox("格子边界")
        self.grid_button.setChecked(True)
        self.grid_button.toggled.connect(lambda checked: self.canvas.set_grid(checked))
        tools_row.addWidget(self.grid_button)
        self.clear_selection_button = button("取消选区", lambda: self.canvas.clear_selection(), "small")
        tools_row.addWidget(self.clear_selection_button)
        tools_row.addStretch()
        self.info = label("", "muted")
        self.info.setFixedWidth(180)
        self.info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        tools_row.addWidget(self.info)
        view.addLayout(tools_row)

        view_split = QSplitter(Qt.Orientation.Horizontal)
        self.view_splitter = view_split
        view_split.setChildrenCollapsible(False)
        self.canvas = EditorCanvas(self.canvas_model)
        self.canvas.changed.connect(self._canvas_changed)
        self.canvas.hovered.connect(lambda text: self._set_hint(self.hover_label, text))
        self.canvas.picked.connect(lambda text: self._set_hint(self.stage, text))
        self.canvas.picked.connect(self._picked_color)
        view_split.addWidget(self.canvas)
        right = QWidget()
        right.setObjectName("editorColors")
        right.setStyleSheet("#editorColors { background: #192132; }")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.color_panel = ColorPanel()
        self.color_panel.color_changed.connect(self._panel_color_changed)
        self.color_panel.color_committed.connect(lambda rgb: self.color_panel.history.push(self.current_swatch_color()))
        right_layout.addWidget(self.color_panel, 1)
        right_layout.addWidget(label("本图用色（点一下取色）", "field"))
        self.color_list = QListWidget()
        self.color_list.setIconSize(QPixmap(16, 16).size())
        self.color_list.setMaximumHeight(120)
        self.color_list.setStyleSheet("QListWidget { background: #141b2b; color: #edf2fc;"
                                      " border: 1px solid #34435c; border-radius: 6px; }")
        self.color_list.currentRowChanged.connect(self.color_row_changed)
        self.color_list.setToolTip("当前这一版用到的颜色，点一下切换成当前色。")
        right_layout.addWidget(self.color_list)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right)
        right_scroll.setMinimumWidth(220)
        right_scroll.setMaximumWidth(300)
        view_split.addWidget(right_scroll)
        view_split.setStretchFactor(0, 1)
        view_split.setStretchFactor(1, 0)
        view_split.setSizes([780, 250])
        view.addWidget(view_split, 1)

        footer = QHBoxLayout()
        self.hover_label = label("", "muted")
        self.stage = label("", "muted")
        for hint in (self.hover_label, self.stage):
            hint.setWordWrap(False)
            hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            hint.setFixedHeight(24)
            footer.addWidget(hint, 1)
        view.addLayout(footer)

        self.selection_label = label("", "muted")
        self.selection_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.selection_label.setFixedHeight(24)
        selection_row = QHBoxLayout()
        selection_row.addWidget(self.selection_label, 1)
        self.fill_selection_button = button('填满选区', self.fill_selection, 'small')
        self.fill_selection_button.setToolTip('把整个框选区域填成当前颜色；支持透明色，可撤销。')
        selection_row.addWidget(self.fill_selection_button)
        view.addLayout(selection_row)
        self.canvas.selection_changed.connect(self._selection_changed)

        action_card, actions = card()
        action_row = QHBoxLayout()
        actions.addLayout(action_row)
        action_row.addStretch()
        self.apply_button = button("应用", self.apply, "primary")
        action_row.addWidget(self.apply_button)
        self.export_button = button("导出 PNG", self.export_png, "small")
        self.export_button.setToolTip("把画布上当前的像素画面按实际像素导出成 PNG，可选择保留网格线，透明层保留。")
        action_row.addWidget(self.export_button)
        action_row.addWidget(self.draft_button)
        self.convert_button = button("确认并生成三版本", self.convert, "primary")
        self.convert_button.setToolTip("确认画布上当前的像素，直接生成混合版、背景墙版和地图版；无需先点应用，不再缩小或调色。")
        action_row.addWidget(self.convert_button)
        self.close_button = button("返回预览", self.close, "small")
        action_row.addWidget(self.close_button)
        self.action_buttons = (self.apply_button, self.export_button,
                               self.convert_button, self.close_button, self.draft_button)
        for btn in self.action_buttons:
            btn.setFixedSize(152, 38)
            btn.setStyleSheet("QPushButton { font-size: 12px; padding: 0; }")
        outer.addWidget(action_card)

        split.addWidget(view_card)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 820])

        self.status_label = label("", "muted")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status_label.setFixedHeight(24)
        outer.addWidget(self.status_label)
        self.set_tool("brush")
        self.refresh_color_list()
        self.refresh_palette()
        self._selection_changed("")

    @staticmethod
    def _set_hint(widget, text):
        widget.setToolTip(text)
        widget.setText(widget.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, widget.width()))

    def _selection_changed(self, text):
        self._set_hint(self.selection_label, text)
        self.clear_selection_button.setEnabled(self.canvas.selection is not None)
        self.fill_selection_button.setEnabled(self.canvas.selection is not None)

    def _brush_size_changed(self, value):
        self.canvas.brush_size = value
        self.canvas.update()

    def fill_selection(self):
        if self.canvas.selection is None:
            return
        changed = self.canvas_model.fill_rectangle(self.canvas.selection,
                    rgb=self.current_swatch_color(), index=self.canvas.index)
        if changed:
            self.canvas.rebuild()
            self._canvas_changed()
            self._finish_stroke()

    # ---------- 状态同步 ----------

    def _sync_controls(self):
        material = self.canvas_model.is_material
        self.palette_name.setText("混合版（物块和背景墙 × 喷漆）" if self.target == "fine" else
                                  "地图版（物块和背景墙地图色）" if self.target == "map" else
                                  "背景墙版（背景墙 × 喷漆）" if material else "像素画：色库不限")
        self.palette_list.setVisible(material)
        self.search.setVisible(material)
        self.side_hint.setVisible(material)
        self.side_card.setVisible(material)
        has_result = self.result is not None
        self.apply_button.setVisible(has_result)
        self.apply_button.setEnabled(has_result)
        self.convert_button.setVisible(self.on_convert is not None)
        self.convert_button.setEnabled(self.on_convert is not None)
        self.undo_btn.setEnabled(self.canvas_model.can_undo)
        self.redo_btn.setEnabled(self.canvas_model.can_redo)
        self.reset_btn.setEnabled(self.canvas_model.dirty)
        color = self.current_swatch_color()
        self.current_swatch.setStyleSheet(
            f"background: {'rgba' if len(color)==4 else 'rgb'}{tuple(int(v) for v in color)}; border: 1px solid #34435c; border-radius: 5px;")
        self._set_hint(self.current_name, self.canvas_model.label_of(self.canvas.index) if material else
                       color_text(color))
        self.info.setText(f"{self.canvas_model.width} × {self.canvas_model.height} 格"
                          f"｜用色 {len(self.canvas_model.used_colors())} 种")
        if hasattr(self, "color_panel"):
            self.color_panel.set_color(color, remember=False)
            if not material:
                self.snap_hint.setText("")

    def current_swatch_color(self):
        if not self.canvas_model.is_material:
            return self.canvas.color
        if self.canvas.index == -1:
            return (0, 0, 0, 0)
        index = max(0, min(self.canvas.index, len(self.canvas_model.labels) - 1))
        self.canvas.color = tuple(int(v) for v in self.canvas_model.candidates[index])
        return self.canvas.color

    def set_tool(self, name: str):
        # 所有绘画工具共用当前色，切工具不从画布首格或面板默认值重建颜色。
        self.canvas.set_tool(name)
        self.screen_pick_button.setVisible(name == "picker")
        for tool, _title, _tip in self.TOOLS:
            getattr(self, f"tool_{tool}").setChecked(tool == name)
        self.status_label.setText(
            {"brush": "画笔：按住左键画，拖动连续改格", "fill": "填充：把相连的同色区域整块换掉",
             "picker": "取色笔：点画布取色；点“屏幕取色”可从其他窗口取色",
             "select": "框选：拖动选择矩形区域，点“填满选区”填成当前色 · Esc取消"}[name])

    def color_state(self):
        return dict(color=tuple(self.current_swatch_color()), history=list(self.color_panel.history.items))

    def _canvas_changed(self):
        self.undo_btn.setEnabled(True)
        self._refresh_timer.start()
        self.stage.setText("已修改（未保存草稿）" if self.result is None else "已修改（未应用）")

    def _refresh_after_edit(self):
        self._refresh_timer.stop()
        self._sync_controls()
        self.refresh_color_list()

    def _finish_stroke(self):
        self.color_panel.set_color(self.current_swatch_color(), remember=True)
        self._refresh_after_edit()

    def _picked_color(self, _text):
        self.color_panel.set_color(self.canvas.color, remember=True)
        if self.canvas_model.is_material:
            self.select_palette_index(self.canvas.index)
        self._sync_controls()

    def refresh_palette(self):
        self._palette_items = {}
        if not self.canvas_model.is_material:
            self.palette_list.clear()
            return
        self.palette_list.blockSignals(True)
        self.palette_list.clear()
        keyword = self.search.text().strip().lower()
        groups = {}
        for i, (rgb, text) in enumerate(zip(self.canvas_model.candidates, self.canvas_model.labels)):
            from .material_rules import permitted
            if not permitted(self.canvas_model.palette.candidates[i].block):
                continue
            if keyword and keyword not in text.lower():
                continue
            swatch = QPixmap(16, 16)
            swatch.fill(QColor(*[int(v) for v in rgb]))
            candidate = self.canvas_model.palette.candidates[i]
            block = candidate.block
            key = ('wall', block['wall_id']) if 'wall_id' in block else ('tile', block['tile_id'])
            note = material_tooltip(block)
            if key not in groups:
                parent = QTreeWidgetItem([block['name_zh'] + (' ※' if note else '')])
                base_swatch = QPixmap(16, 16)
                base_swatch.fill(QColor(*block['rgb']))
                parent.setIcon(0, QIcon(base_swatch))
                parent.setToolTip(0, note)
                self.palette_list.addTopLevelItem(parent)
                groups[key] = parent
            item = QTreeWidgetItem(groups[key], [candidate.paint['name_zh']])
            item.setIcon(0, QIcon(swatch))
            item.setToolTip(0, note)
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._palette_items[i] = item
        self.palette_list.blockSignals(False)
        self.select_palette_index(self.canvas.index)
        if keyword and len(groups) <= 10:
            self.palette_list.expandAll()

    def filter_palette(self):
        self.refresh_palette()

    def select_palette_index(self, index: int):
        item = self._palette_items.get(index)
        if item is not None:
            item.parent().setExpanded(True)
            self.palette_list.setCurrentItem(item)

    def palette_item_changed(self, item, previous=None):
        if item is None:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None:
            return
        index = int(index)
        self.canvas.index = index
        self.canvas.color = tuple(int(v) for v in self.canvas_model.candidates[index])
        self._sync_controls()

    def refresh_color_list(self):
        self.color_list.blockSignals(True)
        self.color_list.clear()
        for rgb in self.canvas_model.used_colors()[:400]:
            swatch = QPixmap(16, 16)
            swatch.fill(QColor(*[int(v) for v in rgb]))
            item = QListWidgetItem(QIcon(swatch), color_text(rgb))
            item.setData(Qt.ItemDataRole.UserRole, rgb)
            self.color_list.addItem(item)
        self.color_list.blockSignals(False)

    def color_row_changed(self, row: int):
        if row < 0:
            return
        item = self.color_list.item(row)
        if item is None:
            return
        rgb = tuple(item.data(Qt.ItemDataRole.UserRole))
        if self.canvas_model.is_material:
            index = -1 if len(rgb)==4 and rgb[3]==0 else self.canvas_model.nearest_index(rgb)
            self.canvas.index = index
            self.canvas.color = (0,0,0,0) if index==-1 else tuple(int(v) for v in self.canvas_model.candidates[index])
            self.select_palette_index(index)
        else:
            self.canvas.color = rgb
        self._sync_controls()

    # ---------- 操作 ----------

    def save_draft(self) -> bool:
        base = Path(self.host_window.base_dir()) if self.host_window is not None and hasattr(self.host_window, 'base_dir') else Path(__file__).resolve().parents[1]
        folder = self.draft_path.parent if self.draft_path else draft_folder(base)
        default = self.draft_path or folder / '未完成像素画.tpdraft'
        if self.draft_path is None:
            n = 2
            while default.exists():
                default = folder / f'未完成像素画({n}).tpdraft'
                n += 1
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法创建草稿文件夹", str(exc))
            return False
        filename, _ = QFileDialog.getSaveFileName(self, "保存像素草稿", str(default), "像素草稿 (*.tpdraft)")
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() != EXTENSION:
            path = path.with_suffix(EXTENSION)
        if path.exists() and QMessageBox.question(self, "替换已有草稿？", f"文件已存在：\n{path}\n是否替换？") != QMessageBox.StandardButton.Yes:
            return False
        try:
            save_draft(path, Draft(self.canvas_model, tuple(self.current_swatch_color()), self.canvas.tool,
                                   tuple(self.color_panel.history.items), self.canvas.selection))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "草稿保存失败", str(exc))
            return False
        self.draft_path = path
        try:
            remember_draft(base, path)
        except OSError:
            pass
        self._draft_checkpoint = fingerprint(self.canvas_model)
        self._set_hint(self.stage, f"草稿已保存：{path.name}")
        self._set_hint(self.status_label, f"下次用“打开草稿 / 图片”继续：{path}")
        return True

    def _panel_color_changed(self, rgb):
        """颜色面板选色：像素画直接用，材料版吸附到最近材料。"""
        rgb = tuple(int(v) for v in rgb)
        if self.canvas_model.is_material:
            index = -1 if len(rgb)==4 and rgb[3]==0 else self.canvas_model.nearest_index(rgb)
            self.canvas.index = index
            self.canvas.color = (0,0,0,0) if index==-1 else tuple(int(v) for v in self.canvas_model.candidates[index])
            self.select_palette_index(index)
            self.snap_hint.setText(f'已吸附：{self.canvas_model.label_of(index)}')
        else:
            self.canvas.color = rgb
            self.snap_hint.setText("")
        self._sync_controls()

    def undo(self):
        if self.canvas_model.undo():
            self.canvas.rebuild()
            self.refresh_color_list()
            self._sync_controls()
            self.stage.setText("已撤销")

    def redo(self):
        if self.canvas_model.redo():
            self.canvas.rebuild()
            self.refresh_color_list()
            self._sync_controls()
            self.stage.setText("已重做")

    def reset(self):
        if self.canvas_model.reset():
            self.canvas.rebuild()
            self.refresh_color_list()
            self._sync_controls()
            self.stage.setText("已恢复打开时的状态")

    def apply(self) -> bool:
        if not self.canvas_model.dirty:
            self.stage.setText("没有改动")
            return False
        self.canvas_model.apply_to(self.result)
        self.canvas_model.mark_applied()
        self._sync_controls()
        if self.on_apply:
            self.on_apply()
        self.stage.setText("已应用像素画，确认后生成三版本" if self.target == TARGET_PIXEL else "已应用本版编辑，记得在主窗口保存")
        return True

    def export_png(self):
        from .png_export import export_png
        folder = Path(self.result.out_dir) if self.result is not None and self.result.out_dir else (self.host_window.base_dir() if self.host_window else Path.home())
        try:
            path = export_png(self, self.canvas_model.to_array(), folder / '手绘像素画.png')
        except (OSError, ValueError, MemoryError) as exc:
            QMessageBox.warning(self, "PNG导出失败", str(exc))
            return
        if path:
            self.stage.setText(f"已导出PNG：{path.name}")
            if self.canvas_mode:
                self.canvas_model.mark_applied()

    def pick_screen(self):
        from .screen_picker import ScreenPicker
        if getattr(self, '_screen_picker', None) and self._screen_picker.windows:
            return
        try:
            self._screen_picker = ScreenPicker(self, self.canvas._picker_cursor, self.color_panel.pick_color)
        except RuntimeError as exc:
            QMessageBox.warning(self, "屏幕取色失败", str(exc))

    def convert(self):
        """把当前画布交给主窗口，跑成泰拉像素画。"""
        if not self.on_convert:
            return
        artwork = self.canvas_model.to_array()
        if self.on_convert(artwork) is False:
            self.stage.setText("转换未开始，画布已保留")
            return
        self._allow_close = True
        self.close()

    def closeEvent(self, event):
        if getattr(self, "_screen_picker", None):
            self._screen_picker.cancel()
        saved_draft = self._draft_checkpoint is not None and fingerprint(self.canvas_model) == self._draft_checkpoint
        if self.canvas_model.dirty and not saved_draft and not getattr(self, "_allow_close", False):
            from PySide6.QtWidgets import QMessageBox
            question = "当前画面尚未保存。保存草稿后，下次可以打开继续编辑。"
            answer = QMessageBox.question(self, "保存未完成的画面？", question,
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Save:
                if not self.save_draft():
                    event.ignore()
                    return
            elif answer not in (QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Yes):
                event.ignore()
                return
        super().closeEvent(event)
        self.closed.emit()
