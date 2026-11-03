#!/usr/bin/env python3
"""Build a versioned Unraid plugin without instance data or credentials."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import re
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


DEFAULT_REPOSITORY = "https://github.com/mvandenbulcke/fluxer-unraid"
DEFAULT_VERSION = "2026.11.03.1"
PLUGIN_PREFIX = PurePosixPath("usr/local/emhttp/plugins/fluxer")
REQUIRED_BUNDLE_FILES = (
    ".env.example",
    "docker-compose.yml",
    "docker-compose.proxy.yml",
    "compose.unraid.yml",
    "compose.ingress.yml",
    "compose.voice-vpn.yml",
    "Caddyfile",
    "setup.sh",
    "set-tokens.sh",
    "start.sh",
    "README.md",
    "LICENSE",
    "UPSTREAM.json",
)
OPTIONAL_BUNDLE_FILES = (
    "voice/Caddyfile.voice",
    "voice/voice-http.compose.yml",
    "voice/voice.compose.yml",
    "voice/voice-edge.compose.yml",
    "voice/sites.d/voice.caddy.example",
    "voice/voice.env.example",
    "voice/edge.env.example",
)
BUNDLE_DIRECTORIES = ("ca", "certs", "caddy.d", "caddy.d/sites")
PLUGIN_SUFFIXES = {
    ".cfg", ".css", ".html", ".js", ".json", ".md", ".page", ".php",
    ".png", ".sh", ".svg", ".txt",
}
FORBIDDEN_COMPONENTS = {".git", ".env", "data", "secrets", "backups", "dist"}


def fail(message: str) -> None:
    raise ValueError(message)


def repository_slug(value: str) -> str:
    value = value.removeprefix("https://github.com/").removesuffix("/")
    value = value.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value):
        fail("Use a public GitHub URL or owner/repository for --repository.")
    return value


def release_version(value: str) -> str:
    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.[1-9]\d*", value):
        fail("Use YYYY.MM.DD.N for --version, with N greater than zero.")
    year, month, day, _ = map(int, value.split("."))
    try:
        dt.date(year, month, day)
    except ValueError as error:
        fail(f"Invalid release date: {error}")
    return value


def source_file(source: Path, relative: str) -> Path:
    path = source / relative
    current = source
    for component in PurePosixPath(relative).parts:
        current /= component
        if current.is_symlink():
            fail(f"The package cannot contain a symbolic link: {relative}")
    if not path.is_file():
        fail(f"Required package file is missing: {relative}")
    return path


def package_inventory(source: Path) -> dict[PurePosixPath, Path | None]:
    inventory: dict[PurePosixPath, Path | None] = {PLUGIN_PREFIX: None}

    def add(relative: PurePosixPath, path: Path | None) -> None:
        if relative in inventory and inventory[relative] != path:
            fail(f"Duplicate package path: {relative}")
        inventory[relative] = path
        for parent in relative.parents:
            if parent == PLUGIN_PREFIX or PLUGIN_PREFIX in parent.parents:
                inventory.setdefault(parent, None)

    plugin_source = source / "unraid-plugin"
    source_file(source, "unraid-plugin/Fluxer.page")
    for path in sorted(plugin_source.rglob("*")):
        relative = PurePosixPath(path.relative_to(plugin_source).as_posix())
        if path.is_symlink():
            fail(f"The plugin source cannot contain a symbolic link: {relative}")
        if path.name == ".DS_Store":
            continue
        if (
            any(part in FORBIDDEN_COMPONENTS for part in relative.parts)
            or any(part.startswith(".") for part in relative.parts)
            or relative.parts[0] == "bundle"
        ):
            fail(f"The plugin source contains a reserved path: {relative}")
        if path.is_dir():
            add(PLUGIN_PREFIX / relative, None)
            continue
        if not path.is_file():
            fail(f"Unsupported plugin source file: {relative}")
        executable_script = relative.parts[0] in {"scripts", "event"} and path.read_bytes().startswith(b"#!")
        if path.suffix not in PLUGIN_SUFFIXES and not executable_script:
            fail(f"Unsupported plugin source file type: {relative}")
        add(PLUGIN_PREFIX / relative, path)

    for relative in REQUIRED_BUNDLE_FILES:
        add(PLUGIN_PREFIX / "bundle" / relative, source_file(source, relative))
    for relative in OPTIONAL_BUNDLE_FILES:
        if (source / relative).exists() or (source / relative).is_symlink():
            add(PLUGIN_PREFIX / "bundle" / relative, source_file(source, relative))
    for relative in BUNDLE_DIRECTORIES:
        add(PLUGIN_PREFIX / "bundle" / relative, None)
    return inventory


def write_archive(target: Path, inventory: dict[PurePosixPath, Path | None]) -> None:
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for relative, source in sorted(inventory.items()):
                        entry = tarfile.TarInfo(str(relative))
                        entry.uid = entry.gid = 0
                        entry.uname = entry.gname = "root"
                        entry.mtime = 0
                        if source is None:
                            entry.type = tarfile.DIRTYPE
                            entry.mode = 0o755
                            archive.addfile(entry)
                            continue
                        contents = source.read_bytes()
                        executable = source.suffix == ".sh" or any(
                            component in {"scripts", "event"} for component in relative.parts
                        )
                        entry.mode = 0o755 if executable else 0o644
                        entry.size = len(contents)
                        archive.addfile(entry, io.BytesIO(contents))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_manifest(repository: str, version: str, archive_name: str, digest: str) -> bytes:
    repository_url = f"https://github.com/{repository}"
    cache_path = f"/boot/config/plugins/fluxer/{archive_name}"
    plugin_path = f"/{PLUGIN_PREFIX}"
    manifest = ET.Element("PLUGIN", {
        "name": "fluxer",
        "author": repository.split("/", 1)[0],
        "version": version,
        "launch": "Settings/Fluxer",
        "pluginURL": f"{repository_url}/releases/latest/download/fluxer.plg",
        "min": "7.0.0",
        "support": f"{repository_url}/issues",
        "project": repository_url,
        "icon": "comments",
    })
    ET.SubElement(manifest, "CHANGES").text = (
        f"### {version}\n"
        "- Unofficial Fluxer installer for Unraid 7.\n"
        "- Install the deployment files and a Settings page.\n"
        "- Keep existing containers and application data during plugin removal.\n"
    )
    preflight = ET.SubElement(manifest, "FILE", {"Run": "/bin/bash"})
    ET.SubElement(preflight, "INLINE").text = """
