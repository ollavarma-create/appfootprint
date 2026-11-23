"""Educational explanations for user storage; no cleanup recommendations.

A directory name is a hint, not proof of ownership or safe deletion.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageExplanation:
    title: str
    purpose: str
    contents: str
    caution: str
    category: str = "Unknown"
    documentation: str = ""


XDG_DOCS = "https://specifications.freedesktop.org/basedir-spec/latest/"
FLATPAK_DOCS = "https://docs.flatpak.org/en/latest/conventions.html"

EXPLANATIONS = {
    ".cache": StorageExplanation(
        "XDG cache", "Standard location for application caches.",
        "Downloaded or generated data used to speed up applications.",
        "Usually reproducible, but removing it can cause downloads, delays or loss of application-specific state. Inspect before changing anything.",
        "Cache / mixed applications", XDG_DOCS),
    ".config": StorageExplanation(
        "XDG configuration", "Standard location for per-user application settings.",
        "Preferences, accounts, application configuration and sometimes other state.",
        "Settings may be difficult to recreate. Do not assume files are disposable.",
        "Configuration / mixed applications", XDG_DOCS),
    ".local": StorageExplanation(
        "Local user data", "Contains XDG data and state, and may include user-installed programs.",
        "Application databases, user data, state, and executable files.",
        "May contain irreplaceable data. Different subdirectories have different purposes.",
        "Persistent data / mixed applications", XDG_DOCS),
    ".var": StorageExplanation(
        "Flatpak application storage", "Flatpak commonly keeps per-application sandbox data under ~/.var/app/.",
        "Application settings, caches, profiles and user files. Game launchers can store Minecraft worlds here.",
        "May contain irreplaceable saves or documents. Flatpak application data can remain after an uninstall.",
        "Mixed application data", FLATPAK_DOCS),
    ".mozilla": StorageExplanation(
        "Mozilla profiles", "Firefox and related Mozilla applications may use a historical profile location.",
        "Browser profiles, bookmarks, extensions and settings.",
        "Profiles can contain important personal data. A Firefox Flatpak may instead store its profile under ~/.var/app/.",
        "Application data / profiles"),
    ".vscode": StorageExplanation(
        "Visual Studio Code", "Common user-level location for VS Code extensions and related files.",
        "Extensions and support files; settings may be elsewhere.",
        "Removing extensions may require reinstalling them; inspect the actual contents.",
        "Development tools"),
    ".platformio": StorageExplanation(
        "PlatformIO", "Common PlatformIO development-tool storage.",
        "Downloaded platforms, toolchains, packages and configuration.",
        "Some data can be downloaded again, but do not treat the entire directory as a cache.",
        "Development tools"),
    ".rustup": StorageExplanation(
        "Rustup", "Rust toolchain manager storage.",
        "Installed Rust toolchains and components.",
        "Toolchains may be reinstallable, but inspect configured versions before changing them.",
        "Development tools"),
    ".cargo": StorageExplanation(
        "Cargo", "Rust package-manager user storage.",
        "Installed command-line tools, registry downloads, Git checkouts and configuration.",
        "Not everything is a cache; installed tools and settings may be needed.",
        "Development tools"),
    ".npm": StorageExplanation(
        "npm", "Node.js package-manager user storage.",
        "Download cache, logs and metadata.",
        "Review subdirectories separately; this does not describe project-local node_modules.",
        "Development cache / mixed"),
    ".gradle": StorageExplanation(
        "Gradle", "Gradle build-system user storage.",
        "Dependency caches, wrapper distributions and metadata.",
        "Some content is reproducible, but regeneration can be costly.",
        "Development cache / mixed"),
    ".m2": StorageExplanation(
        "Maven", "Maven's conventional per-user directory.",
        "Dependency repository, settings and potentially private artifacts.",
        "Local artifacts and credentials may not be recoverable.",
        "Development data / mixed"),
    ".dotnet": StorageExplanation(
        ".NET", "Common .NET SDK and tool storage.",
        "Tools, SDK support files and first-run state.",
        "Contents vary; do not infer safe cleanup from the directory name.",
        "Development tools"),
    ".gnupg": StorageExplanation(
        "GnuPG", "GnuPG key and trust storage.",
        "Private keys, public keys, trust databases and configuration.",
        "Critical: private keys may be impossible to recover. Never treat this as disposable.",
        "Sensitive credentials"),
    ".ssh": StorageExplanation(
        "OpenSSH", "SSH client configuration and identity storage.",
        "Private keys, known hosts and connection configuration.",
        "Critical: private keys and access configuration may be irreplaceable.",
        "Sensitive credentials"),
    ".pki": StorageExplanation(
        "Public-key infrastructure", "Often used for certificate and trust data.",
        "Certificates, databases and application-specific security state.",
        "May contain important security material; inspect carefully.",
        "Security data"),
    ".thunderbird": StorageExplanation(
        "Thunderbird", "Common Thunderbird profile location.",
        "Mail profiles, messages, settings and address books.",
        "May contain irreplaceable mail and personal data.",
        "Application data / profiles"),
}

UNKNOWN = StorageExplanation(
    "Unidentified hidden directory",
    "AppFootprint has no verified explanation for this directory name.",
    "Its contents and owner are unknown without further inspection.",
    "Unknown does not mean unnecessary. Inspect the directory before making changes.",
)


def explain_hidden_directory(path: str | Path) -> StorageExplanation:
    """Explain only a top-level hidden directory name, without reading its files."""
    return EXPLANATIONS.get(Path(path).name, UNKNOWN)
