# Architecture — unified application inventory

## Purpose and boundaries

AppFootprint explains what occupies storage, which applications or shared
components may be responsible, and what a user should consider before taking
action. It is **not** a disk cleaner. The program does not delete files,
execute cleanup commands, or request root privileges.

The existing Flatpak scanner and Qt UI remain the functional baseline.
PR #13 introduces additive contracts; it does **not** claim Snap, RPM or
AppImage inventory support.

## Layers

```text
Qt presentation (existing Flatpak UI)
          |
Existing scanner.Item  ----> FlatpakProvider adapter
                                    |
                           InventoryRecord (neutral)
                                    |
                         attribution / measurements
                                    |
                         future provider consumers

Future providers: Snap | RPM/DNF | AppImage
Future analyzers: XDG user paths | caches | logs | browser profiles
```

- `scanner.py` remains the current Flatpak implementation and source of
  truth for existing UI behavior.
- `inventory.py` defines package-manager-neutral, Qt-independent data types.
- `providers/flatpak.py` translates legacy Flatpak results to those types.
- New providers will implement `InventoryProvider.scan(progress, cancelled)`
  and return records plus nonfatal issues.
- User-data analyzers will eventually be separate from package providers,
  allowing one application to be associated with multiple evidence-backed
  paths regardless of installation mechanism.

No migration of the UI or existing scanner is attempted in this PR.

## Record identity and relationships

A record key includes **provider, reference and scope**. The same application
may be installed by Flatpak and RPM, or in both user and system scopes.
Provider-specific revision, architecture, and branch should remain in the
reference. Dependencies are relationships, not additional per-app bytes.

A future cross-provider application identity resolver may group records for
display, but must not collapse them based on a similar name alone.

## Measurement and evidence

Every `StorageMeasurement` has:

- **Role:** direct installation, shared dependency, or user data.
- **Status:** measured, absent, inaccessible, error, or not applicable.
- **Allocated bytes:** a nonnegative integer **only** for measured status.
- **Evidence:** confirmed, strong match, possible match, or unknown.
- **Source path and reason:** enough context to explain the result.

`0 B` is a successful measurement of zero; it must not stand in for a
permission error or an unavailable path. The Flatpak legacy scanner currently
represents absent `~/.var/app/<id>` as zero; the adapter preserves that
legacy value rather than asserting a new absence status. Improving this
distinction in the underlying scanner is future work.

`measured_total` refuses to calculate a total when selected measurements
are unknown or inaccessible. This conservative policy prevents false
precision. A sum of allocated blocks is **not** an estimate of bytes
reclaimable after uninstalling a package.

Hard links, OSTree, Btrfs compression, reflinks, snapshots, sparse files and
Snap squashfs images can all make physical and reclaimable usage differ from
the measured values. Shared components must never be silently charged in
full to every application.

## Provider-specific future design

| Provider | Inventory source | Special accounting considerations |
| --- | --- | --- |
| Flatpak (implemented) | Flatpak CLI, deployment paths, metadata | OSTree, shared runtimes, extensions, per-user `~/.var/app` |
| Snap (planned) | `snap` metadata and mounted revisions | Squashfs backing images versus mount contents; inactive revisions; bases |
| RPM/DNF (planned) | RPM database and package metadata | File ownership, shared libraries, dependency groups; no direct user-data ownership |
| AppImage (planned) | User-selected/discovered AppImage files | No authoritative global registry; avoid claiming paths based on name alone |

The absence of a package manager must not crash the application. Do not
automatically invoke `sudo` or shell-evaluate metadata.

## User data attribution

XDG locations such as `~/.config`, `~/.local/share`,
`~/.local/state` and `~/.cache` require separate evidence gathering.
Matching directory names is not proof of ownership. Distinguish confirmed,
strong, possible and unknown associations; do not infer that caches,
telemetry, diagnostics or archived logs are disposable.

A package provider identifies installations; a data analyzer identifies
paths; an attribution layer explains the evidence connecting them.

## Guidance rather than deletion

The advisor may eventually provide **copyable, reviewed commands** (for
example `flatpak uninstall --unused` or `sudo dnf autoremove`) with
context, expected consequences and warnings. AppFootprint itself must not
run these commands or perform deletions. Commands should be specific to
the detected provider and presented as instructions, never as a guaranteed
safe action. No cleanup command UI is introduced in PR #13.

An AppImage distribution of AppFootprint would ordinarily run with the
user's normal permissions; it is not inherently sandboxed like Flatpak.
That does not bypass filesystem permissions. Do not run the entire GUI
as root to overcome access errors.

## Privacy, failure handling and tests

- Do not read personal file contents or upload inventory telemetry.
- Keep all scanning read-only and responsive/cancellable.
- Preserve error and permission-denied states rather than replacing them
  with zero.
- Test provider contracts with fake records, without requiring Flatpak,
  Snap, RPM, Qt or any particular installed applications.
- Maintain existing Flatpak UI/scanner regression tests while migrating
  incrementally.
- Test against at least two different Linux installations before making
  broad compatibility claims.

## Proposed implementation sequence

1. **PR #13:** neutral model, Flatpak adapter, tests, architectural guidance.
2. **Snap inventory:** isolated provider with revision/base accounting.
3. **RPM inventory:** package ownership and dependency relationships.
4. **XDG attribution:** evidence-based association of user data.
5. **Guidance:** explanatory, copyable commands; never automatic deletion.

The priority is reliable explanations, not maximal reclaimed-space estimates.
