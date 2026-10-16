"""真实控件：滴管、工具共享颜色、方形色板、值预览、保存关闭和重开。"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.editor import EditCanvas
from terraria_pixel.editor_window import PixelEditorWindow
from terraria_pixel.pipeline import Result

app = QApplication([])
configure_app(app)
output = Path(__file__).resolve().parents[2] / '.tmp/desktop-verification'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=output) as temporary:
    path = Path(temporary) / '未完成像素画.tpdraft'
    main = MainWindow()
    main.show()
    editor = PixelEditorWindow(canvas=EditCanvas.blank(32, 24), parent=main)
    main._track_editor(editor)
    QTest.qWait(30)
    assert not hasattr(editor.color_panel, 'pick_button')
    panel = editor.color_panel
    panel.tabs.setCurrentIndex(2)
    QTest.qWait(20)
    panel.hex_input.setFocus()
    QTest.qWait(20)
    panel.hex_input.setText('#DB1616')
    QTest.mouseClick(editor.tool_fill, Qt.MouseButton.LeftButton)
    assert editor.canvas.color == (219, 22, 22), editor.canvas.color
    for name in ('brush', 'picker', 'select', 'fill', 'brush'):
        QTest.mouseClick(getattr(editor, 'tool_' + name), Qt.MouseButton.LeftButton)
        assert editor.canvas.color == (219, 22, 22)
        assert panel.rgb == (219, 22, 22)
    editor.set_tool('picker')
    assert not editor.canvas.cursor().pixmap().isNull()
    assert editor.canvas.cursor().hotSpot() == QPoint(3, 28)
    assert '(219, 22, 22)' in panel.value_preview.styleSheet()
    main.grab().save(str(output / 'editor-values-v452.png'))
    panel.tabs.setCurrentIndex(1)
    QTest.qWait(20)
    for width in (245, 220, 270):
        panel.grid.resize(width, panel.grid.height())
        app.processEvents()
        assert all(panel.grid.cell_rect(i).width() == panel.grid.cell_rect(i).height() for i in range(60))
    chosen = 15
    QTest.mouseClick(panel.grid, Qt.MouseButton.LeftButton, pos=panel.grid.cell_rect(chosen).center())
    assert editor.canvas.color == panel.grid.colors[chosen]
    main.grab().save(str(output / 'editor-classic-v452.png'))
    editor.set_tool('brush')
    editor.canvas._paint((4, 5))
    panel.pick_color((12, 34, 56))
    editor.canvas.selection = (2, 3, 8, 7)
    pixels = editor.canvas_model.rgb.copy()
    # 从主窗口关闭时选择保存；取消文件选择不能关闭也不能丢画面。
    with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save), \
            patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
        assert not main.close()
    assert main.editors and editor.isVisible()
    with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save), \
            patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
        assert main.close()
    assert path.is_file()
    assert main.editor_color_state['color'] == (12, 34, 56)
    app.processEvents()
    # 新进程等价：创建全新的主窗口，从文件恢复画面、颜色、工具、选区。
    next_main = MainWindow()
    next_main.show()
    with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
        next_main.open_draft()
    reopened = next_main.editors[0]
    QTest.qWait(20)
    np.testing.assert_array_equal(reopened.canvas_model.rgb, pixels)
    assert reopened.canvas.color == (12, 34, 56)
    assert reopened.canvas.selection == (2, 3, 8, 7)
    assert reopened.canvas.tool == 'brush'
    reopened.canvas._paint((3, 4))
    assert reopened.canvas_model.color_at(3, 4) == (12, 34, 56)
    with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')), \
            patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
        assert reopened.save_draft()
    with patch.object(QMessageBox, 'question', side_effect=AssertionError('Saved draft must close without prompting')):
        assert reopened.close()
    # 退出再进入编辑不能重新取首格白色。
    next_main.result = Result(processed_rgb=np.full((12, 16, 3), 255, np.uint8))
    next_main.mode = 4
    next_main.open_editor()
    editing = next_main.editors[0]
    assert editing.canvas.color == (12, 34, 56)
    editing.canvas._paint((0, 0))
    with patch.object(QMessageBox, 'warning'), patch('terraria_pixel.editor_window.save_draft', side_effect=OSError('full')), \
            patch.object(QFileDialog, 'getSaveFileName', return_value=(str(Path(temporary) / 'fail.tpdraft'), '')):
        assert not editing.save_draft()
    assert editing.canvas_model.dirty and editing.isVisible()
    editing.apply_button.click()
    editing.close_button.click()
    # PNG也能直接导入编辑，不运行转换/缩小。
    image_path = Path(temporary) / 'import.png'
    Image.fromarray(pixels).save(image_path)
    with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(image_path), '')):
        next_main.open_draft()
    imported = next_main.editors[0]
    np.testing.assert_array_equal(imported.canvas_model.rgb, pixels)
    imported.close()
    next_main.close()
print('Editor draft UI OK: eyedropper / shared color and focus commit / square swatches / RGB preview / save-on-close / cancel and failure preservation / reopen / pixel image import')
