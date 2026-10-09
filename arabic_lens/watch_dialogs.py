"""Small, non-modal Watch setup windows. No game process is modified."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QStackedWidget, QLineEdit
from .design import STYLE


def center_on_cursor_screen(dialog):
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen:
        center = screen.availableGeometry().center()
        dialog.move(center.x() - dialog.width() // 2, center.y() - dialog.height() // 2)


class WatchPresetsDialog(QDialog):
    create_requested = Signal()
    delete_requested = Signal(int)
    preset_requested = Signal(int)
    new_requested = Signal()
    previous_requested = Signal()
    dismissed = Signal()

    def __init__(self, localization):
        super().__init__()
        self.t = localization.t
        self.setLayoutDirection(Qt.RightToLeft if localization.settings.language == 'ar' else Qt.LeftToRight)
        self.setWindowTitle(self.t('Watch Mode'))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setStyleSheet(STYLE)
        self.setFixedSize(390, 420)
        center_on_cursor_screen(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(12)
        title = QLabel(self.t('Watch Mode')); title.setObjectName('sectionTitle')
        root.addWidget(title)
        caption = QLabel(self.t('Presets')); root.addWidget(caption)
        row = QHBoxLayout()
        row.addStretch()
        plus = QPushButton('+'); plus.setFixedSize(36, 34)
        minus = QPushButton('−'); minus.setFixedSize(36, 34)
        row.addWidget(plus); row.addWidget(minus)
        root.addLayout(row)
        self.list = QListWidget()
        self.empty = QLabel(self.t('No presets saved'))
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet('border:1px solid #c4d7c2; border-radius:8px; color:#67806d;')
        self.display = QStackedWidget()
        self.display.addWidget(self.empty); self.display.addWidget(self.list)
        root.addWidget(self.display, 1)
        self.start = QPushButton(self.t('Start with Preset'))
        self.start.setObjectName('primary')
        root.addWidget(self.start)
        bottom = QHBoxLayout()
        for title, signal in (('Start New', self.new_requested), ('Use Previous', self.previous_requested), ('Close', self.dismissed)):
            button = QPushButton(self.t(title)); button.clicked.connect(signal.emit); bottom.addWidget(button)
        root.addLayout(bottom)
        plus.clicked.connect(self.create_requested.emit)
        minus.clicked.connect(lambda: self.delete_requested.emit(self.list.currentRow()))
        self.start.clicked.connect(lambda: self.preset_requested.emit(self.list.currentRow()))
        self.list.currentRowChanged.connect(lambda row: (minus.setEnabled(row >= 0), self.start.setEnabled(row >= 0)))
        self.delete_button = minus
        self.set_presets([])

    def set_presets(self, presets, selected=-1):
        self.list.clear()
        for preset in presets:
            self.list.addItem(f"{preset['name']}  ·  {len(preset['areas'])} {self.t('areas')}")
        self.display.setCurrentIndex(1 if presets else 0)
        if 0 <= selected < len(presets):
            self.list.setCurrentRow(selected)
        self.start.setEnabled(self.list.currentRow() >= 0)
        self.delete_button.setEnabled(self.list.currentRow() >= 0)

    def closeEvent(self, event):
        self.dismissed.emit()
        super().closeEvent(event)


class WatchTargetDialog(QDialog):
    """Optional focus aid before drawing zones; no app is bound to the preset."""
    chosen = Signal(object)
    cancelled = Signal()

    def __init__(self, localization, targets):
        super().__init__()
        self.t = localization.t
        self.setLayoutDirection(Qt.RightToLeft if localization.settings.language == 'ar' else Qt.LeftToRight)
        self.targets = targets
        self.setWindowTitle(self.t('Choose a game or app'))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(STYLE)
        self.setFixedSize(420, 350)
        center_on_cursor_screen(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.addWidget(QLabel(self.t('Choose a game or app')))
        root.addWidget(QLabel(self.t('Bring an open window forward to draw watch areas.')))
        self.list = QListWidget()
        for target in targets:
            self.list.addItem(target['title'])
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.choose = QPushButton(self.t('Choose'))
        self.choose.setObjectName('primary')
        self.choose.setEnabled(False)
        cancel = QPushButton(self.t('Cancel'))
        skip = QPushButton(self.t('Use current screen'))
        row.addWidget(self.choose); row.addWidget(skip); row.addWidget(cancel)
        root.addLayout(row)
        self.list.currentRowChanged.connect(lambda index: self.choose.setEnabled(index >= 0))
        self.list.itemDoubleClicked.connect(lambda _: self.accept_target())
        self.choose.clicked.connect(self.accept_target)
        skip.clicked.connect(lambda: (self.hide(), self.chosen.emit(None)))
        cancel.clicked.connect(self.cancel_target)

    def accept_target(self):
        index = self.list.currentRow()
        if index >= 0:
            self.hide()
            self.chosen.emit(self.targets[index])

    def cancel_target(self):
        self.hide()
        self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel_target()
        else:
            super().keyPressEvent(event)


class PresetNameDialog(QDialog):
    chosen = Signal(str)
    cancelled = Signal()

    def __init__(self, localization):
        super().__init__()
        self.t = localization.t
        self.setLayoutDirection(Qt.RightToLeft if localization.settings.language == 'ar' else Qt.LeftToRight)
        self.setWindowTitle(self.t('Name your preset'))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(STYLE)
        self.setFixedSize(350, 168)
        center_on_cursor_screen(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        title = QLabel(self.t('Name your preset'))
        title.setObjectName('sectionTitle')
        root.addWidget(title)
        self.name = QLineEdit()
        self.name.setPlaceholderText(self.t('Preset name'))
        self.name.setMaxLength(60)
        root.addWidget(self.name)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(self.t('Cancel'))
        create = QPushButton(self.t('Continue'))
        create.setObjectName('primary')
        create.setEnabled(False)
        row.addWidget(cancel); row.addWidget(create)
        root.addLayout(row)
        self.name.textChanged.connect(lambda value: create.setEnabled(bool(value.strip())))
        self.name.returnPressed.connect(self.accept_name)
        create.clicked.connect(self.accept_name)
        cancel.clicked.connect(self.cancel_name)

    def showEvent(self, event):
        super().showEvent(event)
        self.name.setFocus()

    def accept_name(self):
        name = self.name.text().strip()
        if name:
            self.hide()
            self.chosen.emit(name)

    def cancel_name(self):
        self.hide()
        self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel_name()
        else:
            super().keyPressEvent(event)
