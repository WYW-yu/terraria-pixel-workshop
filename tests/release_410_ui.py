"""真实 Qt 事件覆盖拖图、地图导航、连续保存和窗口保持打开。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys, tempfile, time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData, QUrl, QEvent
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QWheelEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtTest import QTest
from PIL import Image
from terraria_pixel.desktop import MainWindow, configure_app
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.world_dialog import WorldImportDialog
from test_world import fixture

app = QApplication.instance() or QApplication([])
configure_app(app)

def wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('UI operation timed out')
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()

def drag(view, start, end, button):
    for kind, point, changed, buttons in (
        (QEvent.Type.MouseButtonPress, start, button, button),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, button),
        (QEvent.Type.MouseButtonRelease, end, button, Qt.MouseButton.NoButton)):
        event = QMouseEvent(kind, QPointF(point), QPointF(view.mapToGlobal(point.toPoint())), changed, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view, event)
    app.processEvents()

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    image = root / 'image.png'
    Image.new('RGB', (4, 3), (230, 200, 175)).save(image)
    main = MainWindow()
    from terraria_pixel.history import HistoryStore
    main.history = HistoryStore(root / 'history.json', root / 'output')
    main.output_input.setText(str(root / 'output'))
    main.show()
    app.processEvents()
    for widget in (main.canvas, main.width_input, main.table.viewport()):
        mime = QMimeData()
        mime.setUrls([QUrl('https://example.com/no.png'), QUrl.fromLocalFile(str(image))])
        event = QDragEnterEvent(QPoint(5,5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)
        assert event.isAccepted(), type(widget).__name__
        event = QDropEvent(QPointF(5,5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)
        assert event.isAccepted()
        wait_for(lambda: main.worker is None)
        assert main.source_path == image and main.isVisible()
    result = prepare_preview(image, width=4)
    main.result = result
    main.preview_dirty = False
    main._show_result()
    source = fixture(root / 'world.wld', width=80, height=60)
    original = source.read_bytes()
    errors = []
    with patch.object(QMessageBox, 'warning', side_effect=lambda *args: errors.append(args[-1])):
        dialog = WorldImportDialog(result, parent=main)
        dialog.show()
        dialog.load_path(source)
        wait_for(lambda: dialog.worker is None)
        view = dialog.view
        before_position = (view.x, view.y)
        anchor = QPointF(view.rect().center()) + QPointF(-70, -40)
        before = view.world_rect()
        uv = (anchor - before.topLeft()) / before.width()
        wheel = QWheelEvent(anchor, QPointF(view.mapToGlobal(anchor.toPoint())), QPoint(), QPoint(0,240),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(view, wheel)
        after = view.world_rect()
        assert view.zoom > 1 and (view.x, view.y) == before_position
        assert ((anchor - after.topLeft()) / after.width() - uv).manhattanLength() < 1e-6
        before = view.world_rect()
        drag(view, QPointF(30,30), QPointF(90,60), Qt.MouseButton.RightButton)
        assert abs(view.world_rect().x() - before.x() - 60) < 1
        assert (view.x, view.y) == before_position
        view.fit()
        dialog._picked(20, 15)
        rect = view.artwork_rect()
        cell = view.world_rect().width() / dialog.document.info.width
        drag(view, rect.center(), rect.center() + QPointF(3 * cell, 2 * cell), Qt.MouseButton.LeftButton)
        assert (view.x, view.y) == (23,17), (view.x, view.y)
        # 直接保存后窗口、主程序仍打开，可继续再次保存。
        dialog.direct_button.click()
        wait_for(lambda: dialog.worker is None)
        assert dialog.saved_path == source.resolve() and dialog.isVisible() and main.isVisible(), errors
        assert not list(root.glob('*.bak'))
        digest = dialog.document.digest
        dialog._picked(30,20)
        dialog.direct_button.click()
        wait_for(lambda: dialog.worker is None)
        assert dialog.document.digest != digest and dialog.isVisible(), errors
        target = root / 'another.wld'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
            dialog.save_button.click()
        wait_for(lambda: dialog.worker is None)
        assert target.exists() and dialog.document.path == target and dialog.isVisible(), errors
        assert not errors, errors
        view.zoom_at(2)
        dialog.grab().save('E:/test/.tmp/release-410/world-ui.png')
        dialog.reject()
        assert main.isVisible()
    main.grab().save('E:/test/.tmp/release-410/main-ui.png')
    main.close()
print('Qt: image drop on canvas/text/table, anchored zoom, pan, artwork drag, repeated direct/save-as, windows remain open: PASS')
