"""PNG导出窗口：默认原像素，可选择带网格的整数倍放大图。"""
from pathlib import Path
import os
import tempfile
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox, QPushButton, QFileDialog, QMessageBox
from .pixels import png_image


class PngExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('PNG导出选项')
        layout = QVBoxLayout(self)
        self.grid = QCheckBox('保留网格线')
        layout.addWidget(self.grid)
        note = QLabel('不带网格：原像素尺寸，保留透明。\n带网格：每格整数倍放大，格线会出现在PNG中。')
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel('带网格时每格宽度'))
        self.cell_size = QSpinBox()
        self.cell_size.setRange(4, 64)
        self.cell_size.setValue(12)
        self.cell_size.setSuffix(' 像素')
        self.cell_size.setEnabled(False)
        self.grid.toggled.connect(self.cell_size.setEnabled)
        row.addWidget(self.cell_size)
        layout.addLayout(row)
        row = QHBoxLayout()
        cancel = QPushButton('取消'); cancel.clicked.connect(self.reject)
        save = QPushButton('选择保存位置'); save.clicked.connect(self.accept)
        row.addWidget(cancel); row.addWidget(save)
        layout.addLayout(row)


def export_png(parent, pixels, default):
    dialog = PngExportDialog(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    filename, _ = QFileDialog.getSaveFileName(parent, '导出像素画 PNG', str(default), 'PNG 图片 (*.png)', options=QFileDialog.Option.DontConfirmOverwrite)
    if not filename:
        return None
    path = Path(filename).with_suffix('.png')
    if path.exists() and QMessageBox.question(parent, '替换已有图片？', f'是否替换：\n{path}') != QMessageBox.StandardButton.Yes:
        return None
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.png-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        png_image(pixels, grid=dialog.grid.isChecked(), cell_size=dialog.cell_size.value()).save(temporary, format='PNG')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
