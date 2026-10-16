"""用真实鼠标和按钮验证框选填满、粗笔连续绘制及默认行为。"""
import os, sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from terraria_pixel.desktop import configure_app
from terraria_pixel.editor import EditCanvas
from terraria_pixel.editor_window import PixelEditorWindow

app = QApplication.instance() or QApplication([])
configure_app(app)
model = EditCanvas(np.random.default_rng(411).integers(0,256,(20,24,3),dtype=np.uint8))
window = PixelEditorWindow(canvas=model)
window.resize(1200,800)
window.show()
app.processEvents()
canvas=window.canvas
canvas.fit()

def point(x,y):
    rect=canvas.image_rect()
    return QPointF(rect.x()+(x+.5)*canvas.zoom,rect.y()+(y+.5)*canvas.zoom).toPoint()

def stroke(start,end):
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=point(*start))
    pos=point(*end)
    QApplication.sendEvent(canvas,QMouseEvent(QEvent.Type.MouseMove,QPointF(pos),QPointF(pos),
        Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=pos)
    app.processEvents()

assert canvas.brush_size == 1 and not window.fill_selection_button.isEnabled()
window.tool_select.click()
stroke((2,3),(8,9))
assert canvas.selection==(2,3,8,9) and window.fill_selection_button.isEnabled()
before=model.rgb.copy()
window.color_panel.pick_color((19,70,140))
window.fill_selection_button.click()
expected=before.copy();expected[3:10,2:9]=(19,70,140)
np.testing.assert_array_equal(model.rgb,expected)
window.undo_btn.click()
np.testing.assert_array_equal(model.rgb,before)
window.redo_btn.click()
np.testing.assert_array_equal(model.rgb,expected)
window.color_panel.pick_color((0,0,0,0))
window.fill_selection_button.click()
assert np.all(model.rgb[3:10,2:9,3] == 0)
window.undo_btn.click()
window.clear_selection_button.click()
assert not window.fill_selection_button.isEnabled()
window.brush_size_input.setValue(3)
window.color_panel.pick_color((150,80,40))
window.tool_brush.click()
before=model.rgb.copy()
stroke((5,12),(14,12))
expected=before.copy();expected[11:14,4:16]=(150,80,40,255)
np.testing.assert_array_equal(model.rgb,expected)
window.undo_btn.click()
np.testing.assert_array_equal(model.rgb,before)
window.redo_btn.click()
np.testing.assert_array_equal(model.rgb,expected)
window.tool_fill.click();window.tool_picker.click();window.tool_brush.click()
assert canvas.brush_size==3 and canvas.color[:3]==(150,80,40)
window.resize(900,620);app.processEvents()
assert window.brush_size_input.width()>=80
assert window.fill_selection_button.isVisible()
output=Path(__file__).resolve().parents[2]/'.tmp/release-411'
output.mkdir(parents=True,exist_ok=True)
window.grab().save(str(output/'editor-small.png'))
window.resize(1440,900);app.processEvents()
window.grab().save(str(output/'editor.png'))
window._allow_close=True
window.close()
print('Selection fill/button/alpha/undo, 3-cell continuous brush/undo, tool switching and small layout: PASS')
