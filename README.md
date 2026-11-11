# AppFootprint

**Understand the disk footprint of Linux applications.**

AppFootprint is an early-stage, open-source Linux desktop tool that explains where Flatpak application storage is allocated: installed deployments, shared runtimes and extensions, and per-user application data.

Unlike a general disk analyzer, it aims to show **which application a path belongs to**, **which dependencies are shared**, and **what a user should consider before cleaning anything**. Measurements are based on allocated file blocks; they are **not** guaranteed to represent unique physical usage or recoverable space.

## Current features (alpha)

- Read-only Flatpak app/runtime inventory, with numeric size sorting.
- Per-user Flatpak data inspection and expandable Storage Explorer.
- Conservative, explanatory Cleanup Advisor; **no deletion**.
- Dependency Explorer for primary runtimes and metadata-compatible extensions.
- In-window dependency navigation with Back, Forward, and history.
- Scan progress and cancellation.

Initial testing targets Fedora KDE. Other Linux desktops are welcome, but are not yet comprehensively validated. The app does not require administrator privileges.

## Requirements

- Linux desktop with a graphical session.
- Python **3.10+**, Python venv support, and a working `flatpak` command.
- PySide6/Qt 6 (installed automatically by pip).
- An internet connection for the initial Python package installation.

Flatpak applications are useful for testing, but not required just to run the unit tests.

## Install and run from source

In a terminal:

```bash
git clone https://github.com/ollavarma-create/appfootprint.git
cd appfootprint

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

pytest -q
appfootprint
```

The editable install (`-e`) uses the checked-out source. The `[dev]` extra installs pytest; for normal use, `python -m pip install -e .` is sufficient.

If `python3 -m venv .venv` fails, install your distribution's Python venv package. On some Linux distributions you may also need additional Qt/XCB system libraries. Please include the exact error in a bug report rather than using `sudo pip`.

To update a source checkout later:

```bash
git pull --ff-only
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Manual test checklist

Please test on your own machine with your own Flatpak inventory:

1. Start AppFootprint and scan. Check that progress appears and the app remains responsive.
2. Cancel a scan. Check that cancellation is reported and previously completed results are preserved.
3. Sort by **Installed**, **User data**, and **App total**; check that the ordering is numeric.
4. Double-click a Flatpak application and expand folders in **Storage Explorer**. Check that the displayed paths correspond to real locations.
5. Try **Copy path**, **Copy containing folder path**, and **Open in file manager** on both a file and a directory.
6. Open a runtime in **Dependency Explorer**. Follow a compatible platform/extension and an application by double-clicking; test **Back** and **Forward**.
7. Expand a dependency tree or storage directory, navigate away, and return. Check that the previous view state remains.
8. Read the Cleanup Advisor's warnings. The application should **not modify or delete files**.

Some dependency links indicate **metadata compatibility**, not proven runtime usage. A runtime without direct users is not necessarily unused.

## Reporting test results

Open a [GitHub issue](https://github.com/ollavarma-create/appfootprint/issues) with:

- Linux distribution/version and desktop environment (e.g. Fedora KDE).
- Python version (`python3 --version`) and Flatpak version (`flatpak --version`).
- What you tried, what happened, and what you expected.
- Relevant terminal output or traceback; optionally a screenshot.

Please **remove usernames, home-directory paths, application data, tokens, and other private details** from logs and screenshots before posting. Do not upload the contents of personal application data.

## Project direction

The roadmap includes broader Linux packaging support, browser/site storage analysis, and more informed cleanup guidance. The current alpha is deliberately read-only.

- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)

## License

GNU General Public License v3.0; see [LICENSE](LICENSE).
