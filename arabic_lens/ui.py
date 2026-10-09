import copy
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPainter, QColor, QIcon, QPixmap, QKeySequence, QFontDatabase
from PySide6.QtWidgets import (QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QStackedWidget, QComboBox, QCheckBox, QButtonGroup, QSpinBox, QLineEdit, QListWidget,
    QFormLayout, QKeySequenceEdit, QInputDialog, QMessageBox, QColorDialog, QSizePolicy, QSizeGrip, QListWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem)
from .config import DEFAULT_IGNORE, PRESETS, OverlaySettings
from .overlay import ArabicSurface

from .design import STYLE, SliderSpin, line_icon, PreviewScene, ToggleCheckBox


def lens_icon(size=64, active=False):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#79dfbe" if active else "#385e56"))
    p.drawRoundedRect(0, 0, size, size, size * .26, size * .26)
    p.setPen(QColor("#10241f" if active else "#d6efe6"))
    f = QFont("Segoe UI")
    f.setPixelSize(round(size * .67))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pixmap.rect().adjusted(0, -round(size * .06), 0, 0), Qt.AlignCenter, "ع")
    p.end()
    return QIcon(pixmap)


class SettingsWindow(QMainWindow):
    apply_requested = Signal(dict)
    action_requested = Signal(str)
    watch_startup_changed = Signal(str)
    ignore_translation_requested = Signal(str)
    update_requested = Signal()

    def __init__(self, settings, localization, store):
        super().__init__()
        self.settings, self.l, self.store = settings, localization, store
        self.watch_enabled = False
        self.translation_draft = ''
        self.update_status = ''
        self.update_detail = ''
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowTitle("Arabic Lens")
        self.setWindowIcon(lens_icon(active=True))
        self.resize(1360, 980)
        self.setMinimumSize(1060, 700)
        self.setStyleSheet(STYLE)
        self.rebuild()

    def t(self, text):
        return self.l.t(text)

    def label(self, text, name=None):
        label = QLabel(self.t(text))
        if name:
            label.setObjectName(name)
        label.setWordWrap(True)
        return label

    def button(self, text, callback, primary=False):
        button = QPushButton(self.t(text))
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(callback)
        return button

    def rebuild(self, page=0):
        self.overlay_reset = {}
        self.fields, self.overlay_fields, self.shortcut_fields = {}, {}, {}
        self.navs = []
        root = QWidget()
        root.setLayoutDirection(Qt.RightToLeft if self.settings.language == "ar" else Qt.LeftToRight)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 26, 18, 22)
        side.setSpacing(8)
        logo = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(lens_icon(active=True).pixmap(36, 36))
        logo.addWidget(icon)
        logo.addWidget(self.label("Arabic Lens", "brand"))
        logo.addStretch()
        side.addLayout(logo)
        side.addSpacing(30)
        sections = ["Home", "General", "Translation", "Watch Mode", "Overlay", "Shortcuts", "Ignore List", "History"]
        for index, title in enumerate(sections):
            button = QPushButton(self.t(title))
            button.setObjectName("nav")
            button.setIcon(line_icon(title))
            from PySide6.QtCore import QSize
            button.setIconSize(QSize(20, 20))
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            side.addWidget(button)
            self.navs.append(button)
        side.addStretch()
        side.addWidget(self.label("Interface language", "muted"))
        self.sidebar_language = QComboBox()
        self.sidebar_language.addItem("English", "en")
        self.sidebar_language.addItem("العربية", "ar")
        self.sidebar_language.setCurrentIndex(1 if self.settings.language == "ar" else 0)
        side.addWidget(self.sidebar_language)
        side.addSpacing(10)
        side.addWidget(self.label("Local recognition · No game injection · Quiet by design", "muted"))
        row.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(28, 26, 28, 18)
        content.setSpacing(18)
        top = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(4)
        self.page_title = self.label("Home", "title")
        self.page_subtitle = self.label("Your screen, a little easier to understand.", "muted")
        title_column.addWidget(self.page_title)
        title_column.addWidget(self.page_subtitle)
        top.addLayout(title_column, 1)
        top.addStretch()
        self.watch_badge = self.label("Watch is off", "status")
        top.addWidget(self.watch_badge)
        watch_controls = QVBoxLayout()
        watch_controls.setSpacing(5)
        self.watch_button = self.button("Enable Watch", lambda: self.action_requested.emit("watch"), True)
        watch_controls.addWidget(self.watch_button)
        choices = QHBoxLayout()
        choices.setSpacing(8)
        self.watch_choices = QButtonGroup(self)
        self.watch_choices.setExclusive(True)
        for key, title in (("fullscreen", "Watch fullscreen"), ("new", "Create New"),
                ("previous", "Use Previous"), ("presets", "Show Presets")):
            choice = QCheckBox(self.t(title))
            choice.setObjectName("startupChoice")
            choice.setChecked(self.settings.watch_startup == key)
            choice.toggled.connect(lambda enabled, value=key: self.watch_startup_changed.emit(value) if enabled else None)
            self.watch_choices.addButton(choice)
            choices.addWidget(choice)
        watch_controls.addLayout(choices)
        top.addLayout(watch_controls)
        content.addLayout(top)
        self.stack = QStackedWidget()
        content.addWidget(self.stack, 1)
        for builder in (self.home, self.general, self.translation, self.watch_page, self.overlay_page, self.shortcuts, self.ignore_page, self.history_page):
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 10, 0)
            layout.setSpacing(18)
            builder(layout)
            layout.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            self.stack.addWidget(scroll)
        footer = QFrame()
        footer.setObjectName("footer")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(0, 14, 0, 0)
        self.status_label = self.label("Ready", "muted")
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.button("Apply changes", self.apply, True))
        content.addWidget(footer)
        row.addLayout(content, 1)
        old = self.takeCentralWidget()
        shell = QWidget()
        shell.setLayoutDirection(root.layoutDirection())
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        from .titlebar import TitleBar
        self.titlebar = TitleBar(self, self.t)
        shell_layout.addWidget(self.titlebar)
        shell_layout.addWidget(root, 1)
        self.resize_grip = QSizeGrip(shell)
        self.setCentralWidget(shell)
        self.resize_grip.move(shell.width() - 20, shell.height() - 20)
        if old:
            old.deleteLater()
        self.navigate(page)
        self.update_watch(self.watch_enabled)
        self.sidebar_language.currentIndexChanged.connect(lambda index: self.fields["language"].setCurrentIndex(index))
        from .ui_controls import protect_wheel_fields
        protect_wheel_fields(self)

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        titles = ["Home", "General", "Translation", "Watch Mode", "Overlay", "Shortcuts", "Ignore List", "History"]
        subtitles = ["Your screen, a little easier to understand.", "Set up the app around your routine.", "Choose how your English text becomes Arabic.", "Choose what gets translated on your screen.", "Make translations fit your screen.", "Your favourite actions, within reach.", "Less clutter. Keep the words that matter.", "Find a line you translated earlier."]
        self.page_title.setText(self.t(titles[index]))
        self.page_subtitle.setText(self.t(subtitles[index]))
        for i, button in enumerate(self.navs):
            button.setChecked(index == i)
        if index == 7:
            self.refresh_history()

    def heading(self, layout, title, subtitle):
        pass  # Page title and description live in the persistent window header.

    def card(self, layout):
        frame = QFrame()
        frame.setObjectName("card")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(20, 16, 20, 16)
        inner.setSpacing(12)
        layout.addWidget(frame)
        return inner

    def form(self, layout):
        inner = self.card(layout)
        form = QFormLayout()
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(24)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        inner.addLayout(form)
        return form

    def check(self, form, key, title, overlay=False):
        value = getattr(self.settings.overlay if overlay else self.settings, key)
        widget = ToggleCheckBox(self.t(title))
        widget.setChecked(value)
        form.addRow(widget)
        (self.overlay_fields if overlay else self.fields)[key] = widget
        return widget

    def spin(self, form, key, title, low, high, overlay=False, step=1):
        if overlay:
            widget = SliderSpin(low, high, getattr(self.settings.overlay, key), step)
        else:
            widget = QSpinBox()
            widget.setRange(low, high)
            widget.setSingleStep(step)
            widget.setValue(getattr(self.settings, key))
        form.addRow(self.t(title), widget)
        (self.overlay_fields if overlay else self.fields)[key] = widget
        return widget

    def combo(self, form, key, title, choices, overlay=False):
        widget = QComboBox()
        for value, name in choices:
            widget.addItem(self.t(name), value)
        current = getattr(self.settings.overlay if overlay else self.settings, key)
        widget.setCurrentIndex(max(0, widget.findData(current)))
        form.addRow(self.t(title), widget)
        (self.overlay_fields if overlay else self.fields)[key] = widget
        return widget

    def edit(self, form, key, title, placeholder=""):
        widget = QLineEdit(getattr(self.settings, key))
        widget.setPlaceholderText(placeholder)
        widget.setLayoutDirection(Qt.LeftToRight)
        form.addRow(self.t(title), widget)
        self.fields[key] = widget
        return widget

    def section_header(self, layout, title, subtitle, icon="Overlay"):
        row = QHBoxLayout()
        glyph = QLabel()
        glyph.setPixmap(line_icon(icon, 26).pixmap(26, 26))
        glyph.setFixedSize(42, 42)
        glyph.setAlignment(Qt.AlignCenter)
        glyph.setStyleSheet("background: #edf5e8; border-radius: 11px;")
        row.addWidget(glyph)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(self.label(title, "sectionTitle"))
        texts.addWidget(self.label(subtitle, "muted"))
        row.addLayout(texts, 1)
        layout.addLayout(row)

    def make_scene(self, appearance):
        scene = PreviewScene()
        source = QLabel("You need to find the key before sunset.", scene)
        source.setStyleSheet("QLabel { background: #f8f4e9; color: #3c4937; border: 1px solid #c6c9b5; border-radius: 6px; padding: 8px 16px; font-size: 14px; }")
        surface = ArabicSurface(appearance, "عليك العثور على المفتاح قبل غروب الشمس.")
        surface.setParent(scene)
        scene.source, scene.surface = source, surface
        scene.arrange()
        return scene, surface

    def home(self, layout):
        top = self.card(layout)
        self.section_header(top, "English on screen. Arabic in the moment.", "A quiet subtitle beside the words you want to understand.", "Translation")
        scene, surface = self.make_scene(copy.deepcopy(self.settings.overlay))
        top.addWidget(scene)
        top.addWidget(self.label("Appearance example · Your game stays in control", "muted"))
        modes = self.card(layout)
        self.section_header(modes, "How would you like to translate?", "Start with Watch Mode, or select just the text you need.", "capture")
        for title, description, action, icon in (("Watch Mode", "Follow text automatically as your screen changes.", "watch", "eye"), ("Quick Translate", "Select text anywhere. Arabic appears on release.", "quick", "capture"), ("Translate Again", "Recapture your last selection in one keystroke.", "repeat", "repeat")):
            row = QHBoxLayout()
            row.setSpacing(16)
            glyph = QLabel()
            glyph.setPixmap(line_icon(icon, 24).pixmap(24, 24))
            glyph.setFixedWidth(34)
            row.addWidget(glyph)
            text = QVBoxLayout()
            text.setSpacing(3)
            text.addWidget(self.label(title, "sectionTitle"))
            text.addWidget(self.label(description, "muted"))
            row.addLayout(text, 1)
            shortcut = self.label(self.settings.shortcuts[action].replace("+", " + "), "shortcut")
            shortcut.setAlignment(Qt.AlignCenter)
            row.addWidget(shortcut)
            button = self.button("Start" if action == "watch" else "Select text" if action == "quick" else "Translate", lambda checked=False, a=action: self.action_requested.emit(a), action == "watch")
            button.setMinimumWidth(110)
            row.addWidget(button)
            modes.addLayout(row)
            if action != "repeat":
                line = QFrame(); line.setFrameShape(QFrame.HLine); line.setStyleSheet("color: #e4eadf; background: #e4eadf; max-height: 1px;")
                modes.addWidget(line)
        setup = QFrame()
        ready = self.settings.provider == 'Built-in offline' or bool(self.settings.endpoint)
        setup.setObjectName("card" if ready else "notice")
        setup_row = QHBoxLayout(setup)
        setup_row.setContentsMargins(20, 17, 20, 17)
        texts = QVBoxLayout()
        texts.addWidget(self.label("You are ready to translate" if ready else "One small setup before you start", "sectionTitle"))
        texts.addWidget(self.label("Open your game and press Alt+W. Translation works offline." if self.settings.provider == 'Built-in offline' else "Borderless or windowed games work best. Settings can stay closed.", "muted"))
        setup_row.addLayout(texts, 1)
        setup_row.addWidget(self.button("Translation settings", lambda: self.navigate(2)))
        layout.addWidget(setup)

    def general(self, layout):
        self.heading(layout, "General", "Make yourself at home.")
        form = self.form(layout)
        language = self.combo(form, "language", "Application language", [("en", "English"), ("ar", "العربية")])
        self.check(form, "start_windows", "Start with Windows")
        self.check(form, "start_minimized", "Start minimized")
        self.check(form, "minimize_tray", "Close to tray")
        self.check(form, "remember_mode", "Remember Watch Mode")
        self.check(form, "auto_check_updates", "Check for updates automatically")
        language.currentIndexChanged.connect(lambda: self.apply())
        updates = self.card(layout)
        updates.addWidget(self.label("Updates", "sectionTitle"))
        from .version import APP_VERSION
        updates.addWidget(self.label(self.t("Installed version") + " " + APP_VERSION, "muted"))
        updates.addWidget(self.label("Arabic Lens checks for new releases. You choose whether to download and install them.", "muted"))
        self.update_status_label = self.label(self.update_status or "No update check yet.", "muted")
        self.update_status_label.setText(self.t(self.update_status or "No update check yet.") + self.update_detail)
        updates.addWidget(self.update_status_label)
        row = QHBoxLayout()
        row.addWidget(self.button("Check for updates", lambda: self.update_requested.emit()))
        row.addStretch()
        updates.addLayout(row)

    def set_update_status(self, text, detail=''):
        self.update_status = text
        self.update_detail = detail
        if hasattr(self, 'update_status_label'):
            self.update_status_label.setText(self.t(text) + detail)

    def translation(self, layout):
        self.heading(layout, "Translation", "English → Modern Standard Arabic")
        card = self.card(layout)
        card.addWidget(self.label("Translation setup", "sectionTitle"))
        title = QHBoxLayout()
        built_in_name = self.label("Built-in Arabic translation")
        built_in_name.setWordWrap(False)
        title.addWidget(built_in_name)
        self.builtin_toggle = ToggleCheckBox(self.t("On" if self.settings.provider == 'Built-in offline' else 'Off'))
        self.builtin_toggle.setChecked(self.settings.provider == 'Built-in offline')
        title.addWidget(self.builtin_toggle)
        title.addStretch()
        card.addLayout(title)
        card.addWidget(self.label("Ready to use. No account, internet connection or setup needed.", "muted"))
        card.addWidget(self.label("Your text stays on your PC when using built-in translation.", "muted"))
        options = QFormLayout()
        card.addLayout(options)
        self.check(options, "cache_enabled", "Remember translations for faster results")
        advanced_toggle = ToggleCheckBox(self.t("Use an external translation service"))
        self.provider_toggle = advanced_toggle
        card.addWidget(advanced_toggle)
        self.translation_advanced = QWidget()
        advanced_layout = QVBoxLayout(self.translation_advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        form = self.form(advanced_layout)
        self.combo(form, "provider", "Provider", [("Built-in offline", "Built-in Arabic translation"), ("Chat compatible", "Chat compatible"), ("Azure Translator", "Azure Translator")])
        self.edit(form, "endpoint", "Base URL", "https://your-provider.example/v1")
        self.edit(form, "model", "Model", "Your provider's model name")
        self.key_field = QLineEdit()
        self.key_field.setEchoMode(QLineEdit.Password)
        self.key_field.setPlaceholderText(self.t("Saved securely — leave blank to keep") if self.settings.api_key else "••••••••")
        form.addRow(self.t("API key"), self.key_field)
        self.remove_key = QCheckBox(self.t("Remove saved key"))
        form.addRow(self.remove_key)
        self.edit(form, "azure_region", "Azure region", "westeurope")
        self.spin(form, "timeout", "Timeout (seconds)", 3, 60)
        advanced_layout.addWidget(self.label("Only recognized text is sent when you choose an external service.", "muted"))
        card.addWidget(self.translation_advanced)
        advanced_toggle.setChecked(self.settings.provider != 'Built-in offline')
        self.translation_advanced.setVisible(advanced_toggle.isChecked())
        self.fields['provider'].setEnabled(advanced_toggle.isChecked())
        self.builtin_toggle.toggled.connect(self.set_builtin_mode)
        advanced_toggle.toggled.connect(lambda enabled: self.set_builtin_mode(not enabled))
        self.fields['provider'].currentIndexChanged.connect(lambda: self.set_builtin_mode(self.fields['provider'].currentData() == 'Built-in offline'))
        row = QHBoxLayout()
        row.addWidget(self.button("Clear cache", lambda: self.clear_data("cache")))
        row.addStretch()
        card.addLayout(row)

        translator = self.card(layout)
        translator.addWidget(self.label("Translator", "sectionTitle"))
        translator.addWidget(self.label("Try a translation", "muted"))
        translator.addWidget(self.label("Uses the translation setup above.", "muted"))
        row = QHBoxLayout()
        self.translation_input = QTextEdit()
        self.translation_input.setAcceptRichText(False)
        self.translation_input.setPlaceholderText(self.t("Type or paste English text here…"))
        self.translation_input.setPlainText(self.translation_draft)
        self.translation_input.setFixedHeight(120)
        self.translation_input.textChanged.connect(lambda: setattr(self, 'translation_draft', self.translation_input.toPlainText()))
        translator.addWidget(self.translation_input)
        self.translate_button = self.button("Translate", self.translate_input, True)
        row.addWidget(self.translate_button)
        row.addStretch()
        translator.addLayout(row)
        from .ui_controls import TranslationResult
        self.translation_feedback = TranslationResult()
        self.translation_feedback.setFixedHeight(135)
        self.translation_feedback.setPlaceholderText(self.t('Your Arabic translation appears here.'))
        translator.addWidget(self.translation_feedback)

    def use_builtin(self):
        self.set_builtin_mode(True)

    def set_builtin_mode(self, enabled):
        for toggle, state in ((self.builtin_toggle, enabled), (self.provider_toggle, not enabled)):
            toggle.blockSignals(True); toggle.setChecked(state); toggle.blockSignals(False)
        self.builtin_toggle.setText(self.t('On' if enabled else 'Off'))
        provider = self.fields['provider']
        provider.blockSignals(True)
        if enabled:
            provider.setCurrentIndex(0)
        elif provider.currentData() == 'Built-in offline':
            provider.setCurrentIndex(1)
        provider.blockSignals(False)
        provider.setEnabled(not enabled)
        self.translation_advanced.setVisible(not enabled)

    def translate_input(self):
        text = self.translation_input.toPlainText().strip()
        if not text:
            self.translation_feedback.setText(self.t('Enter English text to translate.'))
            return
        if len(text) > 6000:
            self.translation_feedback.setText(self.t('Please translate up to 6000 characters at a time.'))
            return
        self.apply(test=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'resize_grip'):
            self.resize_grip.move(self.centralWidget().width() - 20, self.centralWidget().height() - 20)
            self.resize_grip.setVisible(not self.isMaximized())

    def watch_page(self, layout):
        self.heading(layout, "Watch Mode", "Useful words. Less noise.")
        card = self.card(layout)
        card.addWidget(self.label('Translate as your screen changes', 'sectionTitle'))
        card.addWidget(self.label('Press Alt+W. Useful words, sentences and lists translate automatically. Repeated text is remembered.', 'muted'))
        basic = QFormLayout(); card.addLayout(basic)
        self.check(basic, "active_only", "Only translate the app I am using")
        self.check(basic, "filter_ui", "Skip common menu labels")
        self.check(basic, "show_translation_boxes", "Show Translation boxes")
        card.addWidget(self.label('Boxes show pipeline progress: detected 25%, queued 50%, translating 75%, ready 100%. Percentages are stages, not time remaining.', 'muted'))
        card.addWidget(self.label('Choose ignored words and blocked apps in Ignore List.', 'muted'))
        area_card = self.card(layout)
        area_card.addWidget(self.label('Watch area', 'sectionTitle'))
        area_card.addWidget(self.label('Select one or more areas. Watch follows the focused app and remembers your latest setup.', 'muted'))
        count = len(self.settings.watch_areas)
        area_card.addWidget(self.label(f'{count} watch areas selected' if count else 'Entire focused window', 'muted'))
        area_buttons = QHBoxLayout()
        area_buttons.addWidget(self.button('Select watch areas', lambda: self.action_requested.emit('select_watch_area'), True))
        area_buttons.addWidget(self.button(self.l.t('Add Watch Area') + ' · '
            + self.settings.shortcuts.get('add_zone', 'Alt+Shift+W'),
            lambda: self.action_requested.emit('add_zone')))
        area_buttons.addWidget(self.button('Use entire window', lambda: self.action_requested.emit('clear_watch_area')))
        area_buttons.addStretch()
        area_card.addLayout(area_buttons)
        advanced_toggle = ToggleCheckBox(self.t('Advanced tuning'))
        layout.addWidget(advanced_toggle)
        self.watch_advanced = QWidget()
        advanced_layout = QVBoxLayout(self.watch_advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        form = self.form(advanced_layout)
        self.spin(form, "scan_ms", "Scan interval (ms)", 250, 3000, step=50)
        self.spin(form, "stability_ms", "Stabilization delay (ms)", 250, 3000, step=50)
        self.spin(form, "cooldown_ms", "Translation cooldown (ms)", 500, 10000, step=100)
        self.spin(form, "sensitivity", "Detection sensitivity", 10, 90)
        self.spin(form, "max_regions", "Maximum visible regions", 1, 128)
        self.check(form, "debug", "Developer diagnostics")
        advanced_layout.addWidget(self.label("Stable regions are checked before recognition. Smaller intervals use more CPU. Exclusive fullscreen may need Borderless Windowed.", "muted"))
        advanced_layout.addWidget(self.button('Restore recommended settings', self.restore_watch))
        layout.addWidget(self.watch_advanced)
        self.watch_advanced.hide()
        advanced_toggle.toggled.connect(self.watch_advanced.setVisible)

    def restore_watch(self):
        from .config import Settings
        defaults = Settings()
        for key in ('active_only', 'filter_ui', 'scan_ms', 'stability_ms', 'cooldown_ms', 'sensitivity', 'max_regions', 'debug'):
            widget = self.fields[key]; value = getattr(defaults, key)
            widget.setChecked(value) if isinstance(widget, QCheckBox) else widget.setValue(value)

    def overlay_page(self, layout):
        preview_card = self.card(layout)
        self.section_header(preview_card, "Live preview", "See your subtitle against a game scene as you adjust it.", "eye")
        self.preview_appearance = copy.deepcopy(self.settings.overlay)
        self.preview_scene, self.preview = self.make_scene(self.preview_appearance)
        self.preview_scene.setMinimumHeight(140)
        self.preview_scene.setMaximumHeight(140)
        preview_card.addWidget(self.preview_scene)

        presets_card = self.card(layout)
        preset_row = QHBoxLayout()
        preset_title = QVBoxLayout()
        preset_title.setSpacing(4)
        preset_title.addWidget(self.label("Presets", "sectionTitle"))
        preset_title.addWidget(self.label("A useful starting point.", "muted"))
        preset_row.addLayout(preset_title, 1)
        self.preset_buttons = {}
        hints = {"Default": "Balanced", "Subtitle": "Cinematic", "Minimal": "Discreet", "High Contrast": "Easy to read"}
        for name in PRESETS:
            button = QPushButton(self.t(name) + "\n" + self.t(hints[name]))
            button.setObjectName("preset")
            button.setCheckable(True)
            button.setChecked(name == "Default")
            button.setMinimumWidth(120)
            button.clicked.connect(lambda checked=False, n=name: self.apply_preset(n))
            self.preset_buttons[name] = button
            preset_row.addWidget(button, 1)
        presets_card.addLayout(preset_row)
        presets_card.addWidget(self.button("Restore overlay defaults", self.restore_overlay))

        columns = QHBoxLayout()
        columns.setSpacing(18)
        left_widget, right_widget = QWidget(), QWidget()
        left, right = QVBoxLayout(left_widget), QVBoxLayout(right_widget)
        left.setContentsMargins(0, 0, 0, 0); right.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(16); right.setSpacing(16)
        appearance_card = self.card(left)
        self.section_header(appearance_card, "Appearance", "Type, colour and a little breathing room.", "Translation")
        appearance = QFormLayout()
        appearance.setVerticalSpacing(8)
        appearance.setHorizontalSpacing(18)
        appearance.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        appearance_card.addLayout(appearance)
        fonts = QFontDatabase.families()
        preferred = [f for f in ("Segoe UI", "Tahoma", "Arial", "Noto Sans Arabic", "Noto Naskh Arabic") if f in fonts]
        self.combo(appearance, "font", "Font", [(f, f) for f in preferred + [f for f in fonts if f not in preferred]], overlay=True)
        self.spin(appearance, "font_size", "Font size", 14, 54, overlay=True)
        for key, title in (("text_color", "Text color"), ("background_color", "Background color")):
            button = QPushButton(getattr(self.settings.overlay, key))
            self.color_swatch(button)
            button.clicked.connect(lambda checked=False, b=button: self.pick_color(b))
            self.overlay_fields[key] = button
            appearance.addRow(self.t(title), button)
        for key, title, low, high in (("background_opacity", "Background opacity (%)", 0, 100), ("opacity", "Overlay opacity (%)", 20, 100), ("padding", "Padding", 4, 32), ("radius", "Corner radius", 0, 32), ("outline", "Text outline", 0, 3)):
            self.spin(appearance, key, title, low, high, overlay=True)
        self.check(appearance, "shadow", "Text shadow", overlay=True)

        placement_card = self.card(right)
        self.section_header(placement_card, "Positioning", "Keep the subtitle close to the original text.", "Overlay")
        placement = QFormLayout()
        placement.setVerticalSpacing(12)
        placement.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        placement_card.addLayout(placement)
        self.combo(placement, "position", "Position", [(p, p) for p in ("Below", "Above", "Replace")], overlay=True)
        self.spin(placement, "max_width", "Maximum width", 240, 1000, overlay=True)
        placement_card.addWidget(self.label("Placement adjusts to the screen edges and nearby translations.", "muted"))

        behaviour_card = self.card(right)
        self.section_header(behaviour_card, "Behaviour", "Appear softly. Leave when the words do.", "History")
        behaviour = QFormLayout()
        behaviour.setVerticalSpacing(12)
        behaviour.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        behaviour_card.addLayout(behaviour)
        self.check(behaviour, "match_game", "Match game appearance", overlay=True)
        self.check(behaviour, "follow_content", "Follow text when scrolling", overlay=True)
        self.combo(behaviour, "interaction_hold", "Hold to show close buttons", [(s, s) for s in ('Ctrl+Alt', 'Ctrl+Shift', 'Alt+Shift', 'Ctrl+Alt+Shift')], overlay=True)
        behaviour_card.addWidget(self.label("Overrides font and colours while enabled. Dressmaker uses a warm paper style; other games use sampled contrast.", "muted"))
        self.spin(behaviour, "fade_ms", "Fade duration (ms)", 0, 1000, overlay=True, step=20)
        behaviour_card.addWidget(self.label("Translations stay visible until their English text changes or leaves the screen.", "muted"))
        behaviour_card.addWidget(self.label("Subtitles let clicks pass through, so your mouse stays with the game.", "muted"))
        right.addStretch()
        columns.addWidget(left_widget, 1)
        columns.addWidget(right_widget, 1)
        layout.addLayout(columns)
        for widget in self.overlay_fields.values():
            if isinstance(widget, QComboBox): widget.currentIndexChanged.connect(self.update_preview)
            elif isinstance(widget, QCheckBox): widget.toggled.connect(self.update_preview)
            elif isinstance(widget, (QSpinBox, SliderSpin)): widget.valueChanged.connect(self.update_preview)

    def color_swatch(self, button):
        pix = QPixmap(20, 20); pix.fill(QColor(button.text()))
        painter = QPainter(pix)
        painter.setPen(QColor("#b9c5b4")); painter.drawRect(0, 0, 19, 19); painter.end()
        button.setIcon(QIcon(pix))

    def pick_color(self, button):
        color = QColorDialog.getColor(QColor(button.text()), self)
        if color.isValid():
            button.setText(color.name())
            self.color_swatch(button)
            self.update_preview()

    def apply_preset(self, name):
        for preset_name, button in self.preset_buttons.items():
            button.setChecked(preset_name == name)
        for key, value in PRESETS[name].items():
            widget = self.overlay_fields[key]
            widget.setChecked(value) if isinstance(widget, QCheckBox) else widget.setValue(value)
        self.update_preview()

    def restore_overlay(self):
        defaults = OverlaySettings()
        from dataclasses import asdict
        self.overlay_reset = asdict(defaults)
        self.preview_appearance = copy.deepcopy(defaults)
        for key, widget in self.overlay_fields.items():
            value = getattr(defaults, key)
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, (QSpinBox, SliderSpin)):
                widget.setValue(value)
            else:
                widget.setText(value)
                self.color_swatch(widget)
            widget.blockSignals(False)
        for name, button in self.preset_buttons.items():
            button.setChecked(name == 'Default')
        self.update_preview()

    @staticmethod
    def field_value(widget):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, SliderSpin)):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        return widget.text().strip()

    def update_preview(self):
        for key, widget in self.overlay_fields.items():
            setattr(self.preview_appearance, key, self.field_value(widget))
        from .appearance import effective_appearance
        self.preview.appearance = effective_appearance(self.preview_appearance, 'Dressmaker')
        self.preview.refresh()
        self.preview_scene.position = self.preview_appearance.position
        self.preview_scene.arrange()
        effect = self.preview.graphicsEffect()
        if effect is None:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            effect = QGraphicsOpacityEffect(self.preview)
            self.preview.setGraphicsEffect(effect)
        effect.setOpacity(self.preview_appearance.opacity / 100)

    def shortcuts(self, layout):
        self.heading(layout, "Shortcuts", "One shortcut away.")
        form = self.form(layout)
        for key, title in (("quick", "Quick Translate"), ("repeat", "Translate Last Region"), ("watch", "Watch Mode"), ("add_zone", "Add Watch Area"), ("hide", "Hide Translations")):
            widget = QKeySequenceEdit(QKeySequence(self.settings.shortcuts[key].replace("Win", "Meta")))
            widget.setMaximumSequenceLength(1)
            form.addRow(self.t(title), widget)
            self.shortcut_fields[key] = widget
        layout.addWidget(self.label("Click a field, then press your shortcut. Use Ctrl, Alt, Shift or Win with a letter, number or F-key. Conflicts are checked on Apply.", "muted"))

    def ignore_page(self, layout):
        self.heading(layout, "Ignore List", "Keep the useful text.")
        layout.addWidget(self.label("Only standalone labels are ignored. Sentences containing these words still translate.", "muted"))
        self.ignore_search = QLineEdit()
        self.ignore_search.setPlaceholderText(self.t("Search ignored labels…"))
        layout.addWidget(self.ignore_search)
        self.ignore_list = QTreeWidget()
        self.ignore_list.setRootIsDecorated(False)
        self.ignore_list.setHeaderLabels([self.t('English'), self.t('Arabic')])
        self.ignore_list.headerItem().setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        self.ignore_list.header().setStretchLastSection(True)
        self.ignore_list.setColumnWidth(0, 280)
        for word in self.settings.ignored:
            self.add_ignore_item(word)
        self.ignore_list.setMinimumHeight(150)
        layout.addWidget(self.ignore_list)
        self.ignore_search.textChanged.connect(self.search_ignore)
        row = QHBoxLayout()
        for title, callback in (("Add", self.add_ignore), ("Edit", self.edit_ignore), ("Remove", self.remove_ignore), ("Restore defaults", self.restore_ignore)):
            row.addWidget(self.button(title, callback))
        layout.addLayout(row)
        blocked = self.card(layout)
        blocked.addWidget(self.label("Block apps", "sectionTitle"))
        blocked.addWidget(self.label("Watch Mode skips these apps. Quick Translate still works manually.", "muted"))
        self.blocked_list = QListWidget()
        self.blocked_list.setMinimumHeight(110)
        self.blocked_list.setMaximumHeight(180)
        for app in self.settings.blocked_apps:
            self.add_blocked_item(app)
        blocked.addWidget(self.blocked_list)
        buttons = QHBoxLayout()
        buttons.addWidget(self.button("Add app", self.add_blocked_app))
        buttons.addWidget(self.button("Remove", lambda: self.blocked_list.takeItem(self.blocked_list.currentRow())))
        buttons.addStretch()
        blocked.addLayout(buttons)
        region_card = self.card(layout)
        region_card.addWidget(self.label("Saved regions", "eyebrow"))
        self.regions_list = QListWidget()
        self.regions_list.setMaximumHeight(100)
        for region in self.settings.pinned_regions:
            self.regions_list.addItem(region["name"])
        region_card.addWidget(self.regions_list)
        region_row = QHBoxLayout()
        region_row.addWidget(self.button("Pin last region", lambda: self.action_requested.emit("pin")))
        region_row.addWidget(self.button("Translate", lambda: self.action_requested.emit("region:" + str(self.regions_list.currentRow()))))
        region_row.addWidget(self.button("Remove region", lambda: self.action_requested.emit("unpin:" + str(self.regions_list.currentRow()))))
        region_card.addLayout(region_row)

    def add_blocked_item(self, app):
        item = QListWidgetItem(app['name'])
        item.setData(Qt.UserRole, app)
        item.setToolTip(app['path'])
        self.blocked_list.addItem(item)

    def add_blocked_app(self):
        from .app_picker import AppPicker
        from .app_catalog import path_key
        picker = AppPicker(self, self.t)
        if picker.exec() and picker.selected_app:
            app = picker.selected_app
            if path_key(app['path']) not in {path_key(self.blocked_list.item(i).data(Qt.UserRole)['path']) for i in range(self.blocked_list.count())}:
                self.add_blocked_item(app)
        picker.deleteLater()

    def search_ignore(self, query):
        for i in range(self.ignore_list.topLevelItemCount()):
            item = self.ignore_list.topLevelItem(i)
            item.setHidden(query.casefold() not in (item.text(0) + ' ' + item.text(1)).casefold())

    def add_ignore_item(self, text):
        from .ignore_labels import reference_translation
        arabic = reference_translation(text, self.settings.ignored_translations, self.store)
        item = QTreeWidgetItem([text, arabic or '…'])
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        item.setData(1, Qt.UserRole, arabic)
        self.ignore_list.addTopLevelItem(item)
        if not arabic:
            QTimer.singleShot(0, lambda word=text: self.ignore_translation_requested.emit(word))

    def set_ignore_translation(self, english, arabic):
        for i in range(self.ignore_list.topLevelItemCount()):
            item = self.ignore_list.topLevelItem(i)
            if item.text(0) == english and not item.data(1, Qt.UserRole):
                item.setText(1, arabic or '—')
                item.setData(1, Qt.UserRole, arabic)
        self.search_ignore(self.ignore_search.text())

    def add_ignore(self):
        text, ok = QInputDialog.getText(self, self.t("Add"), self.t("Word or phrase"))
        if ok and text.strip() and text.strip().casefold() not in {self.ignore_list.topLevelItem(i).text(0).casefold() for i in range(self.ignore_list.topLevelItemCount())}:
            self.add_ignore_item(text.strip())
            self.search_ignore(self.ignore_search.text())

    def edit_ignore(self):
        item = self.ignore_list.currentItem()
        if item:
            text, ok = QInputDialog.getText(self, self.t("Edit"), self.t("Word or phrase"), text=item.text(0))
            if ok and text.strip():
                arabic, accepted = QInputDialog.getText(self, self.t('Edit'), self.t('Arabic'), text=item.data(1, Qt.UserRole) or '')
                if accepted:
                    item.setText(0, text.strip())
                    item.setText(1, arabic.strip() or '…')
                    item.setData(1, Qt.UserRole, arabic.strip())
                    if not arabic.strip():
                        self.ignore_translation_requested.emit(text.strip())

    def remove_ignore(self):
        self.ignore_list.takeTopLevelItem(self.ignore_list.indexOfTopLevelItem(self.ignore_list.currentItem()))

    def restore_ignore(self):
        self.ignore_list.clear()
        for word in DEFAULT_IGNORE:
            self.add_ignore_item(word)
        self.search_ignore(self.ignore_search.text())

    def history_page(self, layout):
        self.heading(layout, "History", "Your recent translations.")
        form = self.form(layout)
        self.check(form, "history_enabled", "Enable history")
        self.spin(form, "history_limit", "Maximum entries", 10, 5000)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText(self.t("Search English, Arabic or app…"))
        layout.addWidget(self.history_search)
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(260)
        self.history_list.setWordWrap(True)
        layout.addWidget(self.history_list)
        self.history_debounce = QTimer(self)
        self.history_debounce.setSingleShot(True)
        self.history_debounce.timeout.connect(self.refresh_history)
        self.history_search.textChanged.connect(lambda: self.history_debounce.start(180))
        layout.addWidget(self.button("Clear history", lambda: self.clear_data("history")))

    def refresh_history(self):
        self.history_list.clear()
        for english, arabic, timestamp, app in self.store.history(self.history_search.text()):
            self.history_list.addItem(f"{datetime.fromtimestamp(timestamp):%d %b · %H:%M}   {app}\n{english}\n\u202b{arabic}\u202c")
        if not self.history_list.count():
            self.history_list.addItem(self.t("No translations yet."))

    def clear_data(self, table):
        box = QMessageBox(self)
        box.setWindowTitle(self.t("Clear stored data?"))
        box.setText(self.t("This will permanently remove the selected stored data."))
        clear = box.addButton(self.t("Clear cache" if table == "cache" else "Clear history"), QMessageBox.DestructiveRole)
        box.addButton(self.t("Cancel"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is clear:
            self.store.clear(table)
            self.refresh_history()

    def apply(self, checked=False, test=False):
        values = {key: self.field_value(widget) for key, widget in self.fields.items()}
        values["overlay"] = {**self.overlay_reset, **{key: self.field_value(widget) for key, widget in self.overlay_fields.items()}}
        values["shortcuts"] = {key: widget.keySequence().toString(QKeySequence.PortableText).replace("Meta", "Win") for key, widget in self.shortcut_fields.items()}
        items = [self.ignore_list.topLevelItem(i) for i in range(self.ignore_list.topLevelItemCount())]
        values["ignored"] = [item.text(0) for item in items]
        values['ignored_translations'] = {item.text(0): item.data(1, Qt.UserRole) for item in items if item.data(1, Qt.UserRole)}
        values["blocked_apps"] = [self.blocked_list.item(i).data(Qt.UserRole) for i in range(self.blocked_list.count())]
        values["secret"] = self.key_field.text().strip()
        values["remove_secret"] = self.remove_key.isChecked()
        values["test"] = test
        values['test_text'] = self.translation_input.toPlainText().strip() if test else ''
        self.apply_requested.emit(values)

    def update_watch(self, enabled):
        self.watch_enabled = enabled
        self.watch_badge.setText(self.t("Watch is on" if enabled else "Watch is off"))
        self.watch_button.setText(self.t("Disable Watch" if enabled else "Enable Watch"))

    def closeEvent(self, event):
        event.ignore()
        if self.settings.minimize_tray:
            self.hide()
        else:
            self.showMinimized()
