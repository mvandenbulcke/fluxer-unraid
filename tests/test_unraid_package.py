import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools/build-unraid-plugin.py"
PREFIX = PurePosixPath("usr/local/emhttp/plugins/fluxer")
VERSION = "2026.11.03.9"
REPOSITORY = "example-owner/fluxer-unraid"
ARCHIVE_NAME = f"fluxer-unraid-{VERSION}.tar.gz"
FIXTURE_FILES = {
    ".env.example": b"FLUXER_DOMAIN=chat.example.com\n",
    "docker-compose.yml": b"services: {}\n",
    "docker-compose.proxy.yml": b"services: {}\n",
    "compose.unraid.yml": b"services: {}\n",
    "compose.ingress.yml": b"services: {}\n",
    "compose.voice-direct.yml": b"services: {}\n",
    "Caddyfile": b":8080 { respond OK }\n",
    "setup.sh": b"#!/bin/bash\nexit 0\n",
    "set-tokens.sh": b"#!/bin/bash\nexit 0\n",
    "start.sh": b"#!/bin/bash\nexit 0\n",
    "README.md": b"Fluxer package fixture.\n",
    "CONTRIBUTING.md": b"# Contributing\n\nRun the package tests before a change.\n",
    "PUBLISHING.md": b"# Publishing\n\nTest the release before submission.\n",
    "CHANGELOG.md": (
        b"# Changes\n\n"
        b"## 2026.11.03.10\n\n- Future release marker.\n\n"
        b"## 2026.11.03.9\n\n"
        b"- Preserve application keys during managed upgrades.\n"
        b"- Check outbound tunnel access before the public test.\n\n"
        b"## 2026.11.03.8\n\n- Previous release marker.\n"
    ),
    "docs/README.md": b"# Documentation\n\nRead the installation guide.\n",
    "docs/installation.md": b"# Installation\n\nInstall the plugin from Apps.\n",
    "docs/manual-deployment.md": b"# Manual deployment\n\nUse the saved instance settings.\n",
    "docs/troubleshooting.md": b"# Troubleshooting\n\nRead the container logs.\n",
    "LICENSE": b"AGPL-3.0-only\n",
    "UPSTREAM.json": b'{"release":"fixture"}\n',
    "voice/voice.compose.yml": b"services: {}\n",
    "unraid-plugin/Fluxer.page": b'Menu="Settings"\nTitle="Fluxer"\n',
    "unraid-plugin/include/control.php": b"<?php\nexit;\n",
    "unraid-plugin/scripts/fluxerctl": b"#!/bin/bash\nexit 0\n",
    "unraid-plugin/event/docker_started": b"#!/bin/bash\nexit 0\n",
    "unraid-plugin/images/fluxer.svg": b'<svg xmlns="http://www.w3.org/2000/svg"/>\n',
}


class UnraidPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fluxer-package-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.output = self.base / "output"
        for relative, contents in FIXTURE_FILES.items():
            self.write_source(relative, contents)

    def write_source(self, relative, contents):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def build(self, output=None):
        return subprocess.run(
            [
                sys.executable, str(BUILDER),
                "--source", str(self.source),
                "--output-dir", str(output or self.output),
                "--repository", REPOSITORY,
                "--version", VERSION,
            ],
            text=True, capture_output=True, timeout=20,
        )

    def build_successfully(self, output=None):
        result = self.build(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        return output or self.output

    def test_manifest_and_checksums_identify_the_actual_release_artifacts(self):
        self.build_successfully()
        self.assertEqual(
            {path.name for path in self.output.iterdir()},
            {ARCHIVE_NAME, "fluxer.plg", "SHA256SUMS"},
        )
        archive_path = self.output / ARCHIVE_NAME
        manifest_path = self.output / "fluxer.plg"
        manifest = ET.parse(manifest_path).getroot()
        repository_url = f"https://github.com/{REPOSITORY}"
        self.assertEqual(manifest.tag, "PLUGIN")
        self.assertEqual(manifest.attrib["name"], "fluxer")
        self.assertEqual(manifest.attrib["version"], VERSION)
        self.assertEqual(manifest.attrib["min"], "7.0.0")
        self.assertEqual(manifest.attrib["launch"], "Settings/Fluxer")
        self.assertEqual(
            manifest.attrib["pluginURL"],
            f"{repository_url}/releases/latest/download/fluxer.plg",
        )
        payloads = manifest.findall("./FILE[@Name]")
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(
            payload.attrib["Name"],
            f"/boot/config/plugins/fluxer/{ARCHIVE_NAME}",
        )
        self.assertEqual(
            payload.findtext("URL"),
            f"{repository_url}/releases/download/v{VERSION}/{ARCHIVE_NAME}",
        )
        self.assertEqual(
            payload.findtext("SHA256"),
            hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        )
        checksums = (self.output / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(checksums), 2)
        for line, path in zip(checksums, (archive_path, manifest_path)):
            digest, name = line.split("  ", 1)
            self.assertEqual(name, path.name)
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_archive_ignores_runtime_secrets_and_unlisted_source_files(self):
        marker = b"PRIVATE-RUNTIME-DATA-MUST-NOT-ENTER-THE-PUBLIC-PACKAGE"
        for relative in (
            ".env", "secrets/cloudflare-dns-token", "secrets/cloudflare-tunnel-token",
            "data/postgres-data/database", "backups/settings.env", "dist/old-release.txt",
            "certs/server.key", "ca/private.key", "caddy.d/sites/local.caddy",
            "voice/voice.env", "compose.private.yml", "unlisted-notes.md",
        ):
            self.write_source(relative, marker)
        self.build_successfully()
        archive_path = self.output / ARCHIVE_NAME
        with tarfile.open(archive_path, "r:gz") as archive:
            actual_files = {member.name for member in archive.getmembers() if member.isfile()}
            expected_files = {
                str(PREFIX / (relative.removeprefix("unraid-plugin/")
                              if relative.startswith("unraid-plugin/") else "bundle/" + relative))
                for relative in FIXTURE_FILES
            }
            self.assertEqual(actual_files, expected_files)
            for member in archive.getmembers():
                name = PurePosixPath(member.name)
                self.assertFalse(name.is_absolute(), member.name)
                self.assertNotIn("..", name.parts)
                self.assertTrue(name == PREFIX or PREFIX in name.parents, member.name)
                self.assertTrue(member.isfile() or member.isdir(), member.name)
        self.assertNotIn(marker, gzip.decompress(archive_path.read_bytes()))

    def test_manifest_uses_only_the_selected_release_notes(self):
        self.build_successfully()
        manifest = ET.parse(self.output / "fluxer.plg").getroot()
        changes = manifest.findtext("CHANGES")
        self.assertIsNotNone(changes)
        self.assertIn("Preserve application keys during managed upgrades.", changes)
        self.assertIn("Check outbound tunnel access before the public test.", changes)
        self.assertNotIn("Future release marker.", changes)
        self.assertNotIn("Previous release marker.", changes)
        self.assertNotIn("Install the deployment files and a Settings page.", changes)

    def test_missing_release_notes_prevent_release_artifacts(self):
        self.write_source("CHANGELOG.md", b"# Changes\n\n## 2026.11.03.8\n\n- Previous release marker.\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(VERSION, result.stderr)
        self.assertFalse(self.output.exists() and any(self.output.iterdir()))

    def test_archive_installs_executable_scripts_and_readable_configuration(self):
        self.build_successfully()
        with tarfile.open(self.output / ARCHIVE_NAME, "r:gz") as archive:
            for relative in (
                "scripts/fluxerctl", "event/docker_started", "bundle/setup.sh",
                "bundle/set-tokens.sh", "bundle/start.sh",
            ):
                with self.subTest(relative=relative):
                    self.assertEqual(archive.getmember(str(PREFIX / relative)).mode, 0o755)
            for relative in (
                "Fluxer.page", "include/control.php", "images/fluxer.svg",
                "bundle/compose.ingress.yml", "bundle/.env.example",
            ):
                with self.subTest(relative=relative):
                    self.assertEqual(archive.getmember(str(PREFIX / relative)).mode, 0o644)
            for member in archive.getmembers():
                self.assertEqual((member.uid, member.gid), (0, 0))
                self.assertEqual(member.mode & 0o6000, 0)

    def test_archive_bytes_do_not_depend_on_output_folder_or_source_metadata(self):
        first = self.build_successfully()
        for relative in FIXTURE_FILES:
            path = self.source / relative
            path.chmod(0o700)
            os.utime(path, (1_000_000, 2_000_000))
        second = self.build_successfully(self.base / "second-output")
        for name in (ARCHIVE_NAME, "fluxer.plg", "SHA256SUMS"):
            with self.subTest(name=name):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_source_symlinks_cannot_import_files_into_the_public_archive(self):
        outside = self.base / "private-file"
        outside.write_bytes(b"private content outside the package source")
        for index, relative in enumerate((
            "setup.sh", "unraid-plugin/scripts/fluxerctl", "voice/voice.compose.yml",
        )):
            with self.subTest(relative=relative):
                path = self.source / relative
                original = path.read_bytes()
                path.unlink()
                path.symlink_to(outside)
                output = self.base / f"rejected-symlink-{index}"
                try:
                    result = self.build(output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("symbolic link", result.stderr)
                    self.assertFalse(output.exists())
                finally:
                    path.unlink()
                    path.write_bytes(original)

    def test_runtime_paths_inside_the_plugin_fail_the_build(self):
        for index, relative in enumerate((
            ".env", "secrets/token.txt", "data/database.txt", "backups/keys.txt", "dist/old.txt",
        )):
            with self.subTest(relative=relative):
                path = self.write_source("unraid-plugin/" + relative, b"private runtime content")
                output = self.base / f"rejected-runtime-{index}"
                try:
                    result = self.build(output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("reserved path", result.stderr)
                    self.assertFalse(output.exists())
                finally:
                    path.unlink()
                    while path.parent != self.source / "unraid-plugin":
                        path = path.parent
                        path.rmdir()

    def test_generated_installer_and_remove_scripts_have_valid_bash_syntax(self):
        self.build_successfully()
        manifest = ET.parse(self.output / "fluxer.plg").getroot()
        scripts = manifest.findall("./FILE[@Run='/bin/bash']/INLINE")
        self.assertEqual(len(scripts), 3)
        for index, script in enumerate(scripts):
            with self.subTest(script=index):
                result = subprocess.run(
                    ["bash", "-n"], input=script.text, text=True,
                    capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
