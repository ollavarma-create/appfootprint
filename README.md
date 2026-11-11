# AppFootprint

**Understand the true disk footprint of Linux applications.**

AppFootprint is an open-source Linux desktop project to explain how much storage applications really use: installed packages, shared runtimes, application data, caches, and related resources.

Traditional disk analyzers tell you *where* bytes are. AppFootprint aims to explain *which application they belong to*, *why they exist*, and *what would happen if they were removed*.

## Goals

- Present an application-centric graphical storage breakdown.
- Include Flatpak apps, runtimes, SDKs, and per-application data.
- Eventually reveal browser site storage, including web-app caches.
- Distinguish exclusive storage from shared dependencies; never double-count shared bytes in system totals.
- Provide conservative, understandable recommendations.

## Initial scope

The first version targets Linux desktops, starting with Fedora KDE, using Python 3 and PySide6 (Qt 6). It will inventory installed Flatpak apps and runtimes, attribute shared dependencies, inspect user-scoped Flatpak data, and present a **read-only** GUI with source paths.

Browser site storage and cleanup recommendations are later milestones. No automatic deletion or elevated privileges are planned for the MVP.

## Status

Early design phase; no working release yet.

- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)

## License

GNU General Public License v3.0; see [LICENSE](LICENSE).
