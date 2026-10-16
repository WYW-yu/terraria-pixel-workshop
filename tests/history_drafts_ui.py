"""通过历史窗口真实控件恢复草稿，保留像素/透明层/材料/画具。"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from terraria_pixel.desktop import MainWindow, HistoryDialog, configure_app
from terraria_pixel.drafts import Draft, save_draft
from terraria_pixel.draft_paths import draft_folder, remember_draft, recent_drafts
from terraria_pixel.editor import EditCanvas
from terraria_pixel.history import HistoryStore
from terraria_pixel.pipeline import prepare_preview, export_preview

app = QApplication([])
configure_app(app)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    main = MainWindow()
    main.base_dir = lambda: root
    main.history = HistoryStore(root/'历史记录.json', root/'输出')
    main.output_input.setText(str(root/'输出'))
    main.show()
    pixel_canvas = EditCanvas.blank(6, 5)
    pixel_canvas.set_cell(2, 3, rgb=(12, 34, 56, 0))
    pixel = draft_folder(root)/'未完成.TPDRAFT'
    save_draft(pixel, Draft(pixel_canvas, color=(12,34,56,0), tool='fill', selection=(1,1,4,4)))
    source = root/'source.png'
    Image.new('RGB', (6,5), 'red').save(source)
    preview = prepare_preview(source, width=6)
    result = export_preview(preview, out_dir=root/'输出')
    main.history.remember(result.out_dir)
    material_canvas = EditCanvas.from_result(preview, 'wall')
    material = root/'external'/'墙画草稿.tpdraft'
    save_draft(material, Draft(material_canvas))
    remember_draft(root, material)
    original = {p: p.read_bytes() for p in (pixel, material)}

    # Open default and remembered external drafts through the actual modal history entry.
    for path, canvas in ((pixel,pixel_canvas),(material,material_canvas)):
        def choose(path=path):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, HistoryDialog)
            assert dialog.list.count() == 1
            assert dialog.draft_list.count() == 2
            dialog.tabs.setCurrentIndex(1)
            for row in range(dialog.draft_list.count()):
                if dialog.draft_list.item(row).text() == path.name:
                    dialog.draft_list.setCurrentRow(row)
                    break
            QTest.mouseClick(dialog.open_draft_button, Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, choose)
        main.show_history()
        editor = main.editors[0]
        np.testing.assert_array_equal(editor.canvas_model.rgb, canvas.rgb)
        if canvas.indices is not None:
            np.testing.assert_array_equal(editor.canvas_model.indices, canvas.indices)
        else:
            assert editor.canvas.color == (12,34,56,0)
            assert editor.canvas.tool == 'fill'
        editor.close()
        app.processEvents()

    # Import a previously unknown external file using the real history dialog button.
    imported = root/'new-location'/'导入.tpdraft'
    save_draft(imported, Draft(pixel_canvas))
    def import_other():
        dialog = app.activeModalWidget()
        dialog.tabs.setCurrentIndex(1)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(imported),'')):
            dialog.import_draft_button.click()
    QTimer.singleShot(0, import_other)
    main.show_history()
    assert main.editors and imported in recent_drafts(root)
    main.editors[0].close()
    app.processEvents()

    # Corrupt draft gives a readable warning without opening an editor or modifying files.
    corrupt = root/'bad.tpdraft'
    corrupt.write_bytes(b'not a draft')
    warnings = []
    with patch.object(QMessageBox, 'warning', side_effect=lambda *args: warnings.append(args)):
        main.open_draft(filename=corrupt)
    assert warnings and not main.editors and corrupt.read_bytes() == b'not a draft'
    assert {p:p.read_bytes() for p in original} == original
    dialog = HistoryDialog(main.history,str(root/'输出'),main,draft_base=root)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    app.processEvents()
    output = Path(__file__).resolve().parents[2]/'.tmp/desktop-verification'
    output.mkdir(parents=True,exist_ok=True)
    dialog.grab().save(str(output/'v471-history-drafts.png'))
    dialog.close()
    main.close()
print('History drafts: list, import, RGBA/material restoration, damaged file and unchanged user files OK')
