"""离屏桌面验证，覆盖真实后台读取/转换、方案切换和取消。"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from terraria_pixel.desktop import MainWindow, configure_app, ExportDialog, HistoryDialog, QFileDialog
from terraria_pixel.history import HistoryStore
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
output = root / ".tmp" / "desktop-verification"
output.mkdir(parents=True, exist_ok=True)
app = QApplication([])
from terraria_pixel.png_export import PngExportDialog
from PySide6.QtWidgets import QDialog
PngExportDialog.exec = lambda self: QDialog.DialogCode.Accepted
configure_app(app)
window = MainWindow()
window.history = HistoryStore(output / "历史记录.json", output / "results")
window.show()
errors = []
window._failed = lambda message: errors.append(message)


def process_until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Desktop operation timed out")
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()
    assert not errors, errors


app.processEvents()
window.grab().save(str(output / "desktop-empty.png"))
demo = Image.new("RGB", (128, 96), "#c5e4de")
draw = ImageDraw.Draw(demo)
draw.rectangle((0, 55, 128, 95), fill="#32554c")
draw.rectangle((91, 12, 104, 25), fill="#fff0b5")
draw.polygon([(0, 57), (30, 27), (59, 57)], fill="#7fa5a0")
draw.polygon([(35, 58), (79, 19), (128, 61)], fill="#537b76")
draw.polygon([(67, 30), (79, 19), (93, 32), (83, 29), (77, 34)], fill="#dcece4")
draw.polygon([(50, 95), (66, 55), (75, 55), (83, 95)], fill="#7bb8b4")
for x, y in ((13, 47), (31, 60), (102, 53), (115, 69), (7, 73)):
    draw.rectangle((x + 5, y + 12, x + 7, y + 26), fill="#4f4038")
    draw.polygon([(x + 6, y), (x, y + 15), (x + 12, y + 15)], fill="#234b3c")
demo_path = output / "山间小屋.png"
draw.rectangle((31, 68, 49, 82), fill="#d3ad78")
draw.polygon([(27, 69), (40, 58), (54, 69)], fill="#8c5d4f")
draw.rectangle((38, 73, 42, 82), fill="#4f4038")
draw.rectangle((45, 72, 47, 75), fill="#f8d49b")
demo.resize((768, 576), Image.Resampling.NEAREST).save(demo_path)
window.load_source(demo_path)
process_until(lambda: not window.busy)
assert window.source_rgb is not None
window.width_input.setText("64")
window.output_input.setText(str(output / "results"))
window.sampling_input.setCurrentIndex(3)
window.color_input.setCurrentIndex(2)
window.dither_input.setCurrentIndex(1)
QTest.mouseClick(window.generate_button, Qt.MouseButton.LeftButton)
process_until(lambda: not window.busy)
assert window.result and window.result.out_dir is None
assert window.isVisible(), '生成预览后主程序应保持打开'
assert window.mode == 4
assert window.result.schematic is None
assert window.export_button.isEnabled()
assert not hasattr(window, "report_button")
assert not hasattr(window, "schematic_input")
assert window.progress_bar.isHidden()
assert [b.text() for b in sorted(window.tab_group.buttons(), key=lambda b: b.x())] == ["原图", "像素画", "混合版", "背景墙版", "地图版", "背景墙地图版"]
window.tab_group.button(4).click()
app.processEvents()
assert window.png_actions.isVisible() and window.png_button.isEnabled()
window.grid_toggle.setChecked(True)
window.canvas.set_zoom(8)
png = output / "independent-pixel-export.png"
png.unlink(missing_ok=True)
with patch.object(QFileDialog, "getSaveFileName", return_value=(str(png), "PNG 图片 (*.png)")):
    window.png_button.click()
with Image.open(png) as exported:
    assert exported.format == "PNG"
    assert np.array_equal(np.asarray(exported), window.result.processed_rgb)
assert window.result.out_dir is None
assert window.progress_bar.isHidden()
with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
    window.png_button.click()
window.grab().save(str(output / "desktop-pixel-png.png"))
window.tab_group.button(1).click()
# 动作行在 1–4 页都显示，但 PNG 导出只在「像素画」页；混合版这一页提供编辑入口。
assert window.png_actions.isVisible() and window.png_button.isHidden()
assert window.edit_button.isEnabled()
window.materials_toggle.setChecked(True)
app.processEvents()
window.grab().save(str(output / "desktop-preview.png"))
dialog = ExportDialog(True, parent=window)
dialog.show()
app.processEvents()
dialog.grab().save(str(output / "desktop-export-dialog.png"))
for choice in dialog.choices.values():
    choice.setChecked(False)
assert not dialog.save_button.isEnabled()
dialog.choices["wall"].setChecked(True)
assert dialog.selected_versions() == ("wall",)
assert dialog.save_button.isEnabled()
dialog.close()
window.save_schematics = False
def accept_save():
    current = app.activeModalWidget()
    assert isinstance(current, ExportDialog)
    assert not current.schematic.isChecked()
    # 临时冰块不能持久保存在游戏世界，另有专门测试检查其导出阻止提示。
    current.choices['map'].setChecked(False)
    current.schematic.setChecked(True)
    current.save_button.click()
QTimer.singleShot(0, accept_save)
window.choose_export()
assert window.save_schematics
assert window.progress_bar.isVisible()
process_until(lambda: not window.busy)
assert window.result.schematic.exists()
assert window.isVisible(), '生成作品后主程序应保持打开'
saved_directory = window.result.out_dir
assert window.history.entries()[0]["directory"] == saved_directory
assert window.progress_bar.value() == 100
assert window.progress_bar.isHidden()
assert window.table.rowCount() > 0
assert window.result.processing["sampling_used"] == "edge"
assert window.result.processing["color_limit"] == 16
assert window.result.processing["dither"] == "bayer"
for mode in (0, 1, 3, 4, 5):
    QTest.mouseClick(window.tab_group.button(mode), Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.mode == mode
    window.grab().save(str(output / f"desktop-mode-{mode}.png"))
    if mode in (5,):
        window.open_editor()
        editor = window.editors[-1]
        assert editor.target == 'map'
        assert all('tile_id' in b for b in editor.canvas_model.palette.blocks)
        editor.close()
window.advanced_toggle.setChecked(True)
app.processEvents()
window.settings_scroll.verticalScrollBar().setValue(window.settings_scroll.verticalScrollBar().maximum())
window.tab_group.button(1).click()
app.processEvents()
window.grab().save(str(output / "desktop-algorithm.png"))
QTest.mouseClick(window.tab_group.button(1), Qt.MouseButton.LeftButton)
window.search.setText("不存在的材料")
assert all(window.table.isRowHidden(i) for i in range(window.table.rowCount()))
window.search.clear()
window.grid_toggle.setChecked(True)
window.canvas.set_zoom(8)
app.processEvents()
window.grab().save(str(output / "desktop-grid.png"))
window.canvas.fit()
window.tab_group.button(4).click()
window.width_input.setText("0")
assert not window.generate_button.isEnabled()
assert not window.export_button.isEnabled()
assert not window.png_button.isEnabled()
window.width_input.setText("128")
assert window.generate_button.isEnabled()
window.width_input.setText("32")
window.dither_input.setCurrentIndex(2)
window.generate()
process_until(lambda: not window.busy)
assert window.result.processing["dither"] == "floyd"
window.output_input.setText(str(output / "selected-results"))
assert window.export_button.isEnabled()
window.save_current(("wall",), False)
process_until(lambda: not window.busy)
assert (window.result.out_dir / "作品数据.npz").is_file()
assert not list(window.result.out_dir.glob("*.png"))
assert not list(window.result.out_dir.glob("*.TEditSch"))
selected_directory = window.result.out_dir
previous = window.result
window.generate()
window.cancel()
process_until(lambda: not window.busy)
assert window.result is previous
assert not list((output / "results").glob(".building-*"))
# 新窗口模拟重启，从持久化索引读取结果而不是再生成一次。
reopened = MainWindow()
reopened.history = HistoryStore(window.history.path, output / "results")
reopened.show()
assert any(e["directory"] == selected_directory for e in reopened.history.entries())
reopened.open_history(selected_directory)
deadline = time.monotonic() + 30
while reopened.busy:
    assert time.monotonic() < deadline
    app.processEvents()
    QTest.qWait(10)
assert reopened.result.out_dir == selected_directory
assert reopened.result.grid is not None
assert reopened.export_button.isEnabled()
assert reopened.table.rowCount() > 0
assert reopened.result.processing["dither"] == "floyd"
reopened.tab_group.button(4).click()
history_png = output / "history-pixel-export.png"
history_png.unlink(missing_ok=True)
with patch.object(QFileDialog, "getSaveFileName", return_value=(str(history_png), "PNG 图片 (*.png)")):
    reopened.png_button.click()
assert np.array_equal(np.asarray(Image.open(history_png)), reopened.result.processed_rgb)
assert reopened.progress_bar.isHidden()
reopened.tab_group.button(3).click()
reopened.grab().save(str(output / "desktop-history-open.png"))
history_dialog = HistoryDialog(reopened.history, str(output / "results"), reopened)
history_dialog.show()
app.processEvents()
assert history_dialog.list.count() >= 2
history_dialog.grab().save(str(output / "desktop-history-dialog.png"))
history_dialog.close()
reopened.close()
window.close()
print("Desktop smoke OK: independent PNG pixels / history PNG / one schematic control / tab order / processing-only progress / cached save / search / validation / cancel")
print(output)
