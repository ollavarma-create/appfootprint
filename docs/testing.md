# Fedora KDE alpha test

This is a **read-only prototype**, not a storage cleanup utility.

## Install

From the repository root, with your existing venv activated:

```bash
python -m pip install -e '.[dev]'
pytest -q
appfootprint
```

If `appfootprint` is not found, use `python -m appfootprint.gui`.

Click **Scan Flatpak installations**. The table lists apps and runtimes, their Flatpak installation scope, disk blocks allocated under each deployment directory, and per-app data under `~/.var/app` for user-installed apps.

## What to report

- Output of `flatpak --version`
- Number of apps and runtimes shown
- Whether KiCad appears and which runtime it reports
- Any errors in the rightmost column
- Comparison against `flatpak list --app` and `flatpak list --runtime`
- Whether the scan remains responsive on your machine

Please do not post private filesystem paths or personal data publicly without reviewing them first.

## Known limitations

- This is an inventory, **not** an accurate total physical usage or uninstall-space calculator.
- Deployment directory sizes may omit shared OSTree object-store usage; Btrfs compression/reflinks/snapshots further complicate accounting.
- Runtime relationships are displayed as text but not yet mapped into a dependency graph.
- User data is measured only for user-installed Flatpaks in this alpha.
- Named Flatpak installations beyond user/system are not yet supported.
- Errors and inaccessible directories are reported rather than silently estimated.
- No Firefox/WhatsApp browser cache support yet.
