# AppFootprint

**Understand before you remove.**

AppFootprint is an early-stage, open-source Linux desktop tool for investigating Flatpak, Snap, RPM and XDG user storage. It reports allocated-file-block observations and explains their limits, without removing data.

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

### Compact provider information (PR #17 refinement)

The provider version appears in the Flatpak or Snap card title. A keyboard-
accessible **ⓘ** button on each card opens a dialog with scan details, the
read-only policy, measurement caveats, and (for Snap) cache/snapshot access
limitations. The same button has a hover tooltip. This replaces the three
long explanatory lines above the overview; scan progress and issue state
remain visible in the cards. The shared bar legend stays visible.

### Experimental RPM inventory foundation (PR #18)

The new `appfootprint.providers.rpm.RpmProvider` is a **read-only,
non-GUI** foundation for the next provider. It runs a single
`rpm -qa --queryformat` query and obtains installed package identities and
RPM-owned file paths from the local database. It then uses `lstat()` and
`st_blocks * 512` for regular files and symlinks, without traversing
directories or symlink targets. Directory entries are excluded to avoid
attributing directory contents to multiple packages.

RPM package classification is **OTHER / unclassified** by default. Package
identities are provider-specific and must not be merged with Snap or Flatpak
names. When a file is missing, unreadable, or its path/inode is shared across
packages, the affected package measurement is marked **incomplete** and its
size is **unknown**. The known-byte subtotal and measured/missing/inaccessible/
ambiguous file counts are retained as metadata, but must not be presented
as the complete package size. These are allocated block indicators, **not
reclaimable or deduplicated physical bytes**; Btrfs reflinks and snapshots
cannot be resolved using `st_blocks` alone. User data is not attributed to
RPM packages.

No RPM UI card, DNF operation, removal, administrator escalation or
filesystem modification is part of PR #18. The provider is deliberately
isolated for synthetic tests and empirical Fedora validation before
integration in PR #19. Run `pytest -q` and optionally inspect results
without changing the system:

```bash
python - <<'PY'
from appfootprint.providers.rpm import RpmProvider
records, issues = RpmProvider().scan()
print("RPM packages:", len(records), "issues:", issues)
print("Incomplete packages:", sum(bool(r.issues) for r in records))
for r in records[:5]:
    print(r.identifier, r.reference, r.measurements[0].status.value,
          r.metadata["known_allocated_bytes"], r.issues)
PY
```

### RPM ownership diagnostics (PR #18 refinement)

The previous `ambiguous_files` count is now split into two mutually
exclusive categories:

- `multi_owned_paths`: the exact path is listed by multiple RPM packages;
- `shared_inode_paths`: a path has one RPM owner, but another distinct
  path refers to the same device/inode (hardlink).

When both conditions hold, the path is classified as multi-owned. The
legacy `ambiguous_files` field remains the sum of these two counts for
compatibility. Both remain **unknown** for per-package complete-byte
accounting; no bytes are assigned to an arbitrary owner. Missing files
are still reported as `absent_files`. The scanner does not yet distinguish
RPM `%ghost` entries from ordinary missing files; this requires
additional RPM file-flag metadata and is deferred rather than guessed.

To compare the new categories on Fedora:

```bash
python - <<'PY'
from collections import Counter
from appfootprint.providers.rpm import RpmProvider

records, issues = RpmProvider().scan()
totals = Counter()
for record in records:
    for field in ("multi_owned_paths", "shared_inode_paths",
                  "absent_files", "inaccessible_files"):
        totals[field] += int(record.metadata[field])
print("Packages:", len(records), "issues:", issues)
for field, count in totals.items():
    print(field, count)
PY
```

### RPM hardlink attribution (PR #18 refinement)

RPM file-path ownership and inode identity are evaluated separately. A
hardlinked inode referenced by paths owned **only by one RPM package** is
counted **once** for that package. Subsequent same-package links are
tracked in `internal_hardlink_paths`, and do not make the package
measurement incomplete. An inode referenced by paths belonging to
**different packages** is not assigned to either package: those paths
remain unknown in `cross_package_hardlink_paths` and the existing
`shared_inode_paths` counter. Exact multi-owned paths take precedence
over inode-sharing classification.

