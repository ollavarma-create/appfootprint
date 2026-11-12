# AppFootprint

**Understand the disk footprint of Linux applications.**

AppFootprint is an early-stage, open-source Linux desktop tool that explains where Flatpak application storage is allocated: installed deployments, shared runtimes and extensions, and per-user application data.

Unlike a general disk analyzer, it aims to show **which application a path belongs to**, **which dependencies are shared**, and **what a user should consider before cleaning anything**. Measurements are based on allocated file blocks; they are **not** guaranteed to represent unique physical usage or recoverable space.

## Current features (alpha)

- Read-only Flatpak app/runtime inventory, with numeric size sorting.
- Experimental Snap inventory (PR #15): compressed images, active/disabled revisions, shared bases, and current-user Snap data.
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

Flatpak and Snap are optional at runtime. The UI detects which implemented providers are available. Neither package manager is required to run the unit tests.

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

## Snap inventory (experimental)

If Snap is installed and snapd responds, AppFootprint shows a **Scan Snap
installations** button. It opens a separate read-only inventory with one row
per revision. The compressed `.snap` backing file is measured, **not** the
mounted squashfs content. Disabled revisions are shown separately and are
not automatically classified as safe to remove. Base and snapd components
are treated as shared. Current-user data is measured only for an active
application revision (revision directory and `common`); other users' data,
system-wide Snap data, snapshots, and arbitrary XDG paths are **not** yet
attributed. Therefore this is not a complete Snap storage total.

For a staged test: first run without Snap, then with snapd but no snaps,
then with one or two installed applications, then after removing them.
Close and reopen AppFootprint between installation/removal stages to
refresh provider availability. Do not uninstall Snap solely to test
AppFootprint; removal of Snap packages and snapd can affect other software.

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
- [Measurement limitations](docs/limitations.md)

## License

GNU General Public License v3.0; see [LICENSE](LICENSE).


### Snap package-manager storage

The Snap inventory now reports `/var/lib/snapd/cache` and
`/var/lib/snapd/snapshots` separately from installed compressed images.
Measurements are allocated file blocks, not automatically reclaimable space.
Snapshot archives can preserve data from removed applications; neither these
archives nor cache entries are automatically deleted. Unknown/inaccessible
paths are not silently counted as zero. Protected cache and snapshot paths
are shown as requiring administrator access; AppFootprint does not elevate
privileges. Shared Snap components show user data as not applicable. GNOME, Mesa and GTK theme Snap
families are marked as **inferred** shared content based on their names;
this is not yet verified from Snap content-interface metadata. Comparing
rounded `df -h` output before/after uninstall does not establish exactly
how many bytes were reclaimed.

### Unified Flatpak and Snap inventory (PR #16)

The main table combines Flatpak applications/runtimes and Snap revisions.
Use **Source** (All / Flatpak / Snap) and **Show** (All / Applications /
Shared components) to filter the same inventory. Small teal Flatpak and
amber Snap markers identify providers without overriding the active Qt/KDE
theme's row, text, or selection colors. Color is never the only identifier.

Each provider can be scanned independently. A new scan replaces only that
provider's results; the other provider's last completed inventory remains
visible. The table's **App total** excludes shared components. Unknown
measurements remain unknown, not zero. Snap cache and snapshots appear in
a separate read-only summary, which may report protected paths.

Flatpak rows retain their existing double-click dependency and storage
explorer. Snap rows currently show a basic read-only details message;
Snap-specific dependency navigation is not yet implemented. The legacy
Snap detail dialog remains in code while the unified interface is tested.

### Scan state and freshness

Each available provider shows its own scan state independently of CLI
availability: **Not scanned**, **Scanning**, **Scanned**, **Scanned with
issues**, **Scan failed**, or **Cancelled**. A completed scan shows the
number of records (including zero) and the local completion time. The action
changes from **Scan** to **Rescan** after a completed scan. Cancellation
preserves the last completed results. Snap may additionally display
**Partial coverage** when protected cache or snapshot directories cannot
be measured; a completed scan never implies full filesystem coverage.
No elevated privileges are requested.

### Storage overview and measurement coverage (PR #17)

A small **Storage overview** above the detailed table shows separate Flatpak
and Snap bars. Teal represents reported bytes in applications (including
measured user data); violet represents reported bytes in shared components.
The bars show the **relative proportions of reported bytes within each
provider**, not physical disk occupancy or space freed by uninstalling.
There is deliberately no cross-provider grand total.

Below each bar, the number of identified measurement targets is reported as
measured, absent or unknown. These are **target counts**, not a percentage of
disk space: one unknown directory could be much larger than every measured
target. Snap cache and snapshot targets contribute to coverage but their
bytes do **not** enter the application/shared-component bar. Unidentified
storage cannot be included in coverage. Measurements are not deduplicated
across Btrfs extents, snapshots, or separate package providers.

The existing detailed inventory remains available below the overview, with
source identity and measurement paths preserved for future drill-down.

### Responsive provider cards (PR #17 refinement)

Available package providers appear as independent cards in the storage
overview. On wide windows the cards are side by side; on narrow windows
they stack vertically. Providers that are not available are hidden, and
RPM will get a card only when its scanner is implemented. Each card owns
its Scan/Rescan action, progress and timestamp, measured-byte bar, and
short target-count coverage indicator. The shared legend explains the
bar colors and the limitations of the target counts. The detailed table
and its source/type filters remain below the cards. All colors used for
measurements have textual labels and are independent of package-source
colors.
