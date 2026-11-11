# Architecture — initial proposal

## Core idea

File scanners show **where** bytes are. AppFootprint aims to show **why** they exist and **which applications use them**.

```text
PySide6 GUI
  └── Scan coordinator
      ├── Flatpak inventory provider
      ├── Storage accounting engine
      ├── User-data scanner
      └── Future: browser site-storage provider
```

The accounting engine should be independent of Qt and testable without a GUI. Providers return structured records, not raw shell output.

## Flatpak inventory

Use supported Flatpak commands and metadata, preferring machine-readable output when available. Call subprocesses with argument arrays, never shell strings. Distinguish user and system installations, refs, architectures, and branches. Track runtime relationships explicitly; do not assume SDKs or optional extensions are required by each app.

## Storage accounting

Separate:
- **Exclusive** bytes attributable to one app or its unique data.
- **Shared** bytes belonging to runtimes/extensions used by multiple apps.
- **Unknown** bytes not reliably attributed.

Count each shared object **once** in global totals. A per-app detail view may show the full size of a shared dependency, but must not silently add it to every app's exclusive footprint.

OSTree deduplication, hard links, reflinks, sparse files, Btrfs compression, and snapshots complicate physical size and reclaimable-space estimates. Clearly label apparent size, allocated blocks, and estimated reclaimable bytes; never imply these are equivalent.

## User data

Start with documented paths such as `~/.var/app/<app-id>`. Distinguish configuration, cache, and user data only when supported by evidence. Never assume an app's data is disposable.

## Interface

Use PySide6 with a Qt model/view architecture. Provide an overview, per-app drill-down, source paths, scan errors, and responsive background scanning. Follow KDE/Qt themes and accessibility conventions.

## Safety and privacy

- Entire MVP is read-only; no cleanup buttons.
- No sudo for basic user scans.
- No telemetry or network requirement.
- Do not inspect personal file contents.
- Explicitly show incomplete results and permission errors.

## Testing

Mock Flatpak subprocess calls; test shared-dependency attribution, hard links, inaccessible directories, and unknown storage. Validate on Fedora KDE before broader distro claims.

## Questions to investigate

- What can be measured reliably for OSTree-backed Flatpak installations on Btrfs?
- How should optional SDKs and extensions be attributed?
- How can Firefox origin storage be mapped without examining private content?
