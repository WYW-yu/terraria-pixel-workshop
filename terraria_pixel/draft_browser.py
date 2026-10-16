"""已保存草稿列表；和游戏作品历史分别显示。"""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton
from .draft_paths import draft_folder, list_drafts


class DraftBrowser(QDialog):
    def __init__(self, base, parent=None):
        super().__init__(parent)
        self.setWindowTitle('像素画草稿')
        self.resize(650, 420)
        self.selected_path = None
        self.browse_other = False
        layout = QVBoxLayout(self)
        folder = draft_folder(base)
        note = QLabel(f'默认草稿文件夹：{folder}\n草稿用于继续画；生成的材料作品在“历史记录”中。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.list = QListWidget()
        paths = list_drafts(base)
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list.addItem(item)
        if not paths:
            layout.addWidget(QLabel('还没有草稿。编辑时点“保存草稿”，或打开其他位置的草稿。'))
        layout.addWidget(self.list)
        row = QHBoxLayout()
        other = QPushButton('打开其他草稿 / 图片'); other.clicked.connect(self.other)
        row.addWidget(other)
        row.addStretch()
        cancel = QPushButton('取消'); cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.open_button = QPushButton('继续画'); self.open_button.clicked.connect(self.open_selected)
        self.open_button.setEnabled(False)
        self.list.currentItemChanged.connect(lambda current, old: self.open_button.setEnabled(current is not None))
        self.list.itemDoubleClicked.connect(self.open_selected)
        row.addWidget(self.open_button)
        layout.addLayout(row)

    def other(self):
        self.browse_other = True
        self.accept()

    def open_selected(self, *args):
        item = self.list.currentItem()
        if item:
            self.selected_path = Path(item.data(Qt.ItemDataRole.UserRole))
            self.accept()