The resulting counts describe path occurrences, not distinct inodes or
recoverable bytes. RPM file absence and permission limitations are
unchanged. On Btrfs, reflink sharing remains undetectable with inode
identity alone.

To inspect the refined diagnostic counts, run:

```bash
python - <<'PY'
from collections import Counter
from appfootprint.providers.rpm import RpmProvider

records, issues = RpmProvider().scan()
fields = ("internal_hardlink_paths", "cross_package_hardlink_paths",
          "multi_owned_paths", "absent_files", "inaccessible_files")
counts = Counter()
for record in records:
    for field in fields:
        counts[field] += int(record.metadata[field])
print("Packages:", len(records), "Incomplete:", sum(bool(r.issues) for r in records))
print("Issues:", issues)
for field in fields:
    print(field, counts[field])
PY
```

### RPM GUI integration (PR #19)

When RPM and its installed-package database are available, AppFootprint shows
a third provider card and a **Scan RPM installations** action. The RPM scan
runs on a cancellable worker thread. RPM records appear in the combined table,
with source filter **RPM** and kind filter **RPM packages**; double-click a row
for per-package measurement diagnostics.

RPM package kinds are deliberately **unclassified**, not applications or
shared dependencies. The RPM overview includes only complete per-package
allocated-byte measurements. Unknown package sizes are not zero and partial
known-byte subtotals are not promoted to complete measurements. The purple
RPM bar is an *unclassified package measurement* bucket, not a dependency
or reclaimable-space estimate. RPM user data, RPM dependency exploration,
and package removal are not implemented. Scans remain read-only and never
request root privileges.

Validation: `pytest -q` and launch the GUI on Fedora. Scan RPM, verify
the overview counts and the **RPM** table filter, sort by **Installed**,
double-click complete and incomplete RPM rows, cancel a rescan, and verify
that Flatpak/Snap scanning and filtering still work.

### RPM capability explorer (PR #20, experimental)

Double-click an RPM package row to open the read-only RPM capability explorer.
It queries installed RPM `REQUIRENAME` and `PROVIDENAME` arrays once in a
background thread, shows candidate installed providers for each requirement
and potential reverse dependents, and supports double-click navigation plus
Back/Forward. The selected package's original measurement diagnostics remain
available through **Show selected package measurement**.

**Important limitations:** these are *capability-name candidate matches*,
not validated RPM dependencies. Requirement versions and flags, rich
expressions, architecture-specific satisfiability, and DNF transaction
resolution are not evaluated. Multiple candidates do not imply all are
required; no match does not prove a missing runtime dependency. The
explorer must never be used to recommend removals or estimate reclaimed bytes.
No root access or package-manager transactions are used.

Test with `pytest -q`; on Fedora open an RPM row (e.g. NetworkManager),
check capability lists, navigate to a candidate and Back, and verify the
measurement-details button. A database query may take a moment; closing the
dialog waits for the worker to finish rather than destroying a running thread.

### UI consistency pass (PR #21)

Provider cards use concise titles (for example `Flatpak (1.18.4)`,
`Snap (2.77.1-0.fc44)`, `RPM (6.0.2)`) without repeating provider
names or RPM's `version` prefix. The unified inventory column
`Package / application ID` applies to all three providers.
Provider information controls have a larger minimum click target.

This is a **presentation-only** change. It does not modify scan results,
measurement arithmetic, dependency matching, or deletion behavior.

#### Fedora/KDE manual regression checklist

1. Run `pytest -q`; verify provider-title tests pass.
2. Launch the GUI at a normal desktop width and narrow it below 820px;
   verify cards wrap, remain readable and the info buttons stay clickable.
3. Scan Flatpak, Snap and RPM; verify each provider's counts, measured
   bytes and unknown counts match the pre-upgrade build.
