from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class TitleBar(QFrame):
    def __init__(self, window, translate):
        super().__init__()
        self.window = window
        self.setFixedHeight(48)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setStyleSheet('''QFrame { background: #edf2e9; border-bottom: 1px solid #d9e3d6; }
            QLabel { color: #2d594a; border: none; font-size: 13px; }
            QPushButton { border: none; border-radius: 6px; background: transparent;
                color: #2d594a; font-size: 19px; min-height: 30px; padding: 0; }
            QPushButton:hover { background: #d8e5d4; }
            QPushButton#windowClose:hover { background: #d65345; color: white; }''')
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 5, 10, 5)
        name = QLabel(translate('Arabic Lens'))
        name.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(name)
        row.addStretch()
        self.minimize = self.control('−', translate('Minimize'), window.showMinimized)
        self.maximize = self.control('□', translate('Maximize or restore'), self.toggle_maximized)
        self.close_button = self.control('×', translate('Close to tray'), window.close)
        self.close_button.setObjectName('windowClose')
        for button in (self.minimize, self.maximize, self.close_button):
            row.addWidget(button)

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
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
