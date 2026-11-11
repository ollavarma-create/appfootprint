# Roadmap

## Milestone 0 — Foundation
- [ ] Confirm use cases and non-goals
- [ ] Python packaging and source layout
- [ ] Unit tests and linting
- [ ] Minimal PySide6 UI using mock data

## Milestone 1 — Read-only Flatpak inventory
- [ ] Enumerate user/system apps and runtimes
- [ ] Capture identifiers, refs, versions, and source paths
- [ ] Record verified runtime/extension relationships
- [ ] Measure sizes with explicit measurement definitions
- [ ] Count shared resources only once in global totals
- [ ] Provide scan progress, errors, and cancellation
- [ ] Validate against Flatpak CLI on Fedora KDE

**Exit criteria:** a GUI explains known Flatpak storage without double-counting shared runtime bytes.

## Milestone 2 — Application data
- [ ] Associate `~/.var/app/<app-id>` with apps
- [ ] Classify documented config/cache/data paths
- [ ] Report unknown or inaccessible storage

## Milestone 3 — Browser site storage
- [ ] Research Firefox profile/origin storage layout
- [ ] Map site data sizes without reading private contents
- [ ] Flag unusually large web-app caches
- [ ] Document safety limits and browser-running constraints

## Milestone 4 — Cleanup advisor (future)
- [ ] Conservative, explainable reclaimable-space estimates
- [ ] Explicit user confirmation and native cleanup mechanisms
- [ ] Document potential data loss

## Not in the MVP
- Automatic deletion
- Root-only operation
- Exact reclaimed-byte guarantees
- Every Linux package manager
