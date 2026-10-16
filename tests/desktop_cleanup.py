"""实际窗口验证删除确认、清空、当前作品状态和网格绘制。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from terraria_pixel.desktop import MainWindow, HistoryDialog, configure_app, PreviewCanvas
from terraria_pixel.history import HistoryStore
from terraria_pixel.pipeline import prepare_preview, export_preview

app = QApplication([])
configure_app(app)
screens = Path(__file__).resolve().parents[2] / ".tmp" / "desktop-verification"
screens.mkdir(parents=True, exist_ok=True)


def answer_confirmation(confirm):
    def answer():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        assert "无法撤销" in dialog.informativeText()
        assert "原始图片" in dialog.informativeText()
        assert dialog.detailedText()
        for choice in dialog.buttons():
            if choice.text() == ("删除记录和文件" if confirm else "取消"):
                choice.click()
                return
        raise AssertionError("Confirmation button missing")
    QTimer.singleShot(0, answer)


with tempfile.TemporaryDirectory(dir=screens.parent, prefix="cleanup-check-") as temporary:
    root = Path(temporary)
    source = root / "source.png"
    Image.new("RGB", (10, 8), "#449977").save(source)
    preview = prepare_preview(source, width=10)
    a = export_preview(preview, out_dir=root / "out", make_schematic=True)
    b = export_preview(preview, out_dir=root / "out", versions=("wall",))
    a_directory, b_directory = a.out_dir, b.out_dir
    store = HistoryStore(root / "index.json", root / "out")
    store.remember(a.out_dir)
    store.remember(b.out_dir)
    window = MainWindow()
    window.history = store
    window.output_input.setText(str(root / "out"))
    window.result = a
    window.source_rgb = preview.source_preview
    window._show_result()
    window.show()
    app.processEvents()
    dialog = HistoryDialog(store, str(root / "out"), window)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(screens / "desktop-history-cleanup.png"))
    answer_confirmation(False)
    dialog.delete_selected()
    assert dialog.list.count() == 2
    assert a.out_dir.exists() and b.out_dir.exists()
    answer_confirmation(True)
    dialog.delete_selected()
    assert dialog.list.count() == 1
    assert len(dialog.deleted_directories) == 1
    assert source.is_file()
    dialog.close()

    # 真实主窗口打开历史，清空剩余作品，再关闭历史窗口。
    def clear_and_close():
        history = app.activeModalWidget()
        assert isinstance(history, HistoryDialog)
        answer_confirmation(True)
        history.clear_all()
        assert history.list.count() == 0
        assert not history.clear_button.isEnabled()
        history.reject()
    QTimer.singleShot(0, clear_and_close)
    window.show_history()
    assert store.entries() == []
    assert not hasattr(window, "report_button")
    assert not window.folder_button.isEnabled()
    assert window.result.out_dir is None
    assert not a_directory.exists() and not b_directory.exists()
    assert source.is_file()
    window.grid_toggle.setChecked(True)
    window.tab_group.button(4).click()
    assert window.canvas.cell_shape == (8, 10)
    assert window.grid_toggle.isEnabled()
    window.tab_group.button(0).click()
    assert not window.grid_toggle.isEnabled()
    window.close()

# 像素验证：在明暗色块上绘制真实网格；过小时不画密集线。
canvas = PreviewCanvas()
canvas.resize(300, 210)
rgb = np.full((8, 10, 3), 240, dtype=np.uint8)
rgb[:, 5:] = 20
canvas.set_image(rgb, cell_shape=(8, 10))
canvas.show()
canvas.set_zoom(10)
app.processEvents()
canvas.show_grid = False
without = canvas.grab().toImage()
canvas.show_grid = True
canvas.update()
app.processEvents()
with_grid = canvas.grab().toImage()
rect = canvas.image_rect()
for column in (2, 7):
    x, y = round(rect.left() + column * 10), round(rect.top() + 15)
    assert without.pixelColor(x, y) != with_grid.pixelColor(x, y)
assert canvas.grid_status() == "网格已显示"
canvas.grab().save(str(screens / "desktop-grid-visible.png"))
canvas.set_zoom(5)
app.processEvents()
assert canvas.grid_status() == "请放大以显示网格"
canvas.show_grid = False
small_without = canvas.grab().toImage()
canvas.show_grid = True
canvas.update()
app.processEvents()
assert small_without == canvas.grab().toImage()
canvas.close()
print("Desktop cleanup OK: cancel preserves files / selected delete / clear all / current report disabled / source preserved")
print("Grid OK: visible on light and dark cells / zoom threshold hint / processed image supported / original disabled")
