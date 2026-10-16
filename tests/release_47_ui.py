"""v4.7真实控件回归：透明色、光标、PNG选项、草稿入口和多屏取色。"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QPoint, QPointF, QRect, QTimer
from PySide6.QtGui import QImage, QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QDialog
from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.editor import EditCanvas
from terraria_pixel.editor_window import PixelEditorWindow
from terraria_pixel.drafts import fingerprint
from terraria_pixel.draft_browser import DraftBrowser
from terraria_pixel.png_export import PngExportDialog
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.screen_picker import ScreenPicker

app = QApplication([]); configure_app(app)
output = Path(__file__).resolve().parents[2]/'.tmp/desktop-verification'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    main = MainWindow(); main.base_dir = lambda: root; main.show()
    assert 'by' not in main.windowTitle().lower()
    assert main.version_label.y() > main.height() * .8
    source = root/'source.png'; Image.new('RGB', (8,8), 'red').save(source)
    main.source_path=source; main.source_size=(8,8)
    main.width_input.setText('5001')
    assert main._options()['width']==5001 and main.generate_button.isEnabled()
    main.result=prepare_preview(source,width=8)
    main._show_result(prefer_pixel=True)
    assert main.mode==4
    main.canvas.set_zoom(10)
    app.processEvents()
    rect=main.canvas.image_rect()
    QTest.mouseMove(main.canvas,QPoint(int(rect.x()+15),int(rect.y()+25)))
    assert '(1, 2)' in main.preview_hint.toolTip()
    assert '#FF0000' in main.preview_hint.toolTip() and '查看材料' not in main.preview_hint.toolTip()
    main.open_editor(); editor=main.editors[0]; app.processEvents()
    assert editor.draft_button.mapTo(main,QPoint()).y() > main.height()*.7
    assert editor.draft_button.x() > editor.export_button.x()
    for name in ('brush','fill','picker'):
        editor.set_tool(name)
        assert not editor.canvas.cursor().pixmap().isNull(),name
    assert editor.screen_pick_button.isVisible()
    editor.color_panel.transparent_button.click()
    assert editor.canvas.color==(0,0,0,0)
    editor.set_tool('brush')
    editor.canvas_model.set_cell(2,2,rgb=editor.canvas.color)
    editor.canvas.rebuild(); editor._canvas_changed(); app.processEvents()
    assert editor.canvas_model.color_at(2,2)==(0,0,0,0)
    editor._refresh_after_edit()
    assert editor.color_panel.rgb==(0,0,0,0)
    # Validate actual option dialog acceptance, not a replaced export function.
    def choose_options(grid):
        def choose():
            dialog=app.activeModalWidget()
            assert isinstance(dialog,PngExportDialog)
            assert not dialog.grid.isChecked()
            dialog.grid.setChecked(grid)
            assert dialog.cell_size.isEnabled()==grid
            dialog.accept()
        QTimer.singleShot(0,choose)
    png=root/'raw.png'; choose_options(False)
    with patch.object(QFileDialog,'getSaveFileName',return_value=(str(png),'')):
        editor.export_png()
    assert np.asarray(Image.open(png))[2,2,3]==0
    gridpng=root/'grid.png'; choose_options(True)
    with patch.object(QFileDialog,'getSaveFileName',return_value=(str(gridpng),'')):
        editor.export_png()
    assert Image.open(gridpng).size==(96,96)
    # Save into an alternative folder; both open picker and library must find it.
    draft=root/'other'/'unfinished.tpdraft'
    with patch.object(QFileDialog,'getSaveFileName',return_value=(str(draft),'')):
        assert editor.save_draft()
    app.processEvents(); main.grab().save(str(output/'v47-editor.png'))
    editor.close(); app.processEvents()
    browser=DraftBrowser(root,main)
    assert browser.list.count()==1
    browser.list.setCurrentRow(0); browser.open_selected()
    assert browser.selected_path==draft
    main.open_draft(filename=draft); app.processEvents()
    editor=main.editors[0]
    assert editor.canvas_model.color_at(2,2)==(0,0,0,0)
    editor.close(); app.processEvents()
    def open_picker(*args):
        assert Path(args[2])==draft.parent
        return '', ''
    with patch.object(QFileDialog,'getOpenFileName',side_effect=open_picker):
        main.open_draft()
    # Controlled screen image tests coordinate scaling, negative screen origin, click and cancellation.
    image=QImage(200,100,QImage.Format.Format_RGB32); image.fill(QColor(10,20,30))
    image.setPixelColor(50,40,QColor(200,80,40))
    snapshot=QPixmap.fromImage(image)
    class FakeScreen:
        def geometry(self): return QRect(-100,0,100,50)
        def grabWindow(self, ident): assert ident==0; return snapshot
    picked=[]
    from terraria_pixel.editor_window import eyedropper_cursor
    with patch.object(QApplication,'screens',return_value=[FakeScreen()]):
        picker=ScreenPicker(main,eyedropper_cursor(),picked.append)
    window=picker.windows[0]
    assert window.sample(QPointF(25,20))==(200,80,40)
    QTest.mouseClick(window,Qt.MouseButton.LeftButton,pos=QPoint(25,20))
    assert picked==[(200,80,40)] and not picker.windows
    with patch.object(QApplication,'screens',return_value=[FakeScreen()]):
        picker=ScreenPicker(main,eyedropper_cursor(),picked.append)
    QTest.keyClick(picker.windows[0],Qt.Key.Key_Escape)
    assert picked==[(200,80,40)] and not picker.windows
    main.set_mode(4); app.processEvents()
    main.grab().save(str(output/'v47-pixel-preview.png'))
    main.close()
print('v4.7 UI: cursor icons / transparency / draft paths and library / coordinates / default pixel tab / PNG options / screen picker OK')
