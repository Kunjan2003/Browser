import re
import sqlite3
import sys

import shiboken6
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QLockFile, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QColor, QKeySequence, QPixmap, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfileBuilder, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from journal import Journal

ASSETS = Path(__file__).resolve().parent / "assets"
LOCAL = {name: QUrl.fromLocalFile(str(ASSETS / (name + ".html"))) for name in ("home", "desk", "order")}
HOME = LOCAL["home"]
STYLE = """
QMainWindow, QWidget#shell, QTabWidget::pane { background:#f4f5ed; border:0 }
QWidget {font-family:"Segoe UI",Arial,sans-serif; font-size:14px; color:#183a30}
QWidget#bar {background:#e5ecdf;border-bottom:1px solid #becfba}
QPushButton {background:#f7f8ef;border:1px solid #bfcebb;border-radius:6px;padding:6px 10px}
QPushButton:hover {background:#dce9d5} QPushButton:disabled {color:#819382}
QPushButton#primary {background:#214f3f;color:white;border:1px solid #214f3f;font-weight:bold}
QLineEdit,QPlainTextEdit {background:#fffef8;border:1px solid #aebfa9;border-radius:6px;padding:6px;selection-background-color:#325d4c}
QTabBar::tab {background:#dfe7da;padding:7px 12px;margin-right:2px;border-top-left-radius:5px;border-top-right-radius:5px}
QTabBar::tab:selected {background:#f9faf2;color:#174b35}
QListWidget {background:#f9faf2;border:1px solid #c5d1be;border-radius:7px}
QListWidget::item {padding:8px;border-bottom:1px solid #dde3d7} QListWidget::item:selected {background:#d2e5cf;color:#173f2c}
QLabel#heading {font:bold 23px Georgia;color:#1d4939}
QStatusBar {background:#e5ecdf} QToolTip {color:black;background:white}
"""


def display_url(url):
    if url.isLocalFile():
        for key, page in LOCAL.items():
            if url.toLocalFile() == page.toLocalFile():
                alias = QUrl("traceleaf://" + key)
                if url.hasQuery():
                    alias.setQuery(url.query())
                if url.hasFragment():
                    alias.setFragment(url.fragment())
                return alias.toString()
    visible = QUrl(url)
    if visible.password():
        visible.setPassword(None)
    return visible.toString()


def address_url(text):
    text = text.strip()
    if not text:
        return None
    if text.startswith("traceleaf://"):
        alias = QUrl(text)
        if alias.host() in LOCAL and alias.path() in ("", "/"):
            mapped = QUrl(LOCAL[alias.host()])
            if alias.hasQuery():
                mapped.setQuery(alias.query())
            if alias.hasFragment():
                mapped.setFragment(alias.fragment())
            return mapped
        return None
    if re.match(r"^https?://", text, re.I):
        url = QUrl(text)
    elif re.match(r"^localhost(?:[:/?#]|$)|^127\.\d+\.\d+\.\d+(?:[:/?#]|$)|^\[::1\](?:[:/?#]|$)", text, re.I):
        url = QUrl("http://" + text)
    elif re.match(r"^[^\s/:?#]+\.[^\s/:?#]+(?::\d+)?(?:[/?#].*)?$", text):
        url = QUrl("https://" + text)
    elif re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", text):
        return None
    else:
        return QUrl("https://duckduckgo.com/?" + urlencode({"q": text}))
    return url if url.isValid() and url.host() else None


class BrowserPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, kind, main_frame):
        if url.isLocalFile():
            return any(url.toLocalFile() == local.toLocalFile() for local in LOCAL.values())
        return url.scheme() in ("https", "http") or url == QUrl("about:blank")


