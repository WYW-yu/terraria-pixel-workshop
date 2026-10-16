"""可调整/隐藏面板、全屏和稳定网格点击区域的桌面验证。"""
import os
import sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from terraria_pixel.desktop import MainWindow, configure_app, ExportDialog
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.image_io import load_image_rgb

app = QApplication([])
configure_app(app)
output = Path(__file__).resolve().parents[2] / ".tmp" / "desktop-verification"
source = output / "山间小屋.png"
window = MainWindow()
window.show()
window.result = prepare_preview(source, width=64)
window.source_rgb = load_image_rgb(source)
window.source_path = source
window.source_size = (768, 576)
window._show_result()
app.processEvents()
assert not hasattr(window, "report_button")
assert not hasattr(window, "grid_status_label")
assert window.details_panel.isHidden()
initial = window.canvas.size()
window.materials_toggle.setChecked(True)
app.processEvents()
assert window.details_panel.isVisible()
assert window.canvas.height() < initial.height()
window.body_splitter.setSizes([410, 990])
app.processEvents()
assert window.sidebar_panel.width() > 350
window.workspace_splitter.setSizes([500, 300])
app.processEvents()
assert window.details_panel.height() > 200
window.focus_preview()
app.processEvents()
assert window.sidebar_panel.isHidden() and window.details_panel.isHidden()
assert window.canvas.width() > initial.width()
assert window.canvas.height() >= initial.height()
window.grab().save(str(output / "desktop-focus-blue.png"))
window.canvas.set_zoom(20)
app.processEvents()
position = window.grid_toggle.mapToGlobal(window.grid_toggle.rect().center())
for _ in range(8):
    QTest.mouseClick(window.grid_toggle, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.grid_toggle.mapToGlobal(window.grid_toggle.rect().center()) == position
window.toggle_fullscreen()
app.processEvents()
assert window.isFullScreen()
QTest.keyClick(window, Qt.Key.Key_Escape)
app.processEvents()
assert not window.isFullScreen()
window.settings_toggle.setChecked(True)
window.materials_toggle.setChecked(True)
window.resize(960, 720)
app.processEvents()
assert window.canvas.width() >= 300 and window.canvas.height() >= 210
window.grab().save(str(output / "desktop-small-blue.png"))
export = ExportDialog(parent=window)
export.resize(620, 480)
export.show()
app.processEvents()
assert export.width() == 620
export.close()
window.close()
print("Layout OK: moon blue / background / splitter resizing / hidden panels / focus / fullscreen / fixed grid click position / resizable dialogs")
