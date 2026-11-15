import fcntl
import json
import os
from pathlib import Path
import unittest

from test_unraid_upgrade import SOURCE, TARGET, UnraidUpgradeFixture


AUTO_DOCKER = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args == ['compose', 'config', '--services'] or (
    args[:2] == ['compose', 'ps'] and '--services' in args and 'running' in args
):
    with Path(os.environ['FAKE_DOCKER_LOG']).open('a') as log:
        log.write(json.dumps(args) + '\\n')
    variable = 'FAKE_EXPECTED_SERVICES' if args[1] == 'config' else 'FAKE_RUNNING_SERVICES'
    print(os.environ[variable])
    sys.exit(0)
mock = Path(__file__).with_name('docker-base')
os.execv(mock, [str(mock), *args])
'''


class UnraidAutomaticUpgradeTests(UnraidUpgradeFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        mock = self.base / "bin" / "docker"
        mock.rename(mock.with_name("docker-base"))
        self.write_executable(mock, AUTO_DOCKER)
        self.env["FAKE_EXPECTED_SERVICES"] = "api\nseaweedfs-init"
        self.env["FAKE_RUNNING_SERVICES"] = "api"

    def success(self, *args):
        result = self.call(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def auto_info(self):
        return json.loads(self.success("auto_upgrade_info"))

    def enable(self):
        self.success("auto_upgrade_set", "on")
        config = self.auto_info()
        self.assertTrue(config["enabled"])
        self.assertIsNone(config["last_attempt"])

    def assert_no_upgrade(self):
        commands = self.upgrade_commands()
        for operation in ("pull", "stop", "up"):
            self.assertNotIn(operation, commands)
        self.assertIsNone(self.auto_info()["last_attempt"])
        self.assert_files(self.project, {**self.original, **self.preserved})

    def test_defaults_to_off_and_rejects_invalid_setting(self):
        self.assertEqual(self.auto_info(), {"enabled": False, "last_attempt": None})
        self.assertNotEqual(self.call("auto_upgrade_set", "yes").returncode, 0)
        self.success("auto_upgrade_run")
        self.assertEqual(self.docker_commands(), [])
        self.assertEqual(self.auto_info(), {"enabled": False, "last_attempt": None})
        self.assert_files(self.project, {**self.original, **self.preserved})

    def test_opt_in_applies_supported_release_when_required_services_are_running(self):
        self.enable()
        self.assert_no_upgrade()
        self.success("auto_upgrade_run")
        self.assertEqual(self.info()["installed"], TARGET)
        self.assertEqual(self.auto_info(), {"enabled": True, "last_attempt": TARGET})
        self.assert_files(self.backup(), {**self.original, **self.preserved})
        self.assert_files(self.project, {**self.target, **self.preserved})
        runs = self.upgrade_commands().count("up")
        self.success("auto_upgrade_run")
        self.assertEqual(self.upgrade_commands().count("up"), runs)

    def test_no_upgrade_when_plugin_has_stopped_fluxer(self):
        self.enable()
        (self.project / ".unraid-autostart").unlink()
        self.success("auto_upgrade_run")
        self.assert_no_upgrade()

    def test_no_upgrade_when_docker_is_stopped_or_a_required_service_is_missing(self):
        self.enable()
        self.env["FAKE_EXPECTED_SERVICES"] = "api\ngateway\nseaweedfs-init"
        for running in ("", "api"):
            with self.subTest(running=running):
                self.env["FAKE_RUNNING_SERVICES"] = running
                self.success("auto_upgrade_run")
                self.assert_no_upgrade()

    def test_no_upgrade_during_other_maintenance_or_recovery(self):
        self.enable()
        with Path(self.env["FLUXER_LOCK_FILE"]).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.success("auto_upgrade_run")
        self.assert_no_upgrade()
        (self.backups / "pending").touch()
        self.success("auto_upgrade_run")
        self.assert_no_upgrade()

    def test_failed_automatic_attempt_is_not_retried_and_manual_upgrade_still_works(self):
        self.enable()
        self.env["FAKE_PULL_FAIL"] = "1"
        self.call("auto_upgrade_run")
        self.assertEqual(self.info()["state"], "failed")
        self.assertEqual(self.auto_info()["last_attempt"], TARGET)
        self.assertEqual(self.upgrade_commands().count("pull"), 1)
        self.assert_files(self.project, {**self.original, **self.preserved})

        del self.env["FAKE_PULL_FAIL"]
        self.success("auto_upgrade_run")
        self.assertEqual(self.upgrade_commands().count("pull"), 1)
        self.assertNotIn("stop", self.upgrade_commands())
        self.assertNotIn("up", self.upgrade_commands())
        self.success("upgrade", TARGET)
        self.assertEqual(self.info()["installed"], TARGET)

    def test_restore_turns_off_automatic_upgrades_and_keeps_attempt_history(self):
        control = self.project / "data/postgres-data/global/pg_control"
        control.parent.mkdir()
        control.write_bytes(b"test database control data")
        self.enable()
        self.success("auto_upgrade_run")
        self.assertEqual(self.info()["installed"], TARGET)
        self.assertEqual(self.auto_info(), {"enabled": True, "last_attempt": TARGET})

        self.success("restore", self.backup().parent.name)
        self.assertEqual(self.info()["installed"], SOURCE)
        self.assertEqual(self.auto_info(), {"enabled": False, "last_attempt": TARGET})
        runs = self.upgrade_commands().count("up")
        self.success("auto_upgrade_run")
        self.assertEqual(self.upgrade_commands().count("up"), runs)


if __name__ == "__main__":
    unittest.main()
