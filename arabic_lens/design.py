"""Light desktop design primitives. All artwork is rendered natively by Qt."""
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QIcon, QPixmap, QPainterPath, QLinearGradient
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSlider, QSpinBox, QSizePolicy, QAbstractSpinBox, QCheckBox

STYLE = """
QWidget { background: #dae6da; color: #20312f; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background: #dae6da; }
QFrame#sidebar { background: #cedfce; border-right: 1px solid #dbe2d8; }
QLabel { background: transparent; }
QLabel#brand { font-size: 21px; font-weight: 650; color: #193d32; }
QLabel#muted { color: #536c59; }
QLabel#eyebrow { color: #58776a; font-size: 11px; font-weight: 650; }
QLabel#title { font-size: 29px; font-weight: 650; color: #1c322b; }
QLabel#sectionTitle { font-size: 16px; font-weight: 650; color: #243b31; }
QLabel#status { background: #eef2ec; color: #4e6357; padding: 9px 14px; border: 1px solid #e0e6dc; border-radius: 18px; }
QLabel#shortcut { background: #f2f4ed; color: #627465; border: 1px solid #dde5d6; padding: 6px 10px; border-radius: 5px; font-size: 12px; }
QFrame#card { background: #e9f0e5; border: 1px solid #dde5dc; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QWidget#sliderRow, QSlider, QCheckBox { background: transparent; }
QFrame#notice { background: #f8f0df; border: 1px solid #e7d9b9; border-radius: 10px; }
QFrame#notice QWidget { background: transparent; }
QFrame#footer { border-top: 1px solid #dfe5dd; background: transparent; }
QPushButton { background: #e9f0e5; color: #32493b; border: 1px solid #d0dcd0; border-radius: 7px; padding: 8px 13px; font-weight: 600; }
QPushButton:hover { background: #f0f6ec; border-color: #83a48c; }
QPushButton:pressed { background: #dfeadb; }
QPushButton:disabled { color: #a9b2a7; background: #f4f6f1; }
QPushButton#primary { background: #2b765b; color: #e9f0e5; border: 1px solid #286c53; padding: 10px 18px; }
QPushButton#primary:hover { background: #348c6b; }
QPushButton#nav { background: transparent; color: #5f7264; border: 0; text-align: left; padding: 12px 14px; font-weight: 500; }
QPushButton#nav:checked { background: #dce9d9; color: #1e523b; border: 1px solid #cadcc5; font-weight: 650; }
QPushButton#nav:hover { background: #e3ebde; color: #284e38; }
QPushButton#preset { background: #fafcf8; border: 1px solid #dae3d5; padding: 12px 8px; font-weight: 500; }
QPushButton#preset:checked { background: #e8f3e3; border: 2px solid #5c9870; color: #235039; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QKeySequenceEdit { background: #e9f0e5; color: #2c4334; border: 1px solid #b4c9b4; border-radius: 6px; padding: 6px 9px; min-height: 19px; selection-background-color: #d8eacc; selection-color: #173d28; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QKeySequenceEdit:focus { border-color: #6b9f7c; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #e9f0e5; color: #324b39; selection-background-color: #e2efdc; }
QCheckBox { spacing: 10px; padding: 5px 0; color: #3e5343; }
QCheckBox::indicator { width: 31px; height: 17px; border: 1px solid #c8d4c4; border-radius: 9px; background: #e5ebe0; }
QCheckBox::indicator:checked { background: #4c966a; border-color: #4c966a; }
QCheckBox#startupChoice { color: #405c48; font-size: 11px; spacing: 5px; padding: 2px 0; }
QCheckBox#startupChoice::indicator { width: 12px; height: 12px; border-radius: 3px; border: 1px solid #9eb9a0; background: #eef4e9; }
QCheckBox#startupChoice::indicator:checked { background: #2b765b; border-color: #2b765b; }
QListWidget, QTreeWidget { background: #e9f0e5; color: #344a3a; border: 1px solid #dce4d7; border-radius: 8px; padding: 8px; }
QListWidget::item, QTreeWidget::item { padding: 10px; border-bottom: 1px solid #dce5d8; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #d4e6cf; color: #275138; }
QHeaderView::section { background: #dce8d8; color: #385e4c; padding: 9px 12px; border: 0; font-weight: 600; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #ccd8c7; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #fafff6; color: #35523c; border: 1px solid #c5d9bd; padding: 6px; }
QSlider::groove:horizontal { background: #e1e8dc; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #75ab7e; border-radius: 2px; }
QSlider::handle:horizontal { background: #3c8760; border: 2px solid #e9f0e5; width: 13px; height: 13px; margin: -6px 0; border-radius: 8px; }
"""


class SliderSpin(QWidget):
    valueChanged = Signal(int)
    def __init__(self, low, high, value, step=1):
        super().__init__()
        self.setObjectName("sliderRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(low, high)
        self.slider.setSingleStep(step)
        self.number = QSpinBox()
        self.number.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.number.setRange(low, high)
        self.number.setSingleStep(step)
        self.number.setFixedWidth(72)
        self.slider.setValue(value)
        self.number.setValue(value)
        self.slider.valueChanged.connect(self.number.setValue)
        self.number.valueChanged.connect(self.slider.setValue)
        self.number.valueChanged.connect(self.valueChanged)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.number)

    def value(self):
        return self.number.value()

    def setValue(self, value):
        self.number.setValue(value)


class ToggleCheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        origin = self.width() - 33 if self.layoutDirection() == Qt.RightToLeft else 0
        x = origin + (18 if self.isChecked() else 3)
        p.setPen(QPen(QColor("#b9cbb7"), .5))
        p.setBrush(QColor("#e9f0e5"))
        p.drawEllipse(QRectF(x, (self.height() - 13) / 2, 13, 13))


