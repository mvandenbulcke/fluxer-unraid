import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "unraid-plugin/scripts/fluxerctl"


class UnraidControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fluxer-plugin-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.plugin = self.base / "plugin"
        self.project = self.base / "appdata/fluxer"
        bundle = self.plugin / "bundle"
        bundle.mkdir(parents=True)
        for name in ("setup.sh", "start.sh", ".env.example"):
            shutil.copy2(ROOT / name, bundle / name)
        fakebin = self.base / "bin"
        fakebin.mkdir()
        docker = fakebin / "docker"
        docker.write_text("""#!/bin/bash
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  'compose version --short') printf '%s\\n' "${FAKE_COMPOSE_VERSION:-2.40.0}" ;;
  'compose version') echo 'Docker Compose version v2.40.0' ;;
  'version --format '*) echo '29.0.0' ;;
  'ps -a '*) printf '%s' "${FAKE_PROJECT_OWNER:-}" ;;
  'compose ps '*) echo 'api: running (healthy)' ;;
  'compose up -d --force-recreate traefik cloudflared') exit "${FAKE_RECREATE_EXIT:-0}" ;;
esac
""")
        docker.chmod(0o755)
        tailscale = fakebin / "tailscale"
        tailscale.write_text("#!/bin/bash\nprintf '%s\\n' \"${FAKE_VPN_IP:-100.101.102.103}\"\n")
        tailscale.chmod(0o755)
        if shutil.which("flock") is None:
            flock = fakebin / "flock"
            flock.write_text("""#!/usr/bin/env python3
import fcntl, os, subprocess, sys
args = sys.argv[1:]
if args and args[0] == '-n': args.pop(0)
target = args.pop(0)
fd = int(target) if target.isdigit() else os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError: sys.exit(1)
if args: sys.exit(subprocess.run(args).returncode)
""")
            flock.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            PATH=str(fakebin) + os.pathsep + self.env["PATH"],
            FLUXER_PLUGIN_DIR=str(self.plugin),
            FLUXER_PROJECT_DIR=str(self.project),
            FLUXER_LOCK_FILE=str(self.base / "fluxer.lock"),
            FAKE_DOCKER_LOG=str(self.base / "docker.log"),
        )

    def call(self, *args):
        return subprocess.run(
            ["bash", str(CONTROLLER), *args],
            env=self.env, text=True, capture_output=True, timeout=20,
        )

    def prepare(self):
        result = self.call("prepare", "chat.example.com", "admin@example.com", "100.101.102.103")
        self.assertEqual(result.returncode, 0, result.stderr)

    def tokens(self):
        for name in ("cloudflare-dns-token", "cloudflare-tunnel-token"):
            (self.project / "secrets" / name).write_text("unused-test-token")

    def docker_log(self):
        path = self.base / "docker.log"
        return path.read_text() if path.exists() else ""

    def test_prepare_preserves_existing_keys(self):
        self.prepare()
        original = (self.project / ".env").read_bytes()
        self.assertNotEqual(self.call("prepare", "other.example.com", "admin@example.com", "100.101.102.103").returncode, 0)
        self.assertEqual((self.project / ".env").read_bytes(), original)
        self.assertEqual((self.project / ".env").stat().st_mode & 0o777, 0o600)

    def test_start_rejects_a_different_vpn_address(self):
        self.prepare()
        self.tokens()
        self.env["FAKE_VPN_IP"] = "100.101.102.104"
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertNotIn("compose up", self.docker_log())

    def test_start_rejects_old_compose(self):
        self.prepare()
        self.tokens()
        self.env["FAKE_COMPOSE_VERSION"] = "2.24.3"
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertNotIn("compose up", self.docker_log())

    def test_start_rejects_a_foreign_fluxer_project(self):
        self.prepare()
        self.tokens()
        self.env["FAKE_PROJECT_OWNER"] = "/mnt/user/appdata/some-other-install\n"
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertNotIn("compose up", self.docker_log())

    def test_missing_tokens_prevent_start(self):
        self.prepare()
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertNotIn("compose up", self.docker_log())

    def test_stop_preserves_settings_and_disables_autostart(self):
        self.prepare()
        self.tokens()
        original = (self.project / ".env").read_bytes()
        self.assertEqual(self.call("start").returncode, 0)
        self.assertTrue((self.project / ".unraid-autostart").exists())
        self.assertEqual(self.call("stop").returncode, 0)
        self.assertFalse((self.project / ".unraid-autostart").exists())
        self.assertEqual((self.project / ".env").read_bytes(), original)
        self.assertTrue((self.project / "data/postgres-data").is_dir())
        self.assertIn("compose stop", self.docker_log())
        self.assertNotIn("compose down", self.docker_log())

    def test_status_does_not_return_application_secrets(self):
        self.prepare()
        status = self.call("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("api: running", status.stdout)
        for line in (self.project / ".env").read_text().splitlines():
            key, value = line.split("=", 1)
            value = value.strip("'")
            if "SECRET" in key or "TOKEN" in key or "PASSWORD" in key:
                self.assertNotIn(value, status.stdout)

    def test_token_change_recreates_only_proxy_services(self):
        self.prepare()
        self.tokens()
        marker = self.project / ".cloudflare-tokens-changed"
        marker.touch()
        self.assertEqual(self.call("start").returncode, 0)
        self.assertIn("compose up -d --force-recreate traefik cloudflared", self.docker_log())
        self.assertFalse(marker.exists())

    def test_failed_token_apply_retains_retry_marker(self):
        self.prepare()
        self.tokens()
        marker = self.project / ".cloudflare-tokens-changed"
        marker.touch()
        self.env["FAKE_RECREATE_EXIT"] = "1"
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
