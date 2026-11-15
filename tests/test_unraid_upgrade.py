import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "2026.1102.205049"
TARGET = "2026.1114.195738"
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.proxy.yml",
    "compose.unraid.yml",
    "compose.ingress.yml",
    "compose.voice-direct.yml",
)
MANAGED_FILES = (*COMPOSE_FILES, "Caddyfile", ".env.example", "UPSTREAM.json")
REPLACED_FILES = {"docker-compose.yml", "Caddyfile", ".env.example", "UPSTREAM.json"}
DATA_VOLUMES = (
    "edge-data", "edge-config", "postgres-data", "valkey-data", "nats-data",
    "meilisearch-data", "seaweedfs-data", "media-proxy-tmp",
)
LIVE_FILES = {
    "secrets/cloudflare-dns-token": b"private-test-dns-token",
    "secrets/cloudflare-tunnel-token": b"private-test-tunnel-token",
    "data/postgres-data/PG_VERSION": b"16\n",
    "data/seaweedfs-data/uploads.test": b"user upload",
    "data/traefik-acme/acme.json": b"certificate data",
    "caddy.d/sites/custom.caddy": b"local proxy override",
}

DOCKER = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if not args:
    sys.exit(90)
with Path(os.environ['FAKE_DOCKER_LOG']).open('a') as log:
    log.write(json.dumps(args) + '\\n')
project = Path(os.environ['FLUXER_PROJECT_DIR'])
if args == ['version', '--format', '{{.Server.Version}}']:
    print('29.0.0')
elif args[:2] == ['ps', '-a']:
    if 'com.docker.compose.project.config_files' in args[-1]:
        filenames = os.environ['FAKE_COMPOSE_FILES'].split(':')
        print('mockid|' + ','.join(str(project / name) for name in filenames))
    else:
        print(project)
elif args[0] == 'ps' or args[:2] == ['volume', 'ls']:
    pass
elif args[:2] == ['compose', 'version']:
    print('2.40.0')
elif args[0] != 'compose':
    sys.exit(91)
elif 'config' in args:
    if '--quiet' not in args:
        config = json.loads(Path(os.environ['FAKE_COMPOSE_CONFIG']).read_text())
        if '-f' in args and os.environ.get('FAKE_STAGE_VOLUME_DRIFT') == '1':
            config['volumes']['postgres-data']['driver_opts']['device'] = '/unexpected/postgres-data'
        print(json.dumps(config))
elif 'pull' in args:
    if os.environ.get('FAKE_PULL_FAIL') == '1':
        print('pull diagnostic includes private-test-tunnel-token', file=sys.stderr)
        sys.exit(1)
elif 'stop' in args:
    pass
elif 'up' in args:
    if os.environ.get('FAKE_HEALTH_FAIL') == '1' and '--wait' in args:
        print('service failed its health check', file=sys.stderr)
        sys.exit(1)
elif 'ps' in args:
    print('api: running (healthy)')
else:
    sys.exit(92)
