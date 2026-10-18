"""真实线程走完像素预览、编辑确认、三版独立编辑和取消/重新生成。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.formats import ConversionCancelled

app = QApplication.instance() or QApplication([])
configure_app(app)

def wait(main):
    deadline = time.monotonic() + 40
    while main.worker is not None:
        assert time.monotonic() < deadline, '处理超时'
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()

output = Path(__file__).resolve().parents[2] / '.tmp/workflow51/ui'
output.mkdir(exist_ok=True, parents=True)
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    image = root / 'source.png'
    Image.fromarray(np.random.default_rng(516).integers(0, 256, (7, 9, 3), np.uint8)).save(image)
    main = MainWindow()
    assert main.merge_input.currentData() == 1.5
    main.base_dir = lambda: root
    main._source_loaded((image, np.asarray(Image.open(image)), None))
    main.width_input.setText('9')
    main.gamma_input.setValue(1.7)
    main.show()
    errors = []
    with patch.object(QMessageBox, 'warning', side_effect=lambda *args: errors.append(args[-1])):
        with patch('terraria_pixel.pipeline.mixed_palette', side_effect=AssertionError('不能提前加载材料库')), \
                patch('terraria_pixel.pipeline.match_map', side_effect=AssertionError('不能提前匹配地图')):
            main.generate_button.click()
            wait(main)
        assert not errors, errors
        assert main.mode == 4 and main.result.grid is None
        assert not main.png_button.isHidden() and main.png_button.isEnabled()
        assert main.confirm_button.isEnabled() and main.edit_button.isEnabled()
        assert not main.export_button.isEnabled() and not main.world_button.isEnabled()
        assert not any(main.tab_group.button(mode).isEnabled() for mode in (1, 3, 5))
        main.grab().save(str(output / 'pixel-first.png'))
        main.edit_button.click()
        editor = main.editors[0]
        assert editor.target == 'pixel'
        editor.canvas_model.set_cell(3, 2, rgb=(17, 63, 91))
        editor.apply()
        expected_pixels = main.result.processed_rgb.copy()
        editor.close()
        app.processEvents()
        assert not main.editors and main.confirm_button.isEnabled()
        # 原图已删除也能确认；第二步不得读取图片或重复像素化。
        image.unlink()
        with patch('terraria_pixel.pipeline.pixelate', side_effect=AssertionError('不得二次处理像素画')):
            main.confirm_button.click()
            wait(main)
        assert not errors, errors
        np.testing.assert_array_equal(main.result.processed_rgb, expected_pixels)
        assert all(main.tab_group.button(mode).isEnabled() for mode in (1, 3, 5))
        assert main.tab_group.button(5).text() == '地图版'
        assert any('tile_id' in b for b in main.result.palette_map.blocks)
        assert any('wall_id' in b for b in main.result.palette_map.blocks)
        assert not main.confirm_button.isEnabled()
        assert main.export_button.isEnabled() and main.world_button.isEnabled()
        assert main.result.processing['material_merge'] == 1.5
        assert set(main.result.processing['material_merge_report']) == {'fine', 'wall', 'map'}
        assert '混合版' in main.merge_result_note.text()
        main.grab().save(str(output / 'materials-ready.png'))
        for mode, target, attr in ((1, 'fine', 'grid'), (3, 'wall', 'grid_wall'), (5, 'map', 'grid_map')):
            snapshots = {key: getattr(main.result, key).copy() for key in ('grid', 'grid_wall', 'grid_map', 'processed_rgb')}
            main.tab_group.button(mode).click()
            assert main.png_button.isHidden()
            with patch('terraria_pixel.png_export.export_png', side_effect=AssertionError('材料页不导出PNG')):
                main.export_pixel_png()
            main.edit_button.click()
            editor = main.editors[0]
            assert editor.target == target and not editor.convert_button.isVisible()
            if target == 'map':
                assert editor.palette_name.text() == '地图版（物块和背景墙地图色）'
            editor.canvas_model.set_cell(1, 1, rgb=(0, 0, 0, 0))
            editor.apply()
            editor.close()
            app.processEvents()
            assert getattr(main.result, attr)[1, 1] == -1
            for key, array in snapshots.items():
                if key != attr:
                    np.testing.assert_array_equal(getattr(main.result, key), array)
            assert main.export_button.isEnabled()
        # 像素编辑后的应用使材料过期，取消重新生成不会丢当前像素或旧版笔画。
        main.tab_group.button(4).click()
        main.edit_button.click()
        editor = main.editors[0]
        editor.canvas_model.set_cell(3, 2, rgb=(91, 63, 17))
        editor.apply()
        assert main.result.processing['materials_stale']
        assert not main.export_button.isEnabled() and not main.world_button.isEnabled()
        prior_result = main.result
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            editor.convert()
        assert main.editors and main.result is prior_result
        # 不先应用的笔画也必须纳入编辑器的直接确认。
        editor.canvas_model.set_cell(4, 3, rgb=(8, 99, 155))
        expected_pixels = editor.canvas_model.to_array()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
                patch('terraria_pixel.pipeline.generate_material_versions', side_effect=ConversionCancelled()):
            editor.convert()
            wait(main)
        assert not main.editors and main.mode == 4
        assert all(control.isEnabled() for control in (main.settings_toggle,
            main.materials_toggle, main.focus_button, main.history_button))
        np.testing.assert_array_equal(main.result.processed_rgb, expected_pixels)
        assert main.confirm_button.isEnabled() and not main.export_button.isEnabled()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            main.confirm_button.click()
            wait(main)
        np.testing.assert_array_equal(main.result.processed_rgb, expected_pixels)
        assert not main.result.processing['materials_stale'] and main.export_button.isEnabled()
        assert all(control.isEnabled() for control in (main.settings_toggle,
            main.materials_toggle, main.focus_button, main.history_button))
        assert main.result.grid[1, 1] >= 0
        # 材料设置无需重新生成像素画。
        main.dither_input.setCurrentIndex(main.dither_input.findData('bayer'))
        assert not main.preview_dirty and main.confirm_button.isEnabled()
        assert not main.export_button.isEnabled()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            main.confirm_button.click()
            wait(main)
        np.testing.assert_array_equal(main.result.processed_rgb, expected_pixels)
        assert main.result.processing['dither'] == 'bayer'
        # 合并程度属于材料设置，不重新处理已经确认的像素画。
        main.merge_input.setCurrentIndex(main.merge_input.findData(0))
        assert not main.preview_dirty and main.confirm_button.isEnabled()
        assert not main.export_button.isEnabled() and not main.world_button.isEnabled()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            main.confirm_button.click()
            wait(main)
        assert main.result.processing['material_merge'] == 0
        assert all(r['before'] == r['after'] for r in main.result.processing['material_merge_report'].values())
        np.testing.assert_array_equal(main.result.processed_rgb, expected_pixels)
        main.merge_input.setCurrentIndex(main.merge_input.findData(3))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            main.confirm_button.click()
            wait(main)
        assert main.result.processing['material_merge'] == 3
        np.testing.assert_array_equal(main.result.processed_rgb, expected_pixels)
        assert not errors, errors
        main.tab_group.button(4).click()
        main.edit_button.click()
        editor = main.editors[0]
        editor.canvas_model.set_cell(2, 4, rgb=(127, 42, 79))
        expected_pixels = editor.canvas_model.to_array()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            editor.convert()
            wait(main)
        np.testing.assert_array_equal(main.result.processed_rgb, expected_pixels)
        assert not main.editors and main.export_button.isEnabled()
        assert all(control.isEnabled() for control in (main.settings_toggle,
            main.materials_toggle, main.focus_button, main.history_button))
        main.resize(1024, 720)
        app.processEvents()
        main.grab().save(str(output / 'workflow-small.png'))
        # 原图调整需要重新生成像素画，不能把过期预览当作已确认结果。
        main.gamma_input.setValue(1.8)
        assert main.preview_dirty and not main.confirm_button.isEnabled()
        main.close()
print('Staged GUI: pixel only, exact edited confirmation, separate versions, stale guards, cancel/retry and material settings PASS')
