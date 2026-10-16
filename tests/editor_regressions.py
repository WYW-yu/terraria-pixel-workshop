"""编辑器真实控件回归：连续笔画、关闭保护、取色、失败保留和大图适应。"""
import os
import sys
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.editor import EditCanvas
from terraria_pixel.editor_window import PixelEditorWindow
from terraria_pixel.pipeline import Result

app = QApplication([])
configure_app(app)
output = Path(__file__).resolve().parents[2] / '.tmp/desktop-verification'
output.mkdir(parents=True, exist_ok=True)

window = PixelEditorWindow(canvas=EditCanvas.blank(24, 18), on_convert=lambda rgb: False)
window.show()
app.processEvents()
canvas = window.canvas
canvas.fit()
rect = canvas.image_rect()
start = QPoint(round(rect.x() + canvas.zoom / 2), round(rect.y() + canvas.zoom / 2))
end = QPoint(round(rect.x() + 10.5 * canvas.zoom), start.y())
canvas.color = (12, 34, 56)
QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
event = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(end), Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
app.sendEvent(canvas, event)
QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
np.testing.assert_array_equal(window.canvas_model.rgb[0, :11], np.tile((12, 34, 56), (11, 1)))
window.undo()
assert not window.canvas_model.dirty and not window.canvas_model.can_undo
window.redo()
assert window.canvas_model.dirty
assert canvas._to_cell(QPointF(rect.x() - .1, rect.y())) is None
canvas._paint((0, 0), pick_only=True)
assert window.color_panel.rgb == (12, 34, 56)
assert window.color_panel.history.items[0] == (12, 34, 56)
window.convert()
assert window.isVisible(), 'Failed conversion must retain artwork'
QTest.keyClick(canvas, Qt.Key.Key_I)
assert canvas.tool == 'picker' and window.tool_picker.isChecked()
window.color_panel.pick_color((255, 0, 0))
window.color_panel._hue_changed(120)
assert window.color_panel.hue_strip.hue == 120
window.color_panel._val_changed(0)
window.color_panel._val_changed(1)
assert window.color_panel.rgb == (0, 255, 0)
window.grab().save(str(output / 'editor-v45.png'))
with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
    assert not window.close()
window._allow_close = True
window.close()

result = Result(processed_rgb=np.full((8, 8, 3), 255, dtype=np.uint8))
editor = PixelEditorWindow(result)
editor.canvas_model.set_cell(0, 0, rgb=(1, 2, 3))
assert editor.apply() and not editor.canvas_model.dirty
with patch.object(QMessageBox, 'question', side_effect=AssertionError('Applied changes should not prompt')):
    assert editor.close()

large = PixelEditorWindow(canvas=EditCanvas.blank(1600, 1000))
large.show()
app.processEvents()
large.canvas.fit()
assert large.canvas.image_rect().width() <= large.canvas.width()
assert large.canvas.image_rect().height() <= large.canvas.height()
large.close()

main = MainWindow()
main.result = result
main.mode = 4
main.open_editor()
active = main.editors[-1]
assert not main.edit_button.isEnabled()
active.canvas_model.set_cell(1, 1, rgb=(4, 5, 6))
with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
    assert not main.close()
active._allow_close = True
active.close()
QTest.qWait(20)
app.processEvents()
assert not main.editors
assert main.edit_button.isEnabled()
previous = main.result
with patch.object(QMessageBox, 'warning'):
    assert main.convert_canvas(np.zeros((4, 4, 2), np.uint8)) is False
assert main.result is previous
main.close()
print('Editor regressions OK: continuous brush / one-stroke undo / picker / shortcuts / apply checkpoint / close guard / failed conversion / large fit / editor lifecycle')