set -euo pipefail
if (( EUID != 0 )); then
  printf '%s\\n' 'Install the Fluxer plugin as root.' >&2
  exit 1
fi
if [[ ! -r /etc/unraid-version ]]; then
  printf '%s\\n' 'The Fluxer plugin requires Unraid 7.' >&2
  exit 1
fi
source /etc/unraid-version
if [[ "${version:-}" != 7.* ]]; then
  printf '%s\\n' 'The Fluxer plugin supports Unraid 7 only.' >&2
  exit 1
fi
install -d -m 0755 /boot/config/plugins/fluxer
""".strip() + "\n"
    payload = ET.SubElement(manifest, "FILE", {"Name": cache_path})
    ET.SubElement(payload, "URL").text = (
        f"{repository_url}/releases/download/v{version}/{archive_name}"
    )
    ET.SubElement(payload, "SHA256").text = digest
    install = ET.SubElement(manifest, "FILE", {"Run": "/bin/bash"})
    ET.SubElement(install, "INLINE").text = f"""
set -euo pipefail
umask 022
archive='{cache_path}'
prefix='{PLUGIN_PREFIX}'
members=$(tar -tzf "$archive")
while IFS= read -r member; do
  case "$member" in
    "$prefix"|"$prefix/"|"$prefix/"*) ;;
    *) printf '%s\\n' 'The Fluxer package contains an unexpected path.' >&2; exit 1 ;;
  esac
  case "/$member/" in
    *"/../"*|*"/./"*) printf '%s\\n' 'The Fluxer package contains an invalid path.' >&2; exit 1 ;;
  esac
done <<< "$members"
install -d -m 0755 '{plugin_path}'
tar -xzf "$archive" -C / --no-same-owner --no-same-permissions "$prefix"
printf '%s\\n' 'Fluxer settings are available under Settings > Fluxer.'
printf '%s\\n' 'Use the Settings page to configure and start the containers.'
""".strip() + "\n"
    remove = ET.SubElement(manifest, "FILE", {"Run": "/bin/bash", "Method": "remove"})
    ET.SubElement(remove, "INLINE").text = f"""
set -euo pipefail
if (( EUID != 0 )); then
  printf '%s\\n' 'Remove the Fluxer plugin as root.' >&2
  exit 1
fi
plugin_path='{plugin_path}'
if [[ -d "$plugin_path" && ! -L "$plugin_path" ]]; then
  find "$plugin_path" -xdev -depth -delete
fi
printf '%s\\n' 'Removed the Fluxer settings plugin.'
printf '%s\\n' 'Existing containers, settings, secrets, and application data remain in place.'
""".strip() + "\n"
    ET.indent(manifest, space="  ")
    return ET.tostring(manifest, encoding="utf-8", xml_declaration=True) + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    arguments = parser.parse_args()
    repository = repository_slug(arguments.repository)
    version = release_version(arguments.version)
    source = arguments.source.resolve()
    output = (arguments.output_dir or source / "dist").resolve()
    inventory = package_inventory(source)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"fluxer-unraid-{version}.tar.gz"
    write_archive(archive, inventory)
    manifest = output / "fluxer.plg"
    manifest.write_bytes(build_manifest(repository, version, archive.name, sha256(archive)))
    ET.parse(manifest)
    checksums = output / "SHA256SUMS"
    checksums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in (archive, manifest)),
        encoding="utf-8",
    )
    print(f"Built {archive}")
    print(f"Built {manifest}")
    print(f"Built {checksums}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        sys.exit(1)
