"""世界导入界面：异步读取、地图定位、另存世界与取消。"""
from pathlib import Path
import threading

from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                              QComboBox, QSpinBox, QFileDialog, QProgressBar, QMessageBox, QCheckBox)

from .desktop import MainWindow, button, label, to_pixmap
from .formats import ConversionCancelled, VERSION_DESCRIPTIONS
from .pixels import material_pixels
from .world import load_world, import_into_world, material_version
from .history import HistoryStore, save_world_import_record


VERSION_NAMES = {'fine': '混合版', 'wall': '背景墙版', 'map': '地图版'}


class WorldWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)
    stopped = Signal()

    def __init__(self, operation, subject, options, parent, *, history, output_root):
        super().__init__(parent)
        self.operation, self.subject, self.options = operation, subject, options
        self.history, self.output_root = history, output_root
        self.abort = threading.Event()

    def run(self):
        try:
            operation = load_world if self.operation == 'load' else import_into_world
            result = operation(self.subject, **self.options, progress=self.progress.emit, cancelled=self.abort.is_set)
            if self.operation != 'load':
                # 世界已发布；后续取消/记录/预览失败不能误报为世界写入失败。
                path = result
                record, history_error = None, ''
                self.progress.emit(100, '世界已保存，正在保存作品记录')
                try:
                    options = self.options
                    record = save_world_import_record(self.subject, self.output_root, path,
                        source=options['document'].path, version=options['version'],
                        x=options['x'], y=options['y'], coating=options['coating'],
                        overwrite=options.get('overwrite', False))
                    self.history.remember(record.out_dir)
                except Exception as exc:
                    history_error = str(exc) or type(exc).__name__
                try:
                    document = load_world(path)
                except Exception:
                    document = None
                result = dict(path=path, document=document, record=record, history_error=history_error)
            self.completed.emit(result)
        except ConversionCancelled:
            self.stopped.emit()
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class PlacementView(QWidget):
    position = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 220)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.document = self.world_pixmap = self.art_pixmap = None
        self.art_width = self.art_height = 0
        self.x = self.y = 0
        self.zoom = 1.0
        self.pan = QPointF()
        self._press = self._last = None
        self._moving_art = self._dragged = False

    def world_rect(self):
        if self.document is None:
            return QRectF()
        info = self.document.info
        ratio = min((self.width() - 32) / info.width, (self.height() - 32) / info.height)
        w, h = info.width * ratio * self.zoom, info.height * ratio * self.zoom
        return QRectF((self.width() - w) / 2 + self.pan.x(), (self.height() - h) / 2 + self.pan.y(), w, h)

    def set_document(self, document, *, reset=True):
        self.document = document
        self.world_pixmap = to_pixmap(document.overview) if document is not None else None
        if reset:
            self.fit()
        self.update()

    def fit(self):
        self.zoom, self.pan = 1.0, QPointF()
        self.update()

    def zoom_at(self, factor, point=None):
        if self.document is None:
            return
        point = point or QPointF(self.rect().center())
        before = self.world_rect()
        old = self.zoom
        self.zoom = max(1.0, min(64.0, old * factor))
        ratio = self.zoom / old
        after = self.world_rect()
        self.pan += point - (after.topLeft() + (point - before.topLeft()) * ratio)
        if self.zoom == 1:
            self.pan = QPointF()
        self.update()

    def artwork_rect(self):
        rect = self.world_rect()
        if self.document is None:
            return QRectF()
        info = self.document.info
        return QRectF(rect.x() + rect.width() * self.x / info.width,
                      rect.y() + rect.height() * self.y / info.height,
                      rect.width() * self.art_width / info.width,
                      rect.height() * self.art_height / info.height)

    def set_art(self, rgb, scale):
        image = Image.fromarray(rgb)
        self.art_width, self.art_height = image.width * scale, image.height * scale
        image.thumbnail((700, 500), Image.Resampling.NEAREST)
        import numpy as np
        self.art_pixmap = to_pixmap(np.asarray(image))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#101827'))
        if self.document is None:
            p.setPen(QColor('#a4b1c8'))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '选择世界后，点击地图设置像素画的左上角')
            return
        rect = self.world_rect()
        p.drawPixmap(rect, self.world_pixmap, QRectF(self.world_pixmap.rect()))
        p.setPen(QPen(QColor('#a4b1c8'), 1))
        p.drawRect(rect)
        if self.art_pixmap is not None:
            info = self.document.info
            art_rect = self.artwork_rect()
            p.save()
            p.setClipRect(rect)
            p.setOpacity(.9)
            p.drawPixmap(art_rect, self.art_pixmap, QRectF(self.art_pixmap.rect()))
            p.restore()
            valid = self.x + self.art_width <= info.width and self.y + self.art_height <= info.height
            p.setPen(QPen(QColor('#83afff' if valid else '#ff8c92'), 2))
            p.drawRect(art_rect)
            p.drawLine(int(art_rect.x()) - 6, int(art_rect.y()), int(art_rect.x()) + 6, int(art_rect.y()))
            p.drawLine(int(art_rect.x()), int(art_rect.y()) - 6, int(art_rect.x()), int(art_rect.y()) + 6)

    def _pick(self, event):
        rect = self.world_rect()
        if self.document is not None and rect.contains(event.position()):
            info = self.document.info
            x = int((event.position().x() - rect.x()) * info.width / rect.width())
            y = int((event.position().y() - rect.y()) * info.height / rect.height())
            self.position.emit(max(0, min(x, info.width - self.art_width)),
                               max(0, min(y, info.height - self.art_height)))

    def mousePressEvent(self, event):
        if self.document is None:
            return
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._press = self._last = event.position()
            self._dragged = False
            self._moving_art = event.button() == Qt.MouseButton.LeftButton and self.artwork_rect().contains(event.position())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._press is None or self.document is None:
            return
        if (event.position() - self._press).manhattanLength() > 3:
            self._dragged = True
        if self._dragged:
            delta = event.position() - self._last
            if self._moving_art:
                rect, info = self.world_rect(), self.document.info
                self._art_delta = getattr(self, '_art_delta', QPointF()) + delta
                dx = round(self._art_delta.x() * info.width / rect.width())
                dy = round(self._art_delta.y() * info.height / rect.height())
                self.position.emit(max(0, min(self.x + dx, info.width - self.art_width)),
                                   max(0, min(self.y + dy, info.height - self.art_height)))
                self._art_delta -= QPointF(dx * rect.width() / info.width, dy * rect.height() / info.height)
            else:
                self.pan += delta
                self.update()
        self._last = event.position()

    def mouseReleaseEvent(self, event):
        if self._press is not None:
            if not self._dragged and not self._moving_art and event.button() == Qt.MouseButton.LeftButton:
                self._pick(event)
            self._press = self._last = None
            self._art_delta = QPointF()
            self.setCursor(Qt.CursorShape.CrossCursor)

    def wheelEvent(self, event):
        self.zoom_at(1.25 ** (event.angleDelta().y() / 120), event.position())
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self._press = self._last = None
        self.fit()