def line_icon(kind, size=22, color="#527462"):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    p.setPen(QPen(QColor(color), 1.55, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    if kind == "Home":
        path = QPainterPath(QPointF(3, 11)); path.lineTo(12, 3); path.lineTo(21, 11)
        p.drawPath(path); p.drawRoundedRect(QRectF(6, 10, 12, 11), 1, 1); p.drawRect(QRectF(10, 15, 4, 6))
    elif kind == "General":
        p.drawEllipse(QRectF(7, 7, 10, 10)); p.drawEllipse(QRectF(10, 10, 4, 4))
        for x,y,a,b in [(12,2,12,6),(12,18,12,22),(2,12,6,12),(18,12,22,12),(5,5,8,8),(16,16,19,19),(5,19,8,16),(16,8,19,5)]: p.drawLine(x,y,a,b)
    elif kind in ("Watch Mode", "Overlay"):
        p.drawRoundedRect(QRectF(3, 4, 18, 13), 2, 2); p.drawLine(12,17,12,21); p.drawLine(8,21,16,21)
        if kind == "Overlay": p.drawLine(7,10,17,10); p.drawLine(9,13,17,13)
    elif kind == "Translation":
        p.drawRoundedRect(QRectF(3, 3, 18, 18), 2, 2); p.drawLine(7,16,11,7); p.drawLine(11,7,15,16); p.drawLine(9,13,13,13); p.drawLine(16,8,18,8)
    elif kind == "Shortcuts":
        p.drawRoundedRect(QRectF(2, 5, 20, 14), 2, 2)
        for y in (9,12):
            for x in (6,10,14,18): p.drawPoint(x,y)
        p.drawLine(7,16,17,16)
    elif kind == "Ignore List":
        for y in (5,12,19): p.drawEllipse(QRectF(3,y-1,2,2)); p.drawLine(9,y,21,y)
    elif kind == "History":
        p.drawEllipse(QRectF(3,3,18,18)); p.drawLine(12,6,12,12); p.drawLine(12,12,16,14)
    elif kind == "capture":
        for x,y,a,b,c,d in [(3,9,3,3,9,3),(15,3,21,3,21,9),(21,15,21,21,15,21),(9,21,3,21,3,15)]: p.drawLine(x,y,a,b); p.drawLine(a,b,c,d)
        p.drawLine(8,12,16,12); p.drawLine(12,8,12,16)
    elif kind == "eye":
        path = QPainterPath(QPointF(2,12)); path.quadTo(12,0,22,12); path.quadTo(12,24,2,12); p.drawPath(path); p.drawEllipse(QRectF(9,9,6,6))
    elif kind == "repeat":
        p.drawArc(QRectF(4,4,16,16), 35*16, 285*16); p.drawLine(20,3,20,9); p.drawLine(20,9,14,9)
    p.end()
    return QIcon(pix)


class PreviewScene(QWidget):
    """Quiet landscape gives subtitle contrast a useful light/dark context."""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(195)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.source = None
        self.surface = None
        self.position = "Below"

    def arrange(self):
        if not self.source or not self.surface:
            return
        self.source.adjustSize()
        total = self.source.height() + self.surface.height() + 10
        top = max(6, (self.height() - total) // 2)
        self.source.move(max(12, (self.width() - self.source.width()) // 2), top)
        y = top + self.source.height() + 10
        if self.position == "Above":
            y = top
            self.source.move(self.source.x(), top + self.surface.height() + 10)
            self.source.show()
        elif self.position == "Replace":
            y = max(6, (self.height() - self.surface.height()) // 2)
            self.source.hide()
        else:
            self.source.show()
        self.surface.move(max(12, (self.width() - self.surface.width()) // 2), y)

    def resizeEvent(self, event):
        self.arrange()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setClipPath(self.clip_path())
        p.scale(self.width() / 1000, self.height() / 195)
        sky = QLinearGradient(0,0,0,195)
        sky.setColorAt(0,QColor("#d6dfd3")); sky.setColorAt(.55,QColor("#e9d9bd")); sky.setColorAt(1,QColor("#aea998"))
        p.fillRect(0,0,1000,195,sky)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f3ebd5")); p.drawEllipse(QRectF(722,21,58,58))
        for color, points in [("#bac5b4", [(0,130),(100,60),(210,122),(330,54),(450,125),(610,63),(800,134),(900,93),(1000,130),(1000,195),(0,195)]), ("#92a28b", [(0,155),(160,112),(280,161),(410,115),(530,154),(690,113),(850,153),(1000,117),(1000,195),(0,195)])]:
            path = QPainterPath(QPointF(*points[0]))
            for point in points[1:]: path.lineTo(*point)
            path.closeSubpath(); p.setBrush(QColor(color)); p.drawPath(path)
        p.setBrush(QColor("#77836e")); p.drawRoundedRect(QRectF(115,117,88,78),3,3); p.drawRect(QRectF(109,111,100,12)); p.drawRect(QRectF(142,83,34,30)); p.drawRect(QRectF(136,78,46,8))
        p.setBrush(QColor("#596b58")); p.drawRect(QRectF(144,146,26,49))
        p.setBrush(QColor("#667b62"))
        for x,h in [(21,85),(44,110),(938,102),(966,120)]:
            path=QPainterPath(QPointF(x,195)); path.lineTo(x+16,195-h); path.lineTo(x+34,195); path.closeSubpath(); p.drawPath(path)
        wash=QLinearGradient(0,120,0,195); wash.setColorAt(0,QColor(255,255,255,0)); wash.setColorAt(1,QColor(36,60,40,55)); p.fillRect(0,0,1000,195,wash)

    def clip_path(self):
        path=QPainterPath(); path.addRoundedRect(QRectF(self.rect()),8,8); return path
