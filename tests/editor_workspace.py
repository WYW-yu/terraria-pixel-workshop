"""真实工作区回归：内嵌生命周期、布局稳定、选区边界、PNG纯像素。"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.editor import EditCanvas
from terraria_pixel.editor_window import PixelEditorWindow
from terraria_pixel.pipeline import Result

app = QApplication([])
from terraria_pixel.png_export import PngExportDialog
from PySide6.QtWidgets import QDialog
PngExportDialog.exec = lambda self: QDialog.DialogCode.Accepted
configure_app(app)
output = Path(__file__).resolve().parents[2] / '.tmp/desktop-verification'
output.mkdir(parents=True, exist_ok=True)
main = MainWindow()
main.result = Result(processed_rgb=np.full((24, 32, 3), 255, np.uint8))
main.mode = 4
main.show()
main.open_editor()
QTest.qWait(30)
editor = main.editors[0]
canvas = editor.canvas
assert not editor.isWindow() and editor.window() is main
assert main.workspace_pages.currentWidget() is editor
assert len([w for w in app.topLevelWidgets() if w.isVisible()]) == 1
assert {tuple((b.width(), b.height())) for b in editor.action_buttons} == {(152, 38)}

geometry = canvas.geometry()
image_rect = canvas.image_rect()
for text in ('', '(0, 0) #FFFFFF', '材料：' + '这是很长的材料名称' * 50, ''):
    canvas.hovered.emit(text)
    editor.stage.setText(text)
    editor.info.setText(text)
    editor._refresh_after_edit()
    QTest.qWait(140)
    assert canvas.geometry() == geometry, 'Dynamic hints must not resize the canvas'
    assert canvas.image_rect() == image_rect, 'Dynamic hints must not shift the image'

def point(x, y):
    rect = canvas.image_rect()
    return QPoint(round(rect.x() + (x + .5) * canvas.zoom),
                  round(rect.y() + (y + .5) * canvas.zoom))

def drag(start, end):
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(end), Qt.MouseButton.NoButton,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(canvas, move)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

QTest.keyClick(canvas, Qt.Key.Key_M)
assert canvas.tool == 'select'
drag(point(8, 7), point(3, 2))
assert canvas.selection == (3, 2, 8, 7)
assert not editor.canvas_model.dirty and not editor.canvas_model.can_undo
editor.set_tool('fill')
canvas.color = (20, 80, 150)
QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point(4, 3))
expected = np.full((24, 32, 3), 255, np.uint8)
expected[2:8, 3:9] = (20, 80, 150)
np.testing.assert_array_equal(editor.canvas_model.rgb, expected)
editor.undo()
editor.set_tool('brush')
drag(point(0, 4), point(15, 4))
expected = np.full((24, 32, 3), 255, np.uint8)
expected[4, 3:9] = (20, 80, 150)
np.testing.assert_array_equal(editor.canvas_model.rgb, expected)
editor.undo()
assert not editor.canvas_model.can_undo
editor.redo()
editor.canvas_model.mark_applied()
export = output / 'workspace-export.png'
export.unlink(missing_ok=True)
with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(export), 'PNG')), \
        patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
    editor.export_png()
with Image.open(export) as png:
    np.testing.assert_array_equal(np.asarray(png), expected)
main.grab().save(str(output / 'editor-workspace.png'))

# 缩放以鼠标为中心；格坐标与选区不受缩放影响。
anchor = QPointF(point(4, 3))
old = canvas.image_rect()
coords = ((anchor.x() - old.x()) / canvas.zoom, (anchor.y() - old.y()) / canvas.zoom)
canvas.set_zoom(canvas.zoom * 1.15, anchor)
new = canvas.image_rect()
np.testing.assert_allclose(((anchor.x() - new.x()) / canvas.zoom,
                            (anchor.y() - new.y()) / canvas.zoom), coords)
QTest.keyClick(canvas, Qt.Key.Key_Escape)
assert canvas.selection is None
canvas.fit()
main.resize(1100, 760)
QTest.qWait(30)
assert canvas.image_rect().width() <= canvas.width()
assert canvas.image_rect().height() <= canvas.height()
editor.canvas_model.set_cell(0, 0, rgb=(1, 2, 3))
with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
    assert not editor.close()
assert main.workspace_pages.currentWidget() is editor
assert not hasattr(editor, 'apply_close_button')
editor.apply_button.click()
assert main.workspace_pages.currentWidget() is editor
assert editor.canvas_model.dirty is False
editor.close_button.click()
assert not main.editors and main.workspace_pages.currentWidget() is main.body_splitter
assert main.history_button.isEnabled()
np.testing.assert_array_equal(main.result.processed_rgb[0, 0], (1, 2, 3))
app.processEvents()

main.set_mode(4)
QTest.qWait(20)
preview_geometry = main.canvas.geometry()
preview_rect = main.canvas.image_rect()
for text, zoom in (('短提示', .99), ('长提示' * 100, 1), ('', 10)):
    main.canvas.hover.emit(text)
    main.canvas.zoom_changed.emit(zoom)
    QTest.qWait(20)
    assert main.canvas.geometry() == preview_geometry
    assert main.canvas.image_rect() == preview_rect

# 新建画布也内嵌；转换失败继续保留，退出后可以再次创建。
creator = PixelEditorWindow(canvas=EditCanvas.blank(16, 12), parent=main, on_convert=lambda rgb: False)
main._track_editor(creator)
QTest.qWait(20)
creator.canvas_model.set_cell(0, 0, rgb=(7, 8, 9))
creator.convert()
assert creator.isVisible() and main.workspace_pages.currentWidget() is creator
creator._allow_close = True
creator.close()
assert not main.editors
app.processEvents()
main.close()
print('Workspace OK: one main window / uniform buttons / stable layout / selection-restricted brush and fill / undo / PNG / zoom anchor / return and close protection')