class WorldImportDialog(QDialog):
    saved = Signal(object)
    def __init__(self, result, version='fine', parent=None, *, history=None, output_root=None):
        super().__init__(parent)
        self.artwork = result
        base = MainWindow.base_dir()
        self.history = history if history is not None else getattr(parent, 'history', None)
        if self.history is None:
            self.history = HistoryStore(base / '历史记录.json', base / '输出')
        if output_root is None and parent is not None and hasattr(parent, 'output_input'):
            output_root = parent.output_input.text().strip()
        self.output_root = Path(output_root or self.history.default_root)
        self.document = self.worker = self.saved_path = None
        self._closing = False
        self.setWindowTitle('导入到世界 .wld')
        self.resize(1040, 710)
        self.setMinimumSize(720, 560)
        self.setSizeGripEnabled(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        outer.addWidget(label('把当前作品放进世界', 'section'))
        note = label('选择世界 → 选择材料版本和位置 → 直接保存或另存为 .wld。', 'muted')
        note.setWordWrap(True)
        outer.addWidget(note)
        row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText('请选择 Terraria 世界文件（.wld）')
        row.addWidget(self.path_input, 1)
        self.browse_button = button('选择世界…', self.choose_world)
        row.addWidget(self.browse_button)
        outer.addLayout(row)
        self.info_label = label('尚未选择世界', 'muted')
        self.info_label.setWordWrap(True)
        outer.addWidget(self.info_label)
        row = QHBoxLayout()
        row.addWidget(label('材料版本'))
        self.version_input = QComboBox()
        for key, name in VERSION_NAMES.items():
            try:
                _, palette = material_version(result, key)
            except ValueError:
                continue
            self.version_input.addItem(name, key)
        self.version_input.setCurrentIndex(max(0, self.version_input.findData(version)))
        self.version_input.currentIndexChanged.connect(self._version_changed)
        row.addWidget(self.version_input, 1)
        self.x_input = QSpinBox(self)
        self.x_input.setRange(0, 32767)
        self.x_input.valueChanged.connect(self._position_changed)
        self.x_input.hide()
        self.y_input = QSpinBox(self)
        self.y_input.setRange(0, 32767)
        self.y_input.valueChanged.connect(self._position_changed)
        self.y_input.hide()
        outer.addLayout(row)
        self.size_label = label('', 'muted')
        self.version_description = label('', 'muted')
        self.version_description.setWordWrap(True)
        outer.addWidget(self.version_description)
        outer.addWidget(self.size_label)
        self.coating_input = QCheckBox('添加夜明涂层（夜明漆）')
        self.coating_input.setChecked(True)
        self.coating_input.setToolTip('勾选后给此次导入的物块和背景墙添加夜明涂层，三种材料版本均适用。关闭后不添加；不改变材料和喷漆。')
        outer.addWidget(self.coating_input)
        self.view = PlacementView()
        self.view.position.connect(self._picked)
        outer.addWidget(self.view, 1)
        navigation = QHBoxLayout()
        navigation.addWidget(button('－ 缩小', lambda: self.view.zoom_at(0.8)))
        navigation.addWidget(button('＋ 放大', lambda: self.view.zoom_at(1.25)))
        navigation.addWidget(button('显示全图', self.view.fit))
        navigation.addStretch()
        outer.addLayout(navigation)
        note = label('滚轮缩放；拖动空白处或按住右键平移世界；拖动画作移动位置；单击地图定位，双击恢复全图。缩放仅影响预览。', 'muted')
        note.setWordWrap(True)
        outer.addWidget(note)
        note = label('不透明像素替换整格原有物块、墙、液体和电线；透明位置保留原地形，不能覆盖家具。\n请退出该游戏世界后操作。直接保存会覆盖所选世界，不生成备份；另存为保留原文件。导入成功后自动保存作品历史记录。', 'muted')
        note.setWordWrap(True)
        outer.addWidget(note)
        self.status = label('先选择要放置的世界', 'muted')
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        outer.addWidget(self.progress)
        row = QHBoxLayout()
        self.cancel_button = button('取消处理', self.cancel_work)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)
        row.addStretch()
        self.back_button = button('返回', self.reject)
        row.addWidget(self.back_button)
        self.save_button = button('放置并另存世界…', self.save_world, 'primary')
        self.direct_button = button('直接保存到此世界', self.save_direct)
        # Keep the action row aligned regardless of the primary button theme.
        actions = (self.cancel_button, self.back_button, self.direct_button, self.save_button)
        for action in actions:
            action.setStyleSheet('QPushButton { font-size: 13px; padding: 8px 13px; }')
            action.ensurePolished()
        action_height = max(42, *(action.sizeHint().height() for action in actions))
        for action in actions:
            action.setFixedHeight(action_height)
        save_width = max(160, self.direct_button.sizeHint().width(), self.save_button.sizeHint().width())
        self.direct_button.setFixedWidth(save_width)
        self.save_button.setFixedWidth(save_width)
        self.back_button.setMinimumWidth(72)
        row.addWidget(self.direct_button)
        row.addWidget(self.save_button)
        outer.addLayout(row)
        self._version_changed()

    def _version_changed(self, *args):
        self.version_description.setText(VERSION_DESCRIPTIONS[self.version_input.currentData()])
        grid, palette = material_version(self.artwork, self.version_input.currentData())
        self.view.set_art(material_pixels(grid, palette), self.artwork.scale)
        self.size_label.setText(f'放置尺寸：{grid.shape[1] * self.artwork.scale} × {grid.shape[0] * self.artwork.scale} 格（每像素 {self.artwork.scale}×{self.artwork.scale}）')
        self._position_changed()

    def _position_changed(self, *args):
        self.view.x, self.view.y = self.x_input.value(), self.y_input.value()
        self.view.update()
        self._update_controls()

    def _picked(self, x, y):
        self.x_input.setValue(x)
        self.y_input.setValue(y)

    def _update_controls(self):
        busy = self.worker is not None
        for control in (self.browse_button, self.version_input, self.x_input, self.y_input, self.coating_input, self.view):
            control.setEnabled(not busy)
        valid = self.document is not None
        if valid:
            info = self.document.info
            valid = self.view.x + self.view.art_width <= info.width and self.view.y + self.view.art_height <= info.height
        self.save_button.setEnabled(valid and not busy)
        self.direct_button.setEnabled(valid and not busy)
        if self.document is not None and not busy:
            self.status.setText('位置有效，可以直接保存或另存为。' if valid else '作品超出世界边界，请调整位置或缩小作品。')
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)

    def choose_world(self):
        directory = Path.home() / 'Documents/My Games/Terraria/Worlds'
        path, _ = QFileDialog.getOpenFileName(self, '选择要导入的世界', str(directory), 'Terraria 世界 (*.wld)')
        if path:
            self.load_path(path)

    def load_path(self, path):
        if self.worker is not None:
            return
        self.document = None
        self.view.set_document(None)
        self.path_input.setText(str(path))
        self.info_label.setText('正在读取世界信息与地形…')
        self._start('load', path, {})

    def _start(self, operation, subject, options):
        self.worker = WorldWorker(operation, subject, options, self,
                                  history=self.history, output_root=self.output_root)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.stopped.connect(lambda: self.status.setText('已取消；原世界保持不变。'))
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._finished)
        self.progress.setValue(0)
        self._update_controls()
        self.worker.start()

    def _progress(self, value, text):
        self.progress.setValue(value)
        self.status.setText(f'{text} · {value}%')

    def _completed(self, value):
        if self.worker.operation == 'load':
            self.document = value
            info = value.info
            self.info_label.setText(f'{info.name} · {info.width} × {info.height} 格 · 存档版本 {info.version}')
            self.x_input.setMaximum(info.width - 1)
            self.y_input.setMaximum(info.height - 1)
            self.x_input.setValue(max(0, (info.width - self.view.art_width) // 2))
            self.y_input.setValue(min(50, max(0, info.height - self.view.art_height)))
            self.view.set_document(value)
        else:
            self.saved_path, self.document = value['path'], value['document']
            self.path_input.setText(str(self.saved_path))
            self.view.set_document(self.document, reset=False)
            message = (f'世界已保存：{self.saved_path}。' +
                       ('作品已存入“历史记录 / 草稿”。' if not value['history_error'] else '作品记录未完整保存。') +
                       ('可以继续移动作品或选择其他世界。' if self.document else '预览刷新失败，请重新选择世界。'))
            self.status.setText(message)
            self.saved.emit(value)
            if value['history_error'] and not self._closing:
                record = value['record']
                details = (f'作品数据已保存在：{record.out_dir}，可在历史窗口导入此文件夹。' if record else
                           '当前作品仍在内存中，请返回主界面，通过“保存TEdit文件”保存作品记录。')
                QMessageBox.warning(self, '世界已保存，作品记录保存未完成',
                    f'世界文件已成功写入，无需再次导入。\n{details}\n原因：{value["history_error"]}')

    def _failed(self, message):
        self.status.setText(message)
        if self.worker.operation == 'load':
            self.info_label.setText('未能读取世界，请重新选择。')
        if not self._closing:
            QMessageBox.warning(self, '世界导入未完成', message)

    def _finished(self):
        worker = self.worker
        self.worker = None
        previous_status = self.status.text()
        self._update_controls()
        if worker.operation != 'load' or self.document is None:
            self.status.setText(previous_status)
        worker.deleteLater()
        if self._closing:
            super().reject()

    def save_direct(self):
        if self.worker is None and self.document is not None and self.direct_button.isEnabled():
            self._start('save', self.artwork, dict(document=self.document, destination=self.document.path,
                        overwrite=True, version=self.version_input.currentData(),
                        coating=self.coating_input.isChecked(),
                        x=self.x_input.value(), y=self.y_input.value()))

    def save_world(self):
        if self.worker is not None or self.document is None or not self.save_button.isEnabled():
            return
        original = self.document.path
        destination = original.with_name(original.stem + '-像素画.wld')
        counter = 2
        while destination.exists():
            destination = original.with_name(original.stem + f'-像素画({counter}).wld')
            counter += 1
        path, _ = QFileDialog.getSaveFileName(self, '另存新世界（请选择新文件名）', str(destination), 'Terraria 世界 (*.wld)',
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        path = Path(path)
        if not path.suffix:
            path = path.with_suffix('.wld')
        if path.resolve() == original or path.exists():
            QMessageBox.warning(self, '请选择新文件名', '不会覆盖原世界或已有文件，请使用新的文件名。')
            return
        self._start('save', self.artwork, dict(document=self.document, destination=path,
                    coating=self.coating_input.isChecked(),
                    version=self.version_input.currentData(), x=self.x_input.value(), y=self.y_input.value()))

    def cancel_work(self):
        if self.worker is not None:
            self.worker.abort.set()
            self.status.setText('正在取消，请稍候…')

    def reject(self):
        if self.worker is not None:
            self._closing = True
            self.cancel_work()
        else:
            super().reject()

    def accept(self):
        if self.worker is None and self.saved_path is not None:
            super().accept()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