'''


class UnraidUpgradeFixture:
    def setUp(self):
        workspace = tempfile.TemporaryDirectory(prefix="fluxer-upgrade-test-")
        self.addCleanup(workspace.cleanup)
        self.base = Path(workspace.name).resolve()
        self.plugin = self.base / "plugin"
        self.project = self.base / "appdata" / "fluxer"
        self.backups = self.project.with_name("fluxer-upgrades")
        self.project.mkdir(parents=True, mode=0o700)
        self.bundle = self.plugin / "bundle"
        self.bundle.mkdir(parents=True)
        shutil.copytree(ROOT / "unraid-plugin" / "scripts", self.plugin / "scripts")
        self.controller = self.plugin / "scripts" / "fluxerctl"

        self.original = {name: self.versioned_contents(name, SOURCE) for name in MANAGED_FILES}
        self.target = {name: self.versioned_contents(name, TARGET) for name in MANAGED_FILES}
        manifest_rows = [f"{SOURCE}\t{TARGET}"]
        for name in MANAGED_FILES:
            old, new = self.original[name], self.target[name]
            (self.project / name).write_bytes(old)
            (self.bundle / name).write_bytes(new)
            manifest_rows.append(f"{name}\t{hashlib.sha256(old).hexdigest()}\t{hashlib.sha256(new).hexdigest()}")
        (self.plugin / "upgrade.tsv").write_text("\n".join(manifest_rows) + "\n")

        self.preserved = {
            **LIVE_FILES,
            ".env": (
                f"COMPOSE_FILE={':'.join(COMPOSE_FILES)}\n"
                f"FLUXER_DATA_DIR='{self.project / 'data'}'\n"
                "FLUXER_DOMAIN='chat.example.com'\n"
                "FLUXER_NAS_IP='192.168.30.10'\n"
                "POSTGRES_PASSWORD='private-test-database-key'\n"
                "FLUXER_LIVEKIT_USE_EXTERNAL_IP=false\n"
                "FLUXER_LIVEKIT_NODE_IP=203.0.113.1\n"
            ).encode(),
        }
        for name, contents in self.preserved.items():
            path = self.project / name
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.write_bytes(contents)
            path.chmod(0o600)
        for volume in DATA_VOLUMES:
            (self.project / "data" / volume).mkdir(exist_ok=True)
        (self.project / ".unraid-autostart").touch()
        (self.project / "start.sh").write_text("#!/bin/bash\ndocker compose up -d\n")

        fakebin = self.base / "bin"
        fakebin.mkdir()
        self.write_executable(fakebin / "docker", DOCKER)
        self.write_executable(fakebin / "ip", "#!/bin/sh\necho '2: br0 inet 192.168.30.10/24 scope global br0'\n")
        real_cp = shutil.which("cp")
        self.assertIsNotNone(real_cp)
        self.write_executable(
            fakebin / "cp",
            '''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
destination = Path(sys.argv[-1])
if os.environ.get('FAKE_BACKUP_FAIL') == '1' and destination.name == 'project':
    sys.exit(1)
cp = os.environ['REAL_CP']
os.execv(cp, [cp, *sys.argv[1:]])
''',
        )
        if shutil.which("flock") is None:
            self.write_executable(
                fakebin / "flock",
                '''#!/usr/bin/env python3
import fcntl
import os
import subprocess
import sys

args = sys.argv[1:]
if args and args[0] == '-n':
    args.pop(0)
target = args.pop(0)
descriptor = int(target) if target.isdigit() else os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(1)
if args:
    sys.exit(subprocess.run(args).returncode)
