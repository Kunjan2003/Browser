# Traceleaf

A desktop web browser for people who need to show how they reached a result. Browse with tabs, search, back and forward, bookmarks and downloads. Capture a sequence of visible pages with notes, then export a self-contained QA report.

## Run on Windows

1. Install 64-bit Python 3.12 or 3.13 with its Windows Python launcher.
2. Extract or clone the project to a writable folder.
3. Double-click **Start-Traceleaf.cmd**. The first launch downloads the pinned PySide6 dependencies and creates a virtual environment. The window opens on the offline Field desk.

For Linux desktop development, run these commands from the project directory. Use a distribution supported by the PySide6 wheels and a working graphical session.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python browser.py
```

## Try a two-step report

1. Open **Dispatch desk** on the home page and filter the fictional orders by `1042`.
2. Select **Capture step**, enter “Order list shows ₹1,250” and save.
3. Open **TL-1042**. The practice data deliberately shows an order total of ₹1,250 and an invoice total of ₹1,350.
4. Capture a second step describing the ₹100 discrepancy. Double-click either entry in the trail to review the saved image and note.
5. Choose **Export trail**, extract the ZIP and open **index.html**. The report includes both steps in order, their visible URLs, UTC timestamps and viewport screenshots. **trail.json** contains the same metadata for other tools.

Each capture is manual. The application saves bookmarks, your working trail and a Chromium site profile in the operating system's user data directory. A shared export includes the visible page contents, address and notes you chose to capture. Remove steps from the panel to begin a fresh trail. Search phrases use DuckDuckGo.

## Controls

| Action | Shortcut |
| --- | --- |
| Focus the address or search bar | Ctrl+L |
| Open or close a tab | Ctrl+T / Ctrl+W |
| Back or forward | Alt+Left / Alt+Right |
| Reload | Ctrl+R |
| Toggle bookmark | Ctrl+D |
| Capture a step | Ctrl+Shift+S |

## Test

On Windows, run `.venv\Scripts\python.exe -m unittest discover -s tests -v`. On Linux, run `.venv/bin/python -m unittest discover -s tests -v`. For a headless Linux run, prefix the command with `QT_QPA_PLATFORM=offscreen`.

Tests create a temporary profile and journal, load the practice app and a loopback HTTP server in the real Qt WebEngine, operate native controls, and validate the resulting exports and downloads. The suite requires no external website. A Windows GitHub Actions workflow is included.

## Design and maintenance

The interface uses the familiar [Firefox bookmark star](https://support.mozilla.org/en-US/kb/bookmarks-firefox) and the tabbed browsing model illustrated by the [Qt Simple Browser](https://doc.qt.io/qtforpython-6/examples/example_webenginewidgets_simplebrowser.html). Traceleaf adds a local evidence trail for manual QA. There is no account service or cloud upload.

The renderer and network stack come from Qt WebEngine. This is an early desktop release. Dependency updates and security patches must be installed by the maintainer or user. Re-test after changing the version in requirements.txt. The release includes no extension store, account sync or automatic updater.
