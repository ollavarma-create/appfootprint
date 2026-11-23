# Storage identification catalogs

AppFootprint measures **every top-level hidden directory** in your home folder,
including directories it cannot identify. Identification is optional and does
not affect measurement. The program never deletes files.

## Built-in catalog

The built-in catalog is maintained in
`src/appfootprint/storage_explanations.py`. It contains a deliberately small
set of common XDG, Flatpak, browser, developer-tool, and security directories.
Names are hints, **not evidence** that an application owns a directory.

## Optional personal catalog

AppFootprint can read an additional local JSON file:

- Default: `~/.config/appfootprint/catalog.json`
- With `XDG_CONFIG_HOME` set: `$XDG_CONFIG_HOME/appfootprint/catalog.json`

Example:

```json
{
  "version": 1,
  "directories": {
    ".myeditor": {
      "title": "My Editor",
      "purpose": "Editor support files",
      "contents": "Plugins and user preferences",
      "caution": "Settings may be important; inspect before making changes.",
      "category": "Development tools",
      "documentation": "https://example.org/docs"
    }
  }
}
```

Only `title` is required. Names must be single hidden directory names,
not paths or patterns. Unknown names remain unidentified. Entries for
built-in names are ignored, so personal catalogs cannot replace built-in
safety warnings. Invalid or oversized catalogs are ignored. No scripts,
shell commands, regular expressions, downloads, or cleanup actions are
supported. Rescan User Storage after editing the file to reload it.

AppFootprint **does not bundle or download third-party catalogs**.
If you choose to adapt information from another project, check its license
and permissions, especially before redistributing the result. Your local
catalog remains under your control.

The catalog is for explanation, not a filesystem permission policy.
