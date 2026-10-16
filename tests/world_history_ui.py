"""真实Qt流程：统一入口、连续WLD导入后重开、失败与取消不留假记录。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton
from terraria_pixel.desktop import MainWindow, HistoryDialog, configure_app
from terraria_pixel.formats import ConversionCancelled
from terraria_pixel.history import HistoryStore, load_record
from terraria_pixel.world_dialog import WorldImportDialog
from test_world import fixture
from test_world_history import sample_result

app = QApplication.instance() or QApplication([])
configure_app(app)


def wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('world/history UI timed out')
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    store = HistoryStore(root / 'history.json', root / 'output')
    artwork = sample_result()
    main = MainWindow()
    main.base_dir = lambda: root
    main.history = store
    main.output_input.setText(str(store.default_root))
    main.result = artwork
    main._show_result()
    main.show()
    assert main.history_button.text() == '历史记录 / 草稿'
    assert not any(b.text() == '草稿' for b in main.findChildren(QPushButton))
    source = fixture(root / '世界.wld', width=20, height=16)
    existing_backup = root / '世界.wld.bak'
    existing_backup.write_bytes(b'user backup must stay')
    outcomes, warnings = [], []
    with patch.object(QMessageBox, 'warning', side_effect=lambda *args: warnings.append(args[-1])):
        dialog = WorldImportDialog(artwork, parent=main)
        dialog.saved.connect(outcomes.append)
        dialog.saved.connect(main._world_saved)
        dialog.show()
        dialog.load_path(source)
        wait_for(lambda: dialog.worker is None)
        for index, version in enumerate(('fine', 'wall', 'map')):
            dialog.version_input.setCurrentIndex(dialog.version_input.findData(version))
            dialog.coating_input.setChecked(index != 1)
            dialog._picked(2 + index, 3)
            if index < 2:
                dialog.direct_button.click()
            else:
                target = root / '另存世界.wld'
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
                    dialog.save_button.click()
            wait_for(lambda: dialog.worker is None)
            assert not warnings, warnings
            assert len(store.entries()) == index + 1
            saved = outcomes[-1]['record']
            restored = load_record(saved.out_dir)
            np.testing.assert_array_equal(restored.processed_rgb, artwork.processed_rgb)
            details = restored.processing['world_import']
            assert details['version'] == version and details['x'] == 2 + index
            assert details['y'] == 3 and details['coating'] == (index != 1)
            assert details['overwrite'] == (index < 2)
            assert dialog.isVisible() and main.isVisible()
        assert existing_backup.read_bytes() == b'user backup must stay'
        assert list(root.glob('*.bak')) == [existing_backup]
        assert not list(root.rglob('*.TEditSch'))
        # 保存失败/取消均不能增加记录，也不能修改世界。
        previous = dialog.document.path.read_bytes()
        count = len(store.entries())
        with patch('terraria_pixel.world_dialog.import_into_world', side_effect=PermissionError('locked world')):
            dialog.direct_button.click()
            wait_for(lambda: dialog.worker is None)
        assert len(store.entries()) == count and warnings
        assert dialog.document.path.read_bytes() == previous
        warnings.clear()
        with patch('terraria_pixel.world_dialog.import_into_world', side_effect=ConversionCancelled()):
            dialog.direct_button.click()
            wait_for(lambda: dialog.worker is None)
        assert len(store.entries()) == count and not warnings
        # 世界已成功写入、历史保存失败时，保留成功状态并明确单独提示。
        dialog._picked(8, 3)
        with patch('terraria_pixel.world_dialog.save_world_import_record', side_effect=PermissionError('history locked')):
            dialog.direct_button.click()
            wait_for(lambda: dialog.worker is None)
        assert len(store.entries()) == count
        assert dialog.document.path.read_bytes() != previous
        assert outcomes[-1]['record'] is None and outcomes[-1]['history_error']
        assert '无需再次导入' in warnings[-1]
        assert '世界已保存' in dialog.status.text()
        warnings.clear()
        # 索引失败仍保留可导入的作品文件，不误报世界失败。
        with patch.object(store, 'remember', side_effect=PermissionError('index locked')):
            dialog.direct_button.click()
            wait_for(lambda: dialog.worker is None)
        assert outcomes[-1]['record'] is not None
        assert len(store.entries()) == count + 1
        assert '作品数据已保存在' in warnings[-1]
        warnings.clear()
        dialog.reject()
    # 模拟重启，再通过统一历史窗口打开本次地图记录，不依赖世界文件。
    main.close()
    source.unlink()
    target.unlink()
    reopened = MainWindow()
    reopened.base_dir = lambda: root
    reopened.history = HistoryStore(store.path, store.default_root)
    reopened.output_input.setText(str(store.default_root))
    reopened.show()
    chosen = outcomes[2]['record'].out_dir

    def open_record():
        history = app.activeModalWidget()
        assert isinstance(history, HistoryDialog) and history.tabs.count() == 2
        for row in range(history.list.count()):
            if Path(history.list.item(row).toolTip().splitlines()[-1]) == chosen:
                history.list.setCurrentRow(row)
                history.open_button.click()
                return
        raise AssertionError('imported artwork absent from history')

    QTimer.singleShot(0, open_record)
    reopened.history_button.click()
    wait_for(lambda: reopened.worker is None)
    assert reopened.mode == 5
    np.testing.assert_array_equal(reopened.result.grid_map, artwork.grid_map)
    np.testing.assert_array_equal(reopened.result.processed_rgb, artwork.processed_rgb)
    reopened.edit_button.click()
    assert reopened.editors and reopened.editors[0].canvas_model.target == 'map'
    reopened.editors[0].close()
    app.processEvents()
    shots = Path(__file__).resolve().parents[2] / '.tmp/world-history-ui'
    shots.mkdir(exist_ok=True)
    reopened.grab().save(str(shots / 'merged-history.png'))
    reopened.close()
print('World history UI: direct/save-as, exact snapshots, restart/open/edit, no backups, failure/cancel/index error PASS')
