"""页面提示、当前/上次颜色与启动延迟加载回归。"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtTest import QTest
from terraria_pixel.desktop import MainWindow, configure_app, ExportDialog
assert 'terraria_pixel.pipeline' not in sys.modules
assert 'terraria_pixel.calibrated_colors' not in sys.modules
app = QApplication([])
configure_app(app)
main = MainWindow()
main.show()
assert {b.text() for b in main.tab_group.buttons()} == {'原图', '像素画', '混合版', '背景墙版', '地图版'}
assert set(ExportDialog().choices) == {'fine', 'wall', 'map'}
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.editor import EditCanvas
from terraria_pixel.editor_window import PixelEditorWindow
from PIL import Image
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source = root / 'source.png'
    Image.new('RGB', (8, 8), 'red').save(source)
    main.result = prepare_preview(source, width=8)
    main._show_result()
    assert '查看材料' in main.canvas.default_hint()
    main.set_mode(4)
    assert '查看材料' not in main.canvas.default_hint()
    assert '查看材料' not in main.preview_hint.toolTip()
    main.canvas.leaveEvent(None)
    assert '查看材料' not in main.preview_hint.toolTip()
    editor = PixelEditorWindow(canvas=EditCanvas.blank(8, 8), parent=main)
    main._track_editor(editor)
    panel = editor.color_panel
    panel.pick_color((255, 0, 0))
    panel.pick_color((0, 0, 255))
    assert panel.previous_rgb == (255, 0, 0)
    editor.set_tool('fill')
    assert panel.previous_rgb == (255, 0, 0)
    panel.previous_swatch.click()
    assert panel.rgb == (255, 0, 0) and editor.canvas.color == (255, 0, 0)
    assert panel.previous_rgb == (0, 0, 255)
    main.base_dir = lambda: root
    captured = []
    def picker(*args):
        captured.append(Path(args[2]))
        assert (root / '像素画草稿').is_dir()
        return '', ''
    with patch.object(QFileDialog, 'getSaveFileName', side_effect=picker):
        editor.save_draft()
    assert captured[0].parent == root / '像素画草稿'
    app.processEvents()
    output = Path(__file__).resolve().parents[2] / '.tmp/desktop-verification'
    output.mkdir(parents=True, exist_ok=True)
    main.grab().save(str(output / 'v46-current-previous.png'))
    from terraria_pixel.drafts import fingerprint
    editor._draft_checkpoint = fingerprint(editor.canvas_model)
    editor.close()
main.close()
print('Version UI, hints, color recall, draft folder and lazy startup OK')
