"""离屏检查编辑窗口：能开、能画、能撤销、能应用回主流程（不开真窗口）。

用法：python -B tests/editor_smoke.py
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CACHE_HOME", str(Path(tempfile.gettempdir()) / "tp-qt-cache"))

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from terraria_pixel.pipeline import prepare_preview


captured = []


def main() -> int:
    app = QApplication.instance() or QApplication([])
    from terraria_pixel.png_export import PngExportDialog
    from PySide6.QtWidgets import QDialog
    PngExportDialog.exec = lambda self: QDialog.DialogCode.Accepted
    from terraria_pixel.desktop import configure_app
    configure_app(app)          # 与 main.py 启动一致，保证离屏检查用的是真实主题
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    img = np.zeros((12, 12, 3), np.uint8)
    img[..., 0] = np.linspace(0, 255, 12)[None, :]
    img[..., 1] = 200
    img[..., 2] = np.linspace(0, 255, 12)[:, None]
    path = root / "demo.png"
    Image.fromarray(img).save(path)
    result = prepare_preview(path, width=12, progress=lambda *_: None)

    from terraria_pixel.editor import TARGET_FINE, TARGET_PIXEL
    from terraria_pixel.editor_window import PixelEditorWindow

    # 1) 像素画：色库不限
    pixel = PixelEditorWindow(result, TARGET_PIXEL)
    pixel.canvas.color = (12, 34, 56)
    pixel.canvas._paint((0, 0))
    assert tuple(int(v) for v in result.processed_rgb[0, 0]) != (12, 34, 56), "应用前不应写回结果"
    assert pixel.apply() is True, "像素画改动应能应用"
    assert tuple(int(v) for v in result.processed_rgb[0, 0]) == (12, 34, 56)
    pixel.close()
    assert not pixel.isVisible()

    # 2) 混合版：色库来自方块 × 喷漆，改色吸附到最近材料
    fine = PixelEditorWindow(result, TARGET_FINE)
    assert fine.palette_list.topLevelItemCount() > 0, "材料版应有按物体分组的色库"
    before = fine.canvas_model.index_at(3, 3)
    fine.canvas.color = (250, 5, 5)
    fine.canvas._paint((3, 3))
    after = fine.canvas_model.index_at(3, 3)
    assert after != before, "改色后应换成最近材料"
    assert fine.canvas_model.labels[after], "材料应有可读名称"
    fine.undo()
    assert fine.canvas_model.index_at(3, 3) == before, "撤销应还原材料"
    fine.redo()
    assert fine.canvas_model.index_at(3, 3) == after, "重做应再次应用材料"
    assert fine.apply() is True

    # 3) 填充 + 重置
    fine2 = PixelEditorWindow(result, TARGET_FINE)
    target = (fine2.canvas_model.index_at(0, 0) + 1) % len(fine2.canvas_model.labels)
    filled = fine2.canvas_model.fill(0, 0, index=target)
    assert filled >= 1, "填充至少应命中起始格"
    assert fine2.canvas_model.reset() >= 0
    assert not fine2.canvas_model.dirty
    fine2.close()

    # 4) 新建画布：手绘后转成泰拉像素画
    from terraria_pixel.editor import EditCanvas
    from terraria_pixel.editor_window import PixelEditorWindow as EditorWindow

    artwork = EditCanvas.blank(24, 18, (245, 245, 250))
    made = 0
    for x in range(24):
        if artwork.set_cell(x, 12, rgb=(30, 120, 200)):
            made += 1
    for y in range(6, 13):
        if artwork.set_cell(6, y, rgb=(250, 200, 60)):
            made += 1
    assert made >= 18, "手绘应写入若干格"
    creator = EditorWindow(canvas=artwork, on_convert=lambda rgb: captured.append(rgb))
    assert creator.canvas_mode, "给画布时应进入创作模式"
    creator.show()
    app.processEvents()
    assert creator.convert_button.isVisible(), "创作模式应给出转换按钮"
    assert not creator.apply_button.isVisible(), "创作模式不应出现“应用”"
    creator.convert()
    assert captured and captured[0].shape == (18, 24, 3), "转换应交付当前画面"
    assert not creator.isVisible(), "转换后窗口应关闭"

    # 4.5) 创作画布可以直接导出 PNG
    from unittest.mock import patch
    from PySide6.QtWidgets import QFileDialog

    export_path = Path(tempfile.mkdtemp()) / "手绘导出.png"
    creator2 = EditorWindow(canvas=EditCanvas.blank(12, 9, (12, 34, 56)))
    creator2.show()
    app.processEvents()
    with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export_path), "PNG 图片 (*.png)")):
        creator2.export_png()
    assert export_path.is_file(), "画布应能直接导出 PNG"
    with Image.open(export_path) as exported:
        pixels = np.asarray(exported)
    assert pixels.shape == (9, 12, 3) and tuple(int(v) for v in pixels[0, 0]) == (12, 34, 56), "导出的 PNG 应与画布一致"
    creator2._allow_close = True
    creator2.close()

    # 5) 主窗口接入：编辑区嵌入当前窗口
    from terraria_pixel.desktop import MainWindow
    window = MainWindow()
    window.show()
    app.processEvents()
    window.result = result
    window.mode = 4
    window._update_png_action()
    assert window.edit_button.isEnabled(), "像素画页应能进入编辑"
    window.open_editor()
    assert window.editors and window.editors[-1].isVisible(), "应显示内嵌编辑区"
    assert not window.editors[-1].isWindow(), "编辑区不能成为独立窗口"
    assert not window.edit_button.isEnabled(), "编辑期间预览入口应禁用"
    window.editors[-1].close()
    # 6) 把新建的画布真正跑一遍转换（走主窗口的异步流程）
    window.convert_canvas(captured[0])
    while window.busy:
        app.processEvents()
    assert window.result is not None and window.result.grid is not None, "手绘像素画应能生成材料网格"
    assert window.result.grid.shape == (18, 24)
    assert window.source_rgb is not None and window.source_rgb.shape == (18, 24, 3)
    window.close()
    app.processEvents()

    tmp.cleanup()
    print("编辑窗口离屏检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