''',
            )
        self.config_file = self.base / "config.json"
        self.docker_log = self.base / "docker.log"
        self.env = {
            **os.environ,
            "PATH": str(fakebin) + os.pathsep + os.environ["PATH"],
            "FLUXER_PLUGIN_DIR": str(self.plugin),
            "FLUXER_PROJECT_DIR": str(self.project),
            "FLUXER_LOCK_FILE": str(self.base / "fluxer.lock"),
            "FAKE_COMPOSE_FILES": ':'.join(COMPOSE_FILES),
            "FAKE_COMPOSE_CONFIG": str(self.config_file),
            "FAKE_DOCKER_LOG": str(self.docker_log),
            "REAL_CP": real_cp,
        }
        self.config_file.write_text(json.dumps(self.compose_config()))

    @staticmethod
    def write_executable(path, contents):
        path.write_text(contents)
        path.chmod(0o755)

    @staticmethod
    def versioned_contents(name, version):
        if name == "UPSTREAM.json":
            return (json.dumps({"release": version}) + "\n").encode()
        return f"# {name} {version if name in REPLACED_FILES else 'unchanged'}\n".encode()

    def compose_config(self):
        return {
            "name": "fluxer",
            "services": {"api": {"image": "fluxer/mock", "environment": {}}},
            "volumes": {
                key: {
                    "name": f"fluxer_{key}",
                    "driver": "local",
                    "driver_opts": {
                        "type": "none", "o": "bind", "device": str(self.project / "data" / key),
                    },
                }
                for key in DATA_VOLUMES
            },
            "networks": {"default": {"name": "fluxer_default"}},
        }

    def call(self, *args):
        result = subprocess.run(
            ["bash", str(self.controller), *args],
            env=self.env, text=True, capture_output=True, timeout=30,
        )
        for secret in ("private-test-dns-token", "private-test-tunnel-token", "private-test-database-key"):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return result

    def info(self):
        status = self.call("upgrade_info")
        self.assertEqual(status.returncode, 0, status.stderr)
        return json.loads(status.stdout)

    def docker_commands(self):
        if not self.docker_log.exists():
            return []
        return [json.loads(line) for line in self.docker_log.read_text().splitlines()]

    def upgrade_commands(self):
        steps = {"config", "pull", "stop", "up"}
        return [argument for command in self.docker_commands() for argument in command if argument in steps]

    def assert_files(self, directory, expected):
        for name, contents in expected.items():
            self.assertEqual((directory / name).read_bytes(), contents, f"{directory.name}/{name}")

    def backup(self):
        projects = list(self.backups.glob("backup-*/project"))
        self.assertEqual(len(projects), 1, projects)
        return projects[0]


class UnraidUpgradeTests(UnraidUpgradeFixture, unittest.TestCase):
    def test_upgrade_pulls_before_downtime_and_preserves_project_data(self):
        before = self.info()
        self.assertEqual((before["installed"], before["target"]), (SOURCE, TARGET))
        self.assertTrue(before["available"], before)

        request_id = "60a1c1e6db2445d593926980b5228386"
        result = self.call("upgrade", TARGET, request_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = self.upgrade_commands()
        self.assertIn("config", observed)
        self.assertLess(observed.index("config"), observed.index("pull"))
        self.assertLess(observed.index("pull"), observed.index("stop"))
        self.assertLess(observed.index("stop"), observed.index("up"))
        pull = next(command for command in self.docker_commands() if "pull" in command)
        self.assertEqual(pull[pull.index("--policy") + 1], "missing")
        up = next(command for command in self.docker_commands() if "up" in command)
        self.assertEqual(up[up.index("--pull") + 1], "never")
        self.assertIn("--wait", up)

        self.assert_files(self.project, {**self.target, **self.preserved})
        self.assertTrue((self.project / ".unraid-autostart").is_file())
        backup = self.backup()
        self.assert_files(backup, {**self.original, **self.preserved})
        self.assertEqual(stat.S_IMODE(self.backups.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((backup / ".env").stat().st_mode), 0o600)
        self.assertFalse((self.backups / "pending").exists())
        after = self.info()
        self.assertEqual(after["installed"], TARGET)
        self.assertEqual(after["state"], "completed")
        self.assertEqual(after["request_id"], request_id)
        self.assertEqual(Path(after["backup"]), backup)
        self.assertFalse(after["available"])

    def test_edited_compose_or_stale_target_never_stops_the_stack(self):
        candidate = self.project / "docker-compose.yml"
        custom = candidate.read_bytes() + b"# local edits\n"
        candidate.write_bytes(custom)
        status = self.info()
        self.assertFalse(status["available"])
        self.assertIn("docker-compose.yml", status["message"])
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(candidate.read_bytes(), custom)

        candidate.write_bytes(self.original[candidate.name])
        result = self.call("upgrade", SOURCE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bundled release changed", result.stderr)
        self.assert_files(self.project, self.original)
        self.assertEqual(self.upgrade_commands(), [])

    def test_failed_pull_leaves_running_project_intact_and_allows_retry(self):
        self.env["FAKE_PULL_FAIL"] = "1"
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pull", self.upgrade_commands())
        self.assertNotIn("stop", self.upgrade_commands())
        self.assertNotIn("up", self.upgrade_commands())
        self.assert_files(self.project, {**self.original, **self.preserved})
        self.assertFalse((self.backups / "pending").exists())
        after = self.info()
        self.assertEqual(after["installed"], SOURCE)
        self.assertEqual(after["state"], "failed")
        self.assertTrue(after["available"], after)

    def test_staged_volume_drift_fails_before_pull_or_stop(self):
        self.env["FAKE_STAGE_VOLUME_DRIFT"] = "1"
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported storage settings", result.stderr)
        self.assertEqual(self.upgrade_commands(), ["config", "config"])
        self.assert_files(self.project, {**self.original, **self.preserved})

    def test_external_data_path_requires_manual_upgrade(self):
        env = self.project / ".env"
        external = self.base / "external-data"
        external.mkdir()
        env.write_bytes(env.read_bytes().replace(os.fsencode(self.project / "data"), os.fsencode(external)))
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("project data folder", result.stderr)
        self.assert_files(self.project, self.original)
        self.assertNotIn("pull", self.upgrade_commands())
        self.assertNotIn("stop", self.upgrade_commands())

    def test_external_symlink_cannot_make_the_backup_incomplete(self):
        external = self.base / "external-tunnel-token"
        external.write_bytes(LIVE_FILES["secrets/cloudflare-tunnel-token"])
        token = self.project / "secrets" / "cloudflare-tunnel-token"
        token.unlink()
        token.symlink_to(external)
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic link", result.stderr)
        self.assertEqual(self.upgrade_commands(), [])
        self.assertTrue(token.is_symlink())
        self.assertEqual(external.read_bytes(), LIVE_FILES["secrets/cloudflare-tunnel-token"])

    def test_existing_container_custom_compose_list_requires_manual_upgrade(self):
        self.env["FAKE_COMPOSE_FILES"] += ":compose.custom.yml"
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("pull", self.upgrade_commands())
        self.assertNotIn("stop", self.upgrade_commands())
        self.assert_files(self.project, {**self.original, **self.preserved})

    def test_failed_backup_allows_manual_start_of_original_release(self):
        self.env["FAKE_BACKUP_FAIL"] = "1"
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stop", self.upgrade_commands())
        self.assertNotIn("up", self.upgrade_commands())
        self.assert_files(self.project, {**self.original, **self.preserved})
        self.assertFalse((self.backups / "pending").exists())
        self.assertEqual(self.info()["installed"], SOURCE)
        start = self.call("start")
        self.assertEqual(start.returncode, 0, start.stderr)
        self.assertIn("up", self.upgrade_commands())

    def test_failed_target_health_keeps_the_backup_and_blocks_start(self):
        self.env["FAKE_HEALTH_FAIL"] = "1"
        result = self.call("upgrade", TARGET)
        self.assertNotEqual(result.returncode, 0)
        self.assert_files(self.backup(), {**self.original, **self.preserved})
        self.assertEqual((self.project / "UPSTREAM.json").read_bytes(), self.original["UPSTREAM.json"])
        self.assertTrue((self.backups / "pending").exists())
        status = self.info()
        self.assertFalse(status["available"])
        self.assertEqual(status["phase"], "recovery")
        self.assertEqual(self.upgrade_commands()[-3:], ["stop", "up", "stop"])
        self.assertNotEqual(self.call("start").returncode, 0)
        self.call("autostart")
        self.assertEqual(self.upgrade_commands().count("up"), 1)

    def test_stale_running_status_with_pending_marker_requires_recovery(self):
        self.env["FAKE_HEALTH_FAIL"] = "1"
        self.assertNotEqual(self.call("upgrade", TARGET).returncode, 0)
        status_file = self.backups / "status.json"
        interrupted = json.loads(status_file.read_text())
        interrupted["state"] = "running"
        status_file.write_text(json.dumps(interrupted))

        status = self.info()
        self.assertEqual(status["state"], "interrupted")
        self.assertFalse(status["available"])
        self.assertNotEqual(self.call("start").returncode, 0)


if __name__ == "__main__":
    unittest.main()
