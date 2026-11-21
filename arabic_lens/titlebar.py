from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class TitleBar(QFrame):
    def __init__(self, window, translate, *, compact=False):
        super().__init__()
        self.window = window
        self.setFixedHeight(42 if compact else 48)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setStyleSheet('''QFrame { background: #b7c6bc; border-bottom: 1px solid #a2b5a9; }
            QLabel { color: #2d594a; border: none; font-size: 13px; }
            QPushButton { border: none; border-radius: 6px; background: transparent;
                color: #2d594a; font-size: 19px; min-height: 30px; padding: 0; }
            QPushButton:hover { background: #c3d0c6; }
            QPushButton:checked { background: #dce9d9; color: #1e523b; }
            QPushButton#windowClose:hover { background: #d65345; color: white; }''')
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 5, 10, 5)
        name = QLabel(translate('Arabic Lens'))
        name.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(name)
        row.addStretch()
        self.row = row
        self.maximize = None
        if not compact:
            self.minimize = self.control('−', translate('Minimize'), window.showMinimized)
            self.maximize = self.control('□', translate('Maximize or restore'), self.toggle_maximized)
            row.addWidget(self.minimize)
            row.addWidget(self.maximize)
        self.close_button = self.control('×', translate('Close to tray'), window.close)
        self.close_button.setObjectName('windowClose')
        row.addWidget(self.close_button)

    def add_control(self, button):
        self.row.insertWidget(self.row.indexOf(self.close_button), button)

    def control(self, text, name, action):
        button = QPushButton(text)
        button.setFixedSize(40, 36)
        button.setAccessibleName(name)
        button.setToolTip(name)
        button.clicked.connect(action)
        return button

    def toggle_maximized(self):
        self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()
        self.maximize.setText('❐' if self.window.isMaximized() else '□')

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        if self.maximize and event.button() == Qt.LeftButton:
            self.toggle_maximized()
