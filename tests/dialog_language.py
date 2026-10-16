"""真实Qt弹窗中文文本及保存/放弃/取消的行为。"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.editor import EditCanvas
from terraria_pixel.editor_window import PixelEditorWindow
from terraria_pixel.drafts import load_draft

app = QApplication([])
configure_app(app)
configure_app(app)  # 重复配置不重复装载翻译和过滤器。
assert app._chinese_translator is not None
output = Path(__file__).resolve().parents[2] / '.tmp/desktop-verification'
output.mkdir(parents=True, exist_ok=True)

def answer(standard, expected, screenshot=None):
    def click():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        labels = {dialog.standardButton(b): b.text() for b in dialog.buttons()}
        assert labels == expected, labels
        if screenshot:
            dialog.grab().save(str(output / screenshot))
        dialog.button(standard).click()
    QTimer.singleShot(30, click)

with tempfile.TemporaryDirectory(dir=output) as temporary:
    main = MainWindow()
    main.show()
    editor = PixelEditorWindow(canvas=EditCanvas.blank(16, 12), parent=main)
    main._track_editor(editor)
    app.processEvents()
    editor.canvas_model.set_cell(2, 3, rgb=(12, 34, 56))
    expected = {QMessageBox.StandardButton.Save: '保存草稿',
                QMessageBox.StandardButton.Discard: '放弃改动', QMessageBox.StandardButton.Cancel: '取消'}
    answer(QMessageBox.StandardButton.Cancel, expected, 'draft-close-chinese.png')
    assert not editor.close() and editor.isVisible()
    # 点保存但取消文件选择，也必须保留画面。
    answer(QMessageBox.StandardButton.Save, expected)
    with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
        assert not editor.close()
    path = Path(temporary) / '草稿.tpdraft'
    answer(QMessageBox.StandardButton.Save, expected)
    with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
        assert editor.close()
    assert load_draft(path).canvas.color_at(2, 3) == (12, 34, 56)
    app.processEvents()
    editor = PixelEditorWindow(canvas=EditCanvas.blank(16, 12), parent=main)
    main._track_editor(editor)
    editor.canvas_model.set_cell(0, 0, rgb=(1, 2, 3))
    answer(QMessageBox.StandardButton.Discard, expected)
    assert editor.close()
    answer(QMessageBox.StandardButton.No, {QMessageBox.StandardButton.Yes: '是', QMessageBox.StandardButton.No: '否'})
    assert QMessageBox.question(main, '替换已有草稿？', '是否替换？') == QMessageBox.StandardButton.No
    answer(QMessageBox.StandardButton.Ok, {QMessageBox.StandardButton.Ok: '确定'})
    QMessageBox.warning(main, '提示', '测试中文按钮')
    main.close()
print('Chinese dialogs OK: save draft / discard / cancel / yes / no / OK; real close actions retain their behavior')
