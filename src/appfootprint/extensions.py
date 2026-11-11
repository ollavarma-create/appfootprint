"""Read-only Flatpak extension-point metadata and compatibility matching."""
from __future__ import annotations

import configparser
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtensionPoint:
    name: str
    versions: tuple[str, ...]
    subdirectories: bool
    conditions: tuple[str, ...]


def parse_extension_points(metadata: str) -> list[ExtensionPoint]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(metadata)
    result = []
    for section in parser.sections():
        if not section.startswith("Extension "):
            continue
        name = section.removeprefix("Extension ").strip()
        if not name:
            continue
        values = parser[section]
        versions = tuple(v.strip() for v in
                         values.get("versions", values.get("version", "")).split(";")
                         if v.strip())
        conditions = tuple(f"{key}={values[key]}" for key in
                           ("enable-if", "download-if", "autoprune-unless")
                           if key in values)
        result.append(ExtensionPoint(
            name, versions,
            values.get("subdirectories", "false").lower() == "true",
            conditions,
        ))
    return result


def compatible_extension(point: ExtensionPoint, extension_ref: str,
                         platform_ref: str) -> bool:
    """Metadata compatibility, NOT evidence of actual activation."""
    platform_parts = platform_ref.removeprefix("runtime/").split("/")
    extension_parts = extension_ref.removeprefix("runtime/").split("/")
    if len(platform_parts) != 3 or len(extension_parts) != 3:
        return False
    name, arch, branch = extension_parts
    if arch != platform_parts[1]:
        return False
    if point.subdirectories:
        if not name.startswith(point.name + "."):
            return False
    elif name != point.name:
        return False
    allowed = point.versions or (platform_parts[2],)
    return branch in allowed
