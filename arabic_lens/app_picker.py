from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QComboBox, QLineEdit, QListWidget, QListWidgetItem, QFileDialog)
from .app_catalog import open_apps, installed_apps
from .titlebar import TitleBar


class InventorySignals(QObject):
    finished = Signal(int, object, bool)


class InventoryWorker(QRunnable):
    def __init__(self, index):
        super().__init__()
        self.index = index
        self.signals = InventorySignals()

    def run(self):
        try:
            apps = (open_apps, installed_apps)[self.index]()
            self.signals.finished.emit(self.index, apps, True)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('App inventory unavailable')
            self.signals.finished.emit(self.index, [], False)


class AppPicker(QDialog):
    def __init__(self, parent, translate):
        super().__init__(parent)
        self.t = translate
        self.selected_app = None
        self.inventory, self.pending, self.workers = {}, set(), []
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle(self.t('Block apps'))
        self.setMinimumSize(560, 460)
        self.setLayoutDirection(parent.layoutDirection())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 16)
        title = TitleBar(self, self.t)
        title.minimize.hide(); title.maximize.hide()
        title.close_button.setToolTip(self.t('Cancel'))
        title.close_button.setAccessibleName(self.t('Cancel'))
        layout.addWidget(title)
        body = QVBoxLayout()
        body.setContentsMargins(22, 12, 22, 0)
        layout.addLayout(body)
        heading = QLabel(self.t('Block apps')); heading.setObjectName('sectionTitle')
        body.addWidget(heading)
        note = QLabel(self.t('Choose an app to skip in Watch Mode. Quick Translate still works.'))
        note.setWordWrap(True); body.addWidget(note)
        row = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItems([self.t('Open apps'), self.t('Installed apps')])
        row.addWidget(self.source, 1)
        refresh = QPushButton(self.t('Refresh')); refresh.clicked.connect(self.refresh)
        row.addWidget(refresh); body.addLayout(row)
        self.search = QLineEdit(); self.search.setPlaceholderText(self.t('Search apps…'))
        body.addWidget(self.search)
        self.apps = QListWidget(); body.addWidget(self.apps, 1)
        self.status = QLabel(); self.status.setWordWrap(True); body.addWidget(self.status)
        actions = QHBoxLayout()
        browse = QPushButton(self.t('Browse…')); browse.clicked.connect(self.browse)
        actions.addWidget(browse); actions.addStretch()
        cancel = QPushButton(self.t('Cancel')); cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.add = QPushButton(self.t('Add')); self.add.setEnabled(False)
        self.add.clicked.connect(self.choose); actions.addWidget(self.add)
        body.addLayout(actions)
        self.source.currentIndexChanged.connect(self.load)
        self.search.textChanged.connect(self.render)
        self.apps.currentItemChanged.connect(lambda: self.add.setEnabled(self.apps.currentItem() is not None))
        self.apps.itemDoubleClicked.connect(self.choose)
        from .ui_controls import protect_wheel_fields
        protect_wheel_fields(self)
        self.load()

    def refresh(self):
        self.inventory.pop(self.source.currentIndex(), None)
        self.load()

    def load(self):
        index = self.source.currentIndex()
        if index in self.inventory:
            self.render()
            return
        self.apps.clear(); self.add.setEnabled(False)
        self.status.setText(self.t('Finding apps…'))
        if index not in self.pending:
            self.pending.add(index)
            worker = InventoryWorker(index)
            self.workers.append(worker)
            worker.signals.finished.connect(self.loaded)
            QThreadPool.globalInstance().start(worker)

    def loaded(self, index, apps, success):
        self.pending.discard(index)
        self.inventory[index] = (apps, success)
        if index == self.source.currentIndex():
            self.render()

    def render(self):
        index = self.source.currentIndex()
        if index not in self.inventory:
            return
        apps, success = self.inventory[index]
        self.apps.clear()
        query = self.search.text().casefold()
        for app in apps:
            if query in (app['name'] + ' ' + app['path']).casefold():
                item = QListWidgetItem(app['name'])
                item.setToolTip(app['path']); item.setData(Qt.UserRole, app)
                self.apps.addItem(item)
        self.status.setText(self.t('Choose an app, or browse to its application file.') if success else self.t('Could not list apps. You can browse to an application instead.'))
        self.add.setEnabled(False)

    def choose(self, *unused):
        item = self.apps.currentItem()
        if item:
            self.selected_app = item.data(Qt.UserRole)
            self.accept()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t('Choose an app'), '', self.t('Applications (*.exe)'))
        if path:
            import ntpath
            self.selected_app = {'name': ntpath.splitext(ntpath.basename(path))[0], 'path': path}
            self.accept()
