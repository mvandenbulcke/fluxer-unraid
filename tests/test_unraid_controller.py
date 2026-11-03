import base64
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "unraid-plugin/scripts/fluxerctl"
LEGACY_INGRESS = gzip.decompress(base64.b64decode(
    b"H4sIAAAAAAAC/7VWbW/jNgz+3l9hBPt4VpKmd8UMBEPWJkDQNB3aFBswDIZiMYkWWRIkOS833H8fZTu207SXorsh"
    b"gGNRFEmRDx/agtnwBGx0EQTOUFjwtX8NAp7SJUSVbNMj16R7nW8ZsI4aFwWZFGBtaJ3SGli+ZyHJDHf7WGlXGAqC"
    b"MJAqlLANteEbLmCJ7pzJIN9OVJpSyWrdMBRqSQRsQPTH09FDY4NqThi1q7mihvUXVFho7Goul/3KbikzasMZGEuY"
    b"StZgzu0T2Gllgc33DBY0E+7Uy8sTEtxWmXX/p39mj4PhaHwXT4ez3x8e76JwIbIdGH9kt//WsAHSmb1WXDpLtjDP"
    b"cwaEMoaZtf3o6qp3VnnlnCZO2JcX+r42ScA4dKLEBnPBpA0ToTK2ENScN7JQZot5B7YCmicAXVsHjGuLlx9Nnv8Y"
    b"Psaz5+l0OImfnn/FLERh9/qS9Drk5w7ptC+vzucA4SatVsYRjFIrybCmjqegMlQz6Ldc9HtfOh3738xtEafwA+1x"
    b"Jt405/POFzyhDuwh/4igowIQmqRAIKVc1Pkc3NwP4+H9YDyJfnkCF5yIAy4DAnLz7UPesHUN9nm/7Vf5g/xtlfyQ"
    b"LZQlKyoEyCWQQ5v0XwXYB41Wqv0uyX/R596nLkFw5a+5A0wFN0qmWMADp9yM4tvpUzz4bRzPHu6G03g0ngyjoG0y"
    b"2cbCGnC2XfsNfRhOrUEeCM0r1Pz0puZGiSyFhqbba2TQOZesFKE1lZkEhe0NNbn/kkQs/lVKSK5LcGeUfDPESoq9"
    b"5+gGBXzHaQWq28FsEN+OH48gdRBWgGqX3B/6QpwGdyT1/qJqhayO4TmIV8q6WFO3ioKaR0vCbCQqJ8j6BpmUIPKl"
    b"oHMQlWIZDwZH5wLv08pttvJd5CThVskKknWljmMqCv5s3dzftj4FrfK0f20o+2UxOlp/leew53EoUhEF3aqHy76O"
    b"gs8HCYLCcKx2cODqfCbGGgxXrD6Ks2yJxg8xMZyAYKLAN1m4wFlYynFaciVtncKU7kLLv4K3lB5J/Sm8e691geIa"
    b"jOxobNfydlPlsnP5hXQ7pHd2jmfWh9nqRJ0ivwnVMTNK10UbTCY/aOI3Cl7QAx6mmVOZZgiiSo6d0NDJ+66ZwvDN"
    b"hi7sv7OnT5RP4fohgDLQIJnFln2hXdc88QPF4yDCCPPPsrhA6v7/h1Lzlnk7FuclTXPieMenDeywbaRvm7rVDzHO"
    b"DWdLLypSF72+iejVND0EjtlY8GV9jTCw2Vx66nnvx8ZFo86vsXZhu0gCOTcJ3oDIWRtHePoXRAlxVW4LAAA="
))


class UnraidControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fluxer-plugin-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.plugin = self.base / "plugin"
        self.project = self.base / "appdata/fluxer"
        bundle = self.plugin / "bundle"
        bundle.mkdir(parents=True)
        for name in ("setup.sh", "start.sh", ".env.example", "compose.ingress.yml"):
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
        ip = fakebin / "ip"
        ip.write_text("#!/bin/bash\nprintf '2: br0 inet %s/24 brd 192.168.30.255 scope global br0\\n' \"${FAKE_NAS_IP:-192.168.30.10}\"\n")
        ip.chmod(0o755)
        if shutil.which("sha256sum") is None:
            sha256sum = fakebin / "sha256sum"
            sha256sum.write_text("""#!/usr/bin/env python3
import hashlib, pathlib, sys
path = pathlib.Path(sys.argv[-1])
print(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path))
""")
            sha256sum.chmod(0o755)
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
        result = self.call("prepare", "chat.example.com", "admin@example.com", "192.168.30.10")
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
        self.assertNotEqual(self.call("prepare", "other.example.com", "admin@example.com", "192.168.30.10").returncode, 0)
        self.assertEqual((self.project / ".env").read_bytes(), original)
        self.assertEqual((self.project / ".env").stat().st_mode & 0o777, 0o600)

    def test_start_rejects_an_address_outside_this_nas(self):
        self.prepare()
        self.tokens()
        self.env["FAKE_NAS_IP"] = "192.168.30.11"
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertNotIn("compose up", self.docker_log())

    def test_prepare_rejects_nonprivate_or_invalid_addresses(self):
        for address in ("203.0.113.10", "127.0.0.1", "169.254.1.2", "0.0.0.0", "255.255.255.255", "192.168.030.10", "192.168.30.256"):
            with self.subTest(address=address):
                self.assertNotEqual(self.call("prepare", "chat.example.com", "admin@example.com", address).returncode, 0)
                self.assertFalse((self.project / ".env").exists())

    def test_prepare_supports_private_network_addresses(self):
        for index, address in enumerate(("10.20.30.40", "172.16.20.30", "192.168.30.10", "100.64.2.3")):
            with self.subTest(address=address):
                self.env["FLUXER_PROJECT_DIR"] = str(self.base / f"network-{index}")
                result = self.call("prepare", "chat.example.com", "admin@example.com", address)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"FLUXER_NAS_IP='{address}'", (Path(self.env["FLUXER_PROJECT_DIR"]) / ".env").read_text())

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

    def test_start_atomically_updates_beta3_ingress_and_preserves_instance_data(self):
        self.prepare()
        self.tokens()
        ingress = self.project / "compose.ingress.yml"
        ingress.write_bytes(LEGACY_INGRESS)
        bundled = self.plugin / "bundle/compose.ingress.yml"
        updated = bundled.read_bytes() + b"\n# Updated ingress\n"
        bundled.write_bytes(updated)
        data_file = self.project / "data/postgres-data/keep.txt"
        data_file.write_bytes(b"existing instance data")
        preserved = [self.project / ".env", data_file, *sorted((self.project / "secrets").iterdir())]
        originals = {path: path.read_bytes() for path in preserved}
        old_inode = ingress.stat().st_ino
        self.assertEqual(self.call("check").returncode, 0)
        self.assertEqual(ingress.read_bytes(), LEGACY_INGRESS)
        result = self.call("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(ingress.read_bytes(), updated)
        self.assertNotEqual(ingress.stat().st_ino, old_inode)
        self.assertEqual({path: path.read_bytes() for path in preserved}, originals)
        self.assertEqual(list(self.project.glob(".compose.ingress.yml.*")), [])
        self.assertIn("compose up -d", self.docker_log())

    def test_custom_ingress_prevents_start_without_overwrite(self):
        self.prepare()
        self.tokens()
        ingress = self.project / "compose.ingress.yml"
        custom = ingress.read_bytes() + b"\n# Local changes\n"
        ingress.write_bytes(custom)
        for action in ("check", "start"):
            with self.subTest(action=action):
                result = self.call(action)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("local changes", result.stderr)
                self.assertEqual(ingress.read_bytes(), custom)
        self.assertNotIn("compose up", self.docker_log())

    def test_symlink_ingress_prevents_start_without_changing_target(self):
        self.prepare()
        self.tokens()
        ingress = self.project / "compose.ingress.yml"
        outside = self.base / "outside.yml"
        original = ingress.read_bytes()
        outside.write_bytes(original)
        ingress.unlink()
        ingress.symlink_to(outside)
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertTrue(ingress.is_symlink())
        self.assertEqual(outside.read_bytes(), original)
        self.assertNotIn("compose up", self.docker_log())

    def test_symlink_bundle_prevents_start(self):
        self.prepare()
        self.tokens()
        bundled = self.plugin / "bundle/compose.ingress.yml"
        bundled.unlink()
        bundled.symlink_to(self.project / "compose.ingress.yml")
        self.assertNotEqual(self.call("start").returncode, 0)
        self.assertNotIn("compose up", self.docker_log())


if __name__ == "__main__":
    unittest.main()
