"""预览页常显说明、三版介绍、5.2版本与署名的实际布局检查。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel
from terraria_pixel.desktop import MainWindow, ExportDialog, configure_app
from terraria_pixel.formats import PREVIEW_DESCRIPTIONS, VERSION_DESCRIPTIONS
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.world_dialog import WorldImportDialog

app = QApplication.instance() or QApplication([])
configure_app(app)
output = Path(__file__).resolve().parents[2] / '.tmp/release51/ui'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    image = Path(directory) / 'source.png'
    Image.new('RGB', (7, 5), (180, 130, 90)).save(image)
    result = prepare_preview(image, width=7)
    main = MainWindow()
    main.source_rgb = result.processed_rgb
    main.result = result
    main._show_result()
    main.show()
    assert main.version_label.text() == 'v5.2'
    assert main.author_label.text() == 'byWYW雨'
    assert main.author_label.geometry().left() > main.version_label.geometry().right()
    for size in ((1400, 900), (1024, 720)):
        main.resize(*size)
        for mode, text in PREVIEW_DESCRIPTIONS.items():
            main.tab_group.button(mode).click()
            app.processEvents()
            description = main.preview_description
            assert description.text() == text
            assert not main.tab_group.button(mode).toolTip()
            assert not main.preview_state.toolTip()
            assert description.isVisible() and description.wordWrap()
            bottom = main.tab_group.button(mode).mapTo(main.preview_card, QPoint(0, main.tab_group.button(mode).height())).y()
            top = description.mapTo(main.preview_card, QPoint(0, 0)).y()
            assert top >= bottom
            assert description.height() >= description.heightForWidth(description.width())
            main.grab().save(str(output / f'preview-{size[0]}-{mode}.png'))
    export = ExportDialog()
    export.show()
    app.processEvents()
    assert set(VERSION_DESCRIPTIONS.values()).issubset({label.text() for label in export.findChildren(QLabel)})
    assert export.choices['map'].text().startswith('地图版')
    export.grab().save(str(output / 'export.png'))
    export.close()
    world = WorldImportDialog(result, 'fine')
    assert world.version_input.itemText(world.version_input.findData('map')) == '地图版'
    world.show()
    for key, text in VERSION_DESCRIPTIONS.items():
        world.version_input.setCurrentIndex(world.version_input.findData(key))
        app.processEvents()
        assert world.version_description.text() == text
    world.grab().save(str(output / 'world.png'))
    world.close()
    main.close()
print('5.2 preview descriptions below tabs, exact material descriptions, footer and layout: PASS')
