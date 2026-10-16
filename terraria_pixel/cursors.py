"""绘画工具光标：白描边保证亮暗背景均可辨认。"""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QPolygonF


def drawing_cursor(tool):
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if tool == 'brush':
        outline = [(4, 27), (6, 19), (22, 3), (28, 9), (12, 25)]
    else:
        outline = [(3, 23), (17, 9), (28, 20), (14, 29)]
    polygon = QPolygonF([QPointF(x,y) for x,y in outline])
    painter.setPen(QPen(QColor('white'), 3))
    painter.setBrush(QColor('#83afff'))
    painter.drawPolygon(polygon)
    painter.setPen(QPen(QColor('#101522'), 1))
    painter.drawPolygon(polygon)
    if tool == 'brush':
        painter.drawLine(6, 19, 12, 25)
        painter.setBrush(QColor('#101522'))
        painter.drawPolygon(QPolygonF([QPointF(4,27),QPointF(6,19),QPointF(12,25)]))
    else:
        painter.setPen(QPen(QColor('white'), 2))
        painter.drawArc(8, 3, 14, 17, 0, 180*16)
        painter.setBrush(QColor('#83afff'))
        painter.drawEllipse(1, 24, 4, 6)
    painter.end()
    return QCursor(pixmap, 4, 27)
