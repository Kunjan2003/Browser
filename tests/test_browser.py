import json
from contextlib import suppress
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import shiboken6
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QMessageBox, QPlainTextEdit

from browser import Browser, address_url, display_url
from journal import Journal

app = QApplication.instance() or QApplication([])


def until(check, timeout=8):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        app.processEvents()
        if check():
            return
        QTest.qWait(20)
    raise AssertionError("Timed out waiting for browser state")


def js(view, code):
    result = []
    view.page().runJavaScript(code, 0, result.append)
    until(lambda: bool(result))
    return result[0]


class HTTPFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/sample.txt":
            data = b"Fictional order TL-1042"
            self.send_response(200)
            self.send_header("Content-Disposition", "attachment; filename=sample.txt")
            self.send_header("Content-Type", "text/plain")
        else:
            data = b'<title>Fixture</title><h1>Local test server</h1><a href="/sample.txt">Download</a>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(data)

    def log_message(self, *args):
        pass


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HTTPFixture)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profile = QWebEngineProfile()
        self.win = Browser(self.root, self.profile)
        self.win.show()
        until(lambda: self.win.view().title() == "Field desk")

    def tearDown(self):
        self.win.close()
        self.win.journal.db.close()
        shiboken6.delete(self.win)
        shiboken6.delete(self.profile)
        app.processEvents()

    def enter(self, address):
        self.win.address.setText(address)
        QTest.keyClick(self.win.address, Qt.Key.Key_Return)

    def test_launch_and_fixture(self):
        page = self.win.view()
        self.assertEqual(js(page, "document.querySelector('h1').textContent"), "Your field desk.")
        js(page, "document.querySelector('.cta').click()")
        until(lambda: page.title() == "Dispatch desk")
        until(lambda: js(page, "document.querySelectorAll('tbody tr').length") == 3)
        js(page, "filter.value='1042';filter.dispatchEvent(new Event('input'))")
        self.assertEqual(js(page, "document.querySelector('#count').textContent"), "1 order")
        js(page, "document.querySelector('tbody a').click()")
        until(lambda: page.title() == "TL-1042")
        details = js(page, "document.querySelector('#detail').innerText")
        self.assertIn("₹1,250", details)
        self.assertIn("₹1,350", details)
        self.assertEqual(self.win.address.text(), "traceleaf://order?id=TL-1042")

    def test_http_tabs_history_reload(self):
        url = f"http://127.0.0.1:{self.server.server_port}/"
        page = self.win.view()
        self.enter(url)
        until(lambda: page.title() == "Fixture" and self.win.back.isEnabled())
        self.assertIn("Local test server", js(page, "document.body.innerText"))
        self.win.new_tab()
        until(lambda: self.win.view().title() == "Field desk")
        self.win.tabs.setCurrentIndex(0)
        self.assertEqual(self.win.address.text(), url)
        self.win.back.click()
        until(lambda: page.title() == "Field desk" and self.win.forward.isEnabled())
        self.win.forward.click()
        until(lambda: page.title() == "Fixture")
        loaded = []
        page.loadFinished.connect(loaded.append)
        page.reload()
        until(lambda: loaded == [True])
        self.win.close_tab(0)
        self.win.close_tab(0)
        self.assertEqual(self.win.tabs.count(), 1)
        until(lambda: self.win.view().title() == "Field desk")

    def test_saved_bookmarks(self):
        self.win.star.click()
        db = Journal(self.root)
        try:
            self.assertEqual(db.bookmarks()[0]["url"], "traceleaf://home")
            self.win.star.click()
            self.assertFalse(db.bookmarks())
        finally:
            db.db.close()

    def test_capture_and_export(self):
        note = "Expected ₹1,250. Observed ₹1,350. <dummy>"
        self.enter("traceleaf://order?id=TL-1042")
        until(lambda: self.win.view().title() == "TL-1042")
        QTest.qWait(350)

        def save_note():
            dialog = app.activeModalWidget()
            dialog.findChild(QPlainTextEdit).setPlainText(note)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(60, save_note)
        self.win.capture_button.click()
        self.assertEqual(self.win.steps.count(), 1)
        path = self.root / "test.zip"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            self.win.export_button.click()
        with ZipFile(path) as archive:
            record, = json.loads(archive.read("trail.json"))
            self.assertEqual(record["note"], note)
            self.assertEqual(record["url"], "traceleaf://order?id=TL-1042")
            self.assertIn(b"&lt;dummy&gt;", archive.read("index.html"))
            image = QImage.fromData(archive.read(record["image"]))
            self.assertGreater(image.width(), 400)
            colors = {image.pixelColor(x,y).name() for x in range(0,image.width(),5)
                      for y in range(0,image.height(),5)}
            self.assertGreater(len(colors), 6, "Screenshot should contain rendered page content")

    def test_download(self):
        url = f"http://127.0.0.1:{self.server.server_port}/"
        self.enter(url)
        until(lambda: self.win.view().title() == "Fixture")
        path = self.root / "saved.txt"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            js(self.win.view(), "document.querySelector('a').click()")
            until(lambda: path.exists() and path.read_bytes() == b"Fictional order TL-1042")

    def test_review_cancel_remove_and_reopen(self):
        # The simulated user can cancel a capture without changing the trail.
        QTimer.singleShot(60, lambda: app.activeModalWidget().reject())
        self.win.capture_button.click()
        self.assertEqual(self.win.steps.count(), 0)
        for title in ("Dispatch desk", "TL-1042"):
            QTimer.singleShot(60, lambda: app.activeModalWidget().accept())
            self.win.capture_button.click()
            self.enter("traceleaf://desk" if title == "Dispatch desk" else "traceleaf://order?id=TL-1042")
            until(lambda: self.win.view().title() == title)
        second = Journal(self.root)
        try:
            self.assertEqual([step["title"] for step in second.steps()], ["Field desk", "Dispatch desk"])
        finally:
            second.db.close()
        self.win.steps.setCurrentRow(0)
        QTimer.singleShot(60, lambda: app.activeModalWidget().reject())
        self.win.inspect.click()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.win.remove.click()
        self.assertEqual(self.win.steps.count(), 1)
        self.assertEqual(self.win.journal.steps()[0]["title"], "Dispatch desk")

    def test_user_link_opens_new_tab(self):
        self.enter(f"http://127.0.0.1:{self.server.server_port}/")
        until(lambda: self.win.view().title() == "Fixture")
        page = self.win.view()
        js(page, """let link=document.querySelector('a'); link.href='/child';
                  link.target='_blank';link.textContent='Open child';link.focus()""")
        QTest.keyClick(page.focusProxy(), Qt.Key.Key_Return)
        until(lambda: self.win.tabs.count() == 2 and self.win.view().url().path() == "/child")
        self.assertEqual(page.url().path(), "/")

    def test_address_rules(self):
        cases = {"example.org": "https://example.org", "localhost:8000/a": "http://localhost:8000/a",
                 "two words": "https://duckduckgo.com/?q=two+words",
                 "traceleaf://desk": "traceleaf://desk"}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(display_url(address_url(raw)), expected)
        for raw in ["", "file:///private", "javascript:alert(1)", "traceleaf://unknown", "https://"]:
            self.assertIsNone(address_url(raw))
