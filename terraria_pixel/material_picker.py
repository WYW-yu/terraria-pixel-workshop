"""按物体展开喷漆的素材选择器；只有透光墙显示悬停说明。"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QTreeWidget, QTableWidget, QToolTip


def material_tooltip(block):
    translucent = block.get('translucent_wall') or '透明' in block.get('color_note', '')
    return '透光墙' if 'wall_id' in block and translucent else ''


class StableTooltips:
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._tooltip_item = None
        self.verticalScrollBar().valueChanged.connect(self.dismiss_tooltip)
        self.horizontalScrollBar().valueChanged.connect(self.dismiss_tooltip)

    def dismiss_tooltip(self, *args):
        QToolTip.hideText()
        self._tooltip_item = None

    def clear(self):
        self.dismiss_tooltip()
        super().clear()

    def viewportEvent(self, event):
        kind = event.type()
        if kind == QEvent.Type.ToolTip:
            item = self.itemAt(event.pos())
            text = (item.toolTip(0) if isinstance(self, QTreeWidget) else item.toolTip()) if item else ''
            if text:
                self._tooltip_item = item
                QToolTip.showText(event.globalPos(), text, self.viewport(), self.visualItemRect(item), 4000)
            else:
                self.dismiss_tooltip()
                event.ignore()
            return True
        if kind in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.Wheel, QEvent.Type.MouseButtonPress):
            self.dismiss_tooltip()
        elif kind == QEvent.Type.MouseMove and self.itemAt(event.position().toPoint()) is not self._tooltip_item:
            self.dismiss_tooltip()
        return super().viewportEvent(event)

    def hideEvent(self, event):
        self.dismiss_tooltip()
        super().hideEvent(event)


class MaterialTree(StableTooltips, QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.itemClicked.connect(self._toggle_material)

    def _toggle_material(self, item, column):
        if item.data(0, Qt.ItemDataRole.UserRole) is None:
            item.setExpanded(not item.isExpanded())


class MaterialTable(StableTooltips, QTableWidget):
    def __init__(self, rows=0, columns=3, parent=None):
        super().__init__(parent)
        self.setRowCount(rows)
        self.setColumnCount(columns)