4. Sort/filter the unified inventory by source and kind; check the
   neutral column label and row double-click actions.
5. In the RPM explorer, navigate forward/back and open measurement
   details for the currently selected package.
6. Cancel and rerun a scan; verify the UI recovers and remains responsive.
7. Check KDE light/dark themes and scaling (100% and 125% where available).

### User Storage (PR #22, experimental)

Open **User Storage…** above the combined inventory table, then click
**Scan user storage**. This separately measures five conventional directories
under the current user's home: `~/.cache`, `~/.config`,
`~/.local/share`, `~/.local/state`, and `~/.var/app`.

The scan is read-only, cancellable, and never follows symlinks or traverses
other filesystems. Hardlinked inodes are counted only once within each tree.
For incomplete scans the complete size is **Unknown**; the known subtotal
is labeled separately. Missing directories are shown as absent.

**Never add these values to Flatpak/Snap/RPM totals.** In particular
`~/.var/app` overlaps with Flatpak user data, and directory measurements
can share Btrfs extents/snapshots. Allocated-byte figures are not promises
of physically unique or reclaimable disk space. The scan neither deletes
nor classifies data as safe to delete.

Validation: run `pytest -q`, launch the GUI, open User Storage, scan
and compare selected directory values with `du -B1` (differences can arise
from inode handling and filesystem accounting). Check cancellation, symlinks,
permission failures, and that the existing three provider cards do not change.

### Storage Investigator (PR #23, experimental)

After scanning **User Storage**, double-click a measured XDG directory
to inspect its immediate children. The read-only investigator measures
each child subtree separately, sorts by reported allocated bytes, and
shows incomplete measurements as unknown with a known subtotal.
Symlinks are measured as links, not traversed; different filesystems
are excluded. The scan is cancellable.

Selecting a child shows two **copy-only** shell inspection examples
(`du` and `find`) with safely quoted paths. AppFootprint never
executes these commands or generates deletion commands. No automatic
judgment about whether a cache or application data can be removed.

Each child is independently measured, so shared hardlinks across
children, Btrfs reflinks and snapshots can overlap. **Do not sum
child measurements as physically unique or reclaimable bytes.**

Fedora/KDE validation: run `pytest -q`; scan User Storage; double-click
`~/.cache` and `~/.var/app`; inspect ordering and unknowns; select a
row and copy the inspection commands; cancel and rescan; ensure other
provider cards are unaffected.

## Alpha release readiness (PR #24)

The application remains **read-only**. It does not run generated shell
commands, delete data, elevate privileges, or claim that reported allocated
bytes equal safely reclaimable space. Btrfs sharing, hardlinks and snapshots
can make measurements non-additive.

Hover over measured sizes in the main inventory, User Storage and Storage
Investigator to see exact byte counts; unknown values remain unknown and
partial measurements show a clearly labeled known subtotal.

### Pre-release acceptance checklist

1. Run `python -m pytest -q` on a clean source checkout.
2. Run `python -m compileall -q src/appfootprint`.
3. Launch as an unprivileged user on Fedora KDE; scan Flatpak, Snap, RPM
   and XDG user storage, and check that the existing totals do not change.
4. Confirm exact-byte tooltips, including unknown and incomplete cases.
5. Cancel and restart each available scan; inspect the RPM explorer and
   the Storage Investigator's copy-only `du`/`find` commands.
6. Check window resizing, KDE light/dark themes and text readability.
7. Before publishing an AppImage, build it in a controlled older Linux
   environment, verify runtime compatibility and test on Fedora KDE.
   A build passing unit tests alone does **not** establish AppImage portability.
8. Publish alpha releases with a SHA256 checksum, documented supported
   architectures and distributions, and a clear warning about experimental
   inventory coverage.

Future CI workflows should test on pull requests, create downloadable
build artifacts on demand, and publish GitHub Releases only for explicitly
approved version tags. Package-manager CLI tools remain host dependencies;
they should not be bundled as substitute system package databases.
