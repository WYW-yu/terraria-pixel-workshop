"""离屏走完世界选择、定位、版本切换、后台写入、错误与取消流程。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QFileDialog, QDialog, QMessageBox
from PySide6.QtTest import QTest
from PIL import Image
import numpy as np

from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.world import load_world
from terraria_pixel.world_dialog import WorldImportDialog
from test_world import fixture, independent_tiles


app = QApplication.instance() or QApplication([])
configure_app(app)


def wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('世界导入界面处理超时')
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    image = root / 'source.png'
    Image.new('RGB', (2, 2), 'red').save(image)
    result = prepare_preview(image, width=2, coating=False)
    source = fixture(root / 'world.wld', width=20, height=16)
    original = source.read_bytes()
    errors = []
    from terraria_pixel.history import HistoryStore
    history = HistoryStore(root / 'history.json', root / 'output')
    with patch.object(QMessageBox, 'warning', side_effect=lambda *args: errors.append(args[-1])):
        for version in ('fine', 'wall', 'map'):
            dialog = WorldImportDialog(result, version, history=history)
            dialog.show()
            app.processEvents()
            assert dialog.coating_input.isChecked(), '世界导入应默认添加夜明涂层，不沿用作品的关闭状态'
            for target_version in ('fine', 'wall', 'map', version):
                dialog.version_input.setCurrentIndex(dialog.version_input.findData(target_version))
                assert dialog.coating_input.isChecked(), '切换材料版本不能取消夜明涂层'
            assert not dialog.save_button.isEnabled()
            dialog.load_path(source)
            assert dialog.worker is not None and not dialog.browse_button.isEnabled()
            assert not dialog.coating_input.isEnabled(), '处理中禁止修改夜明选项'
            wait_for(lambda: dialog.worker is None)
            assert dialog.document and dialog.save_button.isEnabled(), errors
            assert dialog.version_input.currentData() == version
            rect = dialog.view.world_rect()
            QTest.mouseClick(dialog.view, Qt.MouseButton.LeftButton, pos=QPoint(int(rect.center().x()), int(rect.center().y())))
            assert abs(dialog.x_input.value() - 10) <= 1
            assert abs(dialog.y_input.value() - 8) <= 1
            dialog.x_input.setValue(19)
            assert not dialog.save_button.isEnabled()
            dialog.x_input.setValue(0)
            dialog.y_input.setValue(1)
            assert dialog.save_button.isEnabled()
            target = root / (version + '.wld')
            with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
                dialog.save_button.click()
            wait_for(lambda: dialog.worker is None)
            assert dialog.saved_path == target
            assert dialog.isVisible(), '保存后导入窗口应继续打开'
            from terraria_pixel.world import material_version
            grid, palette = material_version(result, version)

            def check_saved_coating(path, enabled):
                parsed = independent_tiles(load_world(path, overview=False))
                for gx in (0, 1):
                    for gy in (0, 1):
                        candidate = palette.candidates[int(grid[gy, gx])]
                        wall = 'wall_id' in candidate.block
                        assert (parsed[gx][gy + 1][0] is None) == wall
                        assert parsed[gx][gy + 1][6] == ((16 if wall else 8) if enabled else 0), (version, enabled)

            check_saved_coating(target, True)
            for enabled in (False, True):
                dialog.coating_input.setChecked(enabled)
                dialog.direct_button.click()
                wait_for(lambda: dialog.worker is None)
                assert dialog.isVisible()
                assert dialog.coating_input.isEnabled()
                check_saved_coating(target, enabled)
            dialog.coating_input.setChecked(False)
            target_off = root / (version + '-off.wld')
            with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target_off), '')):
                dialog.save_button.click()
            wait_for(lambda: dialog.worker is None)
            assert dialog.saved_path == target_off
            check_saved_coating(target_off, False)
            assert result.processing['coating'] is False, '此次导入选项不能修改原作品设置'
            assert source.read_bytes() == original
            dialog.reject()
        assert not errors, errors

        dialog = WorldImportDialog(result)
        dialog.show()
        dialog.load_path(source)
        dialog.reject()  # 正在读世界时关闭，先取消线程再退出。
        wait_for(lambda: dialog.worker is None)
        assert not dialog.isVisible()
        assert dialog.saved_path is None

        dialog = WorldImportDialog(result)
        dialog.show()
        dialog.load_path(root / 'missing.wld')
        wait_for(lambda: dialog.worker is None)
        assert errors and dialog.document is None
        assert not dialog.save_button.isEnabled()
        dialog.reject()

    main = MainWindow()
    main.result = result
    main.preview_dirty = False
    main._show_result()
    main._update_png_action()
    assert main.world_button.isEnabled()
    main._set_busy(True)
    assert not main.world_button.isEnabled()
    main._set_busy(False)
    assert main.world_button.isEnabled()
    main.preview_dirty = True
    main._update_png_action()
    assert not main.world_button.isEnabled()
    main.close()
print('世界导入界面：三版默认夜明、开启/关闭的直接保存与另存为、鼠标定位、边界检查、错误与取消线程全部通过')
