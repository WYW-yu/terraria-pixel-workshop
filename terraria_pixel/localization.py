"""固定使用简体中文Qt文本，发行包不依赖电脑的语言或Qt翻译安装。"""
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, QTranslator
from PySide6.QtWidgets import QMessageBox


class DialogLanguage(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QMessageBox):
            labels = {
                QMessageBox.StandardButton.Ok: '确定',
                QMessageBox.StandardButton.Yes: '是',
                QMessageBox.StandardButton.No: '否',
                QMessageBox.StandardButton.Cancel: '取消',
                QMessageBox.StandardButton.Save: '保存',
                QMessageBox.StandardButton.Discard: '放弃改动',
                QMessageBox.StandardButton.Close: '关闭',
                QMessageBox.StandardButton.Retry: '重试',
                QMessageBox.StandardButton.Abort: '中止',
                QMessageBox.StandardButton.Ignore: '忽略',
            }
            if watched.windowTitle() == '保存未完成的画面？':
                labels[QMessageBox.StandardButton.Save] = '保存草稿'
            for standard, text in labels.items():
                button = watched.button(standard)
                if button is not None:
                    button.setText(text)
        return False


def configure_chinese(app):
    if hasattr(app, '_chinese_dialogs'):
        return
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    translator = QTranslator(app)
    if translator.load(str(root / 'assets/translations/qtbase_zh_CN.qm')):
        app.installTranslator(translator)
        app._chinese_translator = translator
    # 保存弹窗使用明确的操作名称；标准按钮值、默认按钮与取消逻辑不变。
    app._chinese_dialogs = DialogLanguage(app)
    app.installEventFilter(app._chinese_dialogs)
