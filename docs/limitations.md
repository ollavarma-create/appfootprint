# Measurement limitations

AppFootprint is a read-only inventory, not a disk-cleanup tool. This page is
intended to become the source for a future **Help → Limitations** view.

## Permissions and coverage

- The application runs with the current user's permissions. It does not use
  sudo, pkexec, or an elevated helper.
- Protected Snap directories such as `/var/lib/snapd/cache` and
  `/var/lib/snapd/snapshots` may not be readable. Their sizes are **unknown**,
  not zero. A partial inventory must not be presented as a complete total.
- The Snap inventory currently measures the current user's known Snap data
  paths; other users' data and some system locations are not covered.
- A successful measurement of every *known* path does not mean that all
  package-manager storage on the system has been discovered.

## Meaning of measured bytes

- File measurements use allocated blocks (`st_blocks * 512`), not necessarily
  the number of unique physical bytes that would be freed by deletion.
- Btrfs copy-on-write extents, reflinks, snapshots, filesystem metadata,
  hard links, and other sharing can make sums differ from `df` or from
  space actually reclaimed after removal.
- Snap image sizes describe compressed backing `.snap` files, not the size
  of the mounted squashfs content. Mounted copies are deliberately excluded.
- Snap cache and snapshots are reported separately from installed images.
  Neither is automatically disposable; snapshot archives may contain
  application data retained after uninstall.
- A before/after comparison of rounded `df -h` output cannot establish
  an exact reclaimed byte count.

## Classification and dependency uncertainty

- Known Snap base packages and system components are separated from apps.
  GNOME, Mesa, and GTK theme Snap families are currently classified as
  *inferred* shared content by name, not by verified content-interface
  metadata. Other shared packages may be missed.
- Flatpak runtime compatibility metadata is not proof that a runtime is
  currently in use. A runtime with no identified direct users is not
  necessarily safe to remove.
- Missing, inaccessible, or failed measurements must remain visibly unknown.
  Shared components must not be added to each application's individual total.

## Safety

AppFootprint does not delete packages, cache entries, snapshots, or user files.
It does not request administrator privileges. Any future privileged measurement
feature would require separate security design and explicit user consent.
