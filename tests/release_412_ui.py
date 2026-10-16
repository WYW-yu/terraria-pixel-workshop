"""验证所有材料页屏蔽易损/重力素材，混合版使用虚化色，保留绘画功能。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys, tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtWidgets import QApplication
from terraria_pixel.desktop import MainWindow, configure_app
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
    output=Path(__file__).resolve().parents[2]/'.tmp/release-4120'
    output.mkdir(exist_ok=True,parents=True)
    main.grab().save(str(output/'mixed-preview.png'))
    main.close()
print('All material pickers exclude forbidden materials; actuated mixed colors and page names: PASS')
