"""验证所有材料页屏蔽易损/重力素材，混合版使用虚化色，保留绘画功能。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys, tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtWidgets import QApplication, QLabel, QSpinBox
from terraria_pixel.desktop import MainWindow, configure_app, ExportDialog
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.editor_window import PixelEditorWindow
from terraria_pixel.material_rules import permitted, validate_grid
from terraria_pixel.material_library import ACTUATED_MODEL

app=QApplication.instance() or QApplication([])
configure_app(app)
with tempfile.TemporaryDirectory() as tmp:
    source=Path(tmp)/'source.png'
    Image.new('RGB',(6,4),(200,120,80)).save(source)
    result=prepare_preview(source,width=6)
    main=MainWindow()
    main.result=result
    main._show_result()
    main.show()
    assert {b.text() for b in main.tab_group.buttons()} == {'原图','像素画','混合版','背景墙版','地图版'}
    assert main.version_label.text() == 'v5.2'
    assert main.export_button.text() == '保存TEdit文件'
    assert set(ExportDialog().choices) == {'fine','wall','map'}
    assert result.processing['actuated_tiles'] is True
    for target in ('fine','wall','map'):
        editor=PixelEditorWindow(result,target)
        editor.show()
        app.processEvents()
        model=editor.canvas_model
        validate_grid(model.indices,model.palette)
        assert editor._palette_items
        for index in editor._palette_items:
            assert permitted(model.palette.candidates[index].block)
        for index,candidate in enumerate(model.palette.candidates):
            assert (index in editor._palette_items)==permitted(candidate.block)
            if target=='fine' and 'tile_id' in candidate.block:
                assert candidate.block['color_model']==ACTUATED_MODEL
        editor._allow_close=True
        editor.close()
    main.set_mode(1)
    app.processEvents()
    output=Path(__file__).resolve().parents[2]/'.tmp/release-51'
    output.mkdir(exist_ok=True,parents=True)
    main.grab().save(str(output/'mixed-preview.png'))
    from terraria_pixel.world_dialog import WorldImportDialog
    dialog=WorldImportDialog(result)
    dialog.show()
    app.processEvents()
    assert dialog.version_input.count() == 3
    assert dialog.coating_input.isChecked()
    assert dialog.back_button.height() == dialog.direct_button.height() == dialog.save_button.height()
    assert dialog.direct_button.width() == dialog.save_button.width()
    assert all(not w.isVisible() for w in dialog.findChildren(QSpinBox))
    assert all('物块已虚化' not in w.text() and '左上角 X' not in w.text() for w in dialog.findChildren(QLabel))
    dialog._picked(23,45)
    assert (dialog.view.x,dialog.view.y)==(23,45)
    dialog.grab().save(str(output/'world-import.png'))
    dialog.reject()
    main.close()
print('All material pickers exclude forbidden materials; actuated mixed colors and page names: PASS')