class Browser(QMainWindow):
    def __init__(self, directory, profile):
        super().__init__()
        self.profile = profile
        self.journal = Journal(directory)
        self.resize(1220, 800)
        self.setWindowTitle("Traceleaf")
        self.setStyleSheet(STYLE)
        self.shell = QWidget(objectName="shell")
        self.setCentralWidget(self.shell)
        layout = QVBoxLayout(self.shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QWidget(objectName="bar")
        tools = QHBoxLayout(bar)
        layout.addWidget(bar)

        def button(label, tip, func):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
            btn.clicked.connect(func)
            tools.addWidget(btn)
            return btn

        self.back = button("←", "Back", lambda: self.view().back())
        self.forward = button("→", "Forward", lambda: self.view().forward())
        button("↻", "Reload", lambda: self.view().reload())
        button("Home", "Field desk", lambda: self.view().setUrl(HOME))
        self.address = QLineEdit(placeholderText="Search or enter a URL")
        self.address.setAccessibleName("Address or search")
        self.address.returnPressed.connect(self.navigate)
        tools.addWidget(self.address, 1)
        self.star = button("☆", "Toggle bookmark", self.bookmark)
        self.saved = button("Bookmarks", "Open bookmarks", self.bookmark_menu)
        button("+", "New tab", self.new_tab)
        self.trail_button = button("Trail", "Toggle trail panel", self.toggle_panel)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.split, 1)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.currentChanged.connect(self.sync)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.split.addWidget(self.tabs)
        self.panel = QWidget()
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(15, 20, 15, 14)
        panel.setSpacing(10)
        panel.addWidget(QLabel("Evidence trail", objectName="heading"))
        hint = QLabel("Capture the current view and add a note at each step.")
        hint.setWordWrap(True)
        panel.addWidget(hint)
        self.capture_button = QPushButton("Capture step", objectName="primary")
        self.capture_button.clicked.connect(self.capture)
        panel.addWidget(self.capture_button)
        self.steps = QListWidget()
        self.steps.setAccessibleName("Captured steps")
        self.steps.itemDoubleClicked.connect(self.inspect_step)
        panel.addWidget(self.steps, 1)
        actions = QHBoxLayout()
        self.inspect = QPushButton("View step")
        self.inspect.clicked.connect(self.inspect_step)
        actions.addWidget(self.inspect)
        self.remove = QPushButton("Remove")
        self.remove.clicked.connect(self.remove_step)
        actions.addWidget(self.remove)
        panel.addLayout(actions)
        self.export_button = QPushButton("Export trail…")
        self.export_button.clicked.connect(self.export_dialog)
        panel.addWidget(self.export_button)
        self.steps.currentItemChanged.connect(self.selection_changed)
        self.split.addWidget(self.panel)
        self.split.setSizes([920, 285])
        self.split.setStretchFactor(0, 1)
        self.profile.downloadRequested.connect(self.download)
        self.shortcuts = []
        for key, action in {
            "Ctrl+L": self.focus_address, "Ctrl+T": self.new_tab,
            "Ctrl+W": lambda: self.close_tab(self.tabs.currentIndex()),
            "Ctrl+R": lambda: self.view().reload(), "Alt+Left": lambda: self.view().back(),
            "Alt+Right": lambda: self.view().forward(), "Ctrl+D": self.bookmark,
            "Ctrl+Shift+S": self.capture,
        }.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(action)
            self.shortcuts.append(shortcut)
        self.refresh_steps()
        self.add_tab(HOME)

    def view(self):
        return self.tabs.currentWidget()

    def focus_address(self):
        self.address.setFocus()
        self.address.selectAll()

    def new_tab(self):
        self.add_tab(HOME)
        self.focus_address()

    def add_tab(self, url=None):
        view = QWebEngineView()
        page = BrowserPage(self.profile, view)
        view.setPage(page)
        page.setBackgroundColor(QColor("#f5f5ea"))
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        page.newWindowRequested.connect(self.open_popup)
        view.titleChanged.connect(lambda title: self.set_tab_title(view, title))
        view.urlChanged.connect(lambda _: self.sync() if view is self.view() else None)
        view.loadFinished.connect(lambda ok: self.finished(view, ok))
        index = self.tabs.addTab(view, "New tab")
        self.tabs.setCurrentIndex(index)
        if url is not None:
            view.setUrl(url)
        return view

    def open_popup(self, request):
        if request.isUserInitiated():
            request.openIn(self.add_tab().page())

    def close_tab(self, index):
        if index < 0:
            return
        old = self.tabs.widget(index)
        self.tabs.removeTab(index)
        old.deleteLater()
        if not self.tabs.count():
            self.new_tab()

    def set_tab_title(self, view, title):
        index = self.tabs.indexOf(view)
        if index >= 0:
            self.tabs.setTabText(index, (title or "New tab")[:32].replace("&", "&&"))
            self.tabs.setTabToolTip(index, title)
            if view is self.view():
                self.setWindowTitle((title or "New tab") + " · Traceleaf")

    def navigate(self):
        url = address_url(self.address.text())
        if url is None:
            self.statusBar().showMessage("Enter a web address or a search phrase.", 4000)
            return
        self.view().setFocus()
        self.view().setUrl(url)

    def finished(self, view, ok):
        if view is self.view():
            self.sync()
            if not ok:
                self.statusBar().showMessage("Page did not finish loading. Check the address or reload.", 5000)

    def sync(self, *_):
        view = self.view()
        if view is None:
            return
        url = display_url(view.url())
        self.address.setText(url)
        self.setWindowTitle((view.title() or "New tab") + " · Traceleaf")
        self.back.setEnabled(view.history().canGoBack())
        self.forward.setEnabled(view.history().canGoForward())
        self.star.setText("★" if any(row["url"] == url for row in self.journal.bookmarks()) else "☆")

    def bookmark(self):
        view = self.view()
        if view.url().isEmpty():
            return
        try:
            added = self.journal.toggle_bookmark(display_url(view.url()), view.title())
            self.sync()
            self.statusBar().showMessage("Bookmark saved" if added else "Bookmark removed", 2500)
        except sqlite3.Error as error:
            QMessageBox.warning(self, "Bookmark", str(error))

    def bookmark_menu(self):
        menu = QMenu(self)
        for row in self.journal.bookmarks():
            action = menu.addAction((row["title"] or row["url"]).replace("&", "&&"))
            action.setData(row["url"])
        if menu.isEmpty():
            menu.addAction("No saved bookmarks").setEnabled(False)
        chosen = menu.exec(self.saved.mapToGlobal(self.saved.rect().bottomLeft()))
        if chosen and chosen.data():
            url = address_url(chosen.data())
            if url is not None:
                self.view().setUrl(url)

    def toggle_panel(self):
        self.panel.setVisible(self.panel.isHidden())

    def capture(self):
        view = self.view()
        if not view or view.url().isEmpty():
            return
        title, url = view.title() or "Untitled", display_url(view.url())
        data = QByteArray()
        output = QBuffer(data)
        output.open(QIODevice.OpenModeFlag.WriteOnly)
        if not view.grab().save(output, "PNG"):
            QMessageBox.warning(self, "Capture", "The page image could not be captured.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Capture step")
        form = QVBoxLayout(dialog)
        form.addWidget(QLabel("Describe this step"))
        note = QPlainTextEdit(placeholderText="What did you expect? What did you observe?")
        form.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        dialog.resize(440, 210)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.journal.capture(title, url, note.toPlainText().strip(), bytes(data))
                self.panel.show()
                self.refresh_steps()
                self.steps.setCurrentRow(self.steps.count() - 1)
            except sqlite3.Error as error:
                QMessageBox.warning(self, "Capture", str(error))

    def refresh_steps(self):
        self.steps.clear()
        for index, step in enumerate(self.journal.steps(), 1):
            item = QListWidgetItem(f"{index:02}   {step['title']}")
            item.setToolTip(step["note"] or step["url"])
            item.setData(Qt.ItemDataRole.UserRole, step["id"])
            self.steps.addItem(item)
        self.export_button.setEnabled(self.steps.count() > 0)
        self.selection_changed()

    def selection_changed(self, *_):
        selected = self.steps.currentItem() is not None
        self.inspect.setEnabled(selected)
        self.remove.setEnabled(selected)

    def selected_id(self):
        return self.steps.currentItem().data(Qt.ItemDataRole.UserRole)

    def inspect_step(self, *_):
        if self.steps.currentItem() is None:
            return
        step = self.journal.db.execute("SELECT * FROM checkpoints WHERE id=?", (self.selected_id(),)).fetchone()
        dialog = QDialog(self)
        dialog.setWindowTitle(step["title"])
        layout = QVBoxLayout(dialog)
        image = QPixmap()
        image.loadFromData(step["png"], "PNG")
        preview = QLabel()
        preview.setPixmap(image.scaled(680, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(preview)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(f"{step['url']}\n{step['created']}\n\n{step['note']}")
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def remove_step(self):
        if self.steps.currentItem() is None:
            return
        if QMessageBox.question(self, "Remove step", "Remove the selected capture from this trail?") == QMessageBox.StandardButton.Yes:
            try:
                self.journal.remove(self.selected_id())
                self.refresh_steps()
            except sqlite3.Error as error:
                QMessageBox.warning(self, "Remove step", str(error))

    def export_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export trail", "traceleaf-trail.zip", "ZIP archive (*.zip)")
        if path:
            try:
                self.journal.export(path)
                self.statusBar().showMessage("Trail exported. Unzip it and open index.html.", 6000)
            except (OSError, sqlite3.Error) as error:
                QMessageBox.warning(self, "Export failed", str(error))

    def download(self, request):
        name = Path(request.suggestedFileName()).name
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        destination, _ = QFileDialog.getSaveFileName(self, "Save download", str(Path(folder) / name))
        if not destination:
            request.cancel()
            return
        path = Path(destination)
        request.setDownloadDirectory(str(path.parent))
        request.setDownloadFileName(path.name)
        request.stateChanged.connect(lambda state: self.statusBar().showMessage(state.name + " · " + path.name, 5000))
        request.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Traceleaf")
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "profile.lock"))
    if not lock.tryLock():
        QMessageBox.information(None, "Traceleaf", "This profile is already open or unavailable.")
        return 1
    builder = QWebEngineProfileBuilder()
    builder.setPersistentStoragePath(str(directory / "sites"))
    builder.setCachePath(str(directory / "cache"))
    profile = builder.createProfile("traceleaf", app)
    window = Browser(directory, profile)
    window.show()
    result = app.exec()
    window.journal.db.close()
    shiboken6.delete(window)
    shiboken6.delete(profile)
    return result


if __name__ == "__main__":
    sys.exit(main())
