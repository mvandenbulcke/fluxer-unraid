from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import unittest

from test_unraid_upgrade import MANAGED_FILES, SOURCE, TARGET, UnraidUpgradeFixture


OLDER = "backup-Abc123"
NEWER = "backup-Xyz789"
OLD_TIME = 1793721600
NEW_TIME = 1794672000
REQUEST_ID = "72a1c1e6db2445d593926980b5228386"
USER_DATA = "data/postgres-data/messages.test"
POST_BACKUP_UPLOAD = "data/seaweedfs-data/new-upload.test"
POSTGRES_CONTROL = "data/postgres-data/global/pg_control"

RESTORE_DOCKER = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import sys

args = sys.argv[1:]
online = Path(os.environ['FAKE_PROJECT_ONLINE'])
running_check = args and args[0] == 'ps' and '-a' not in args
stop = args and 'stop' in args
start = args and 'up' in args
if stop:
    online.unlink(missing_ok=True)
if start:
    online.touch()
    if '--force-recreate' in args and os.environ.get('FAKE_RESTORE_WRITE') == '1':
        messages = Path(os.environ['FLUXER_PROJECT_DIR']) / 'data/postgres-data/messages.test'
        with messages.open('ab') as active_data:
            active_data.write(b'\\nrestored DB boot record')
if running_check or (stop and args[0] == 'stop') or (
    start and '--wait' in args and os.environ.get('FAKE_KILL_RESTORE') == '1'
) or ('config' in args and os.environ.get('FAKE_RESTORE_CONFIG_FAIL') == '1'):
    with Path(os.environ['FAKE_DOCKER_LOG']).open('a') as log:
        log.write(json.dumps(args) + '\\n')
    if running_check:
        if online.exists():
            identity = '0123456789ab'
            if 'com.docker.compose.project.working_dir' in args[-1]:
                owner = os.environ.get('FAKE_RUNNING_OWNER', os.environ['FLUXER_PROJECT_DIR'])
                identity += '|' + owner
            print(identity)
        sys.exit(0)
    if stop:
        sys.exit(0)
    if start:
        os.kill(os.getppid(), signal.SIGKILL)
        sys.exit(1)
    print('configuration diagnostic includes private-test-database-key', file=sys.stderr)
    sys.exit(1)
mock = Path(__file__).with_name('docker-base')
os.execv(mock, [str(mock), *args])
'''

RESTORE_MV = '''#!/usr/bin/env python3
import os
from pathlib import Path
import signal
import sys

args = sys.argv[1:]
real_mv = os.environ['REAL_MV']
fault = os.environ.get('FAKE_RENAME_FAULT')
if fault:
    if args == ['--help']:
        print('--no-copy')
        sys.exit(0)
    if len(args) >= 2 and Path(args[-2]).is_dir():
        source, destination = map(Path, args[-2:])
        live = Path(os.environ['FLUXER_PROJECT_DIR'])
        if fault == 'failed_staged_move' and destination == live and source.parent.name.startswith('.restore-stage-'):
            sys.exit(1)
        os.rename(source, destination)
        if fault == 'interrupted_after_displace' and source == live:
            os.kill(os.getppid(), signal.SIGKILL)
            sys.exit(1)
        sys.exit(0)
os.execv(real_mv, [real_mv, *args])
'''


class UnraidRestoreTests(UnraidUpgradeFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.preserved[POSTGRES_CONTROL] = b"synthetic database control data"
        control_path = self.project / POSTGRES_CONTROL
        control_path.parent.mkdir(mode=0o700)
        control_path.write_bytes(self.preserved[POSTGRES_CONTROL])
        control_path.chmod(0o600)
        mock = self.base / "bin" / "docker"
        mock.rename(mock.with_name("docker-base"))
        self.write_executable(mock, RESTORE_DOCKER)
        real_mv = shutil.which("mv")
        self.assertIsNotNone(real_mv)
        self.env["REAL_MV"] = real_mv
        self.write_executable(mock.with_name("mv"), RESTORE_MV)
        online = self.base / "online"
        online.touch()
        self.env["FAKE_PROJECT_ONLINE"] = str(online)

    def install_fixture(self, release, messages):
        for name in MANAGED_FILES:
            (self.project / name).write_bytes(self.versioned_contents(name, release))
        (self.project / USER_DATA).write_bytes(messages)

    def make_backup(self, backup_id, timestamp):
        self.backups.mkdir(mode=0o700, exist_ok=True)
        folder = self.backups / backup_id
        folder.mkdir(mode=0o700)
        project_copy = folder / "project"
        shutil.copytree(self.project, project_copy)
        os.utime(project_copy, (timestamp, timestamp))
        os.utime(folder, (timestamp, timestamp))
        return project_copy

    def active_and_old_backup(self):
        self.install_fixture(SOURCE, b"two old messages")
        backup = self.make_backup(OLDER, OLD_TIME)
        self.install_fixture(TARGET, b"two old messages and a new message")
        (self.project / POST_BACKUP_UPLOAD).write_bytes(b"upload after the backup")
        return backup

    @staticmethod
    def files_under(directory):
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()
        }

    def restore_info(self):
        result = self.call("restore_info")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def restore(self, backup_id=OLDER):
        return self.call("restore", backup_id, REQUEST_ID)

    def test_list_legacy_backups_newest_first_with_release_and_time(self):
        self.install_fixture(SOURCE, b"old messages")
        self.make_backup(OLDER, OLD_TIME)
        self.install_fixture(TARGET, b"newer messages")
        self.make_backup(NEWER, NEW_TIME)
        incomplete = self.make_backup("backup-Bad123", NEW_TIME)
        (incomplete / POSTGRES_CONTROL).unlink()

        entries = self.restore_info()["backups"]
        self.assertEqual([entry["id"] for entry in entries], [NEWER, OLDER])
        self.assertEqual([entry["release"] for entry in entries], [TARGET, SOURCE])
        times = [datetime.fromisoformat(entry["created_at"]).astimezone(timezone.utc) for entry in entries]
        self.assertEqual(times, [datetime.fromtimestamp(value, timezone.utc) for value in (NEW_TIME, OLD_TIME)])
        self.assertEqual(self.docker_commands(), [])

    def test_restores_old_selection_and_preserves_current_project(self):
        old_backup = self.active_and_old_backup()
        new_backup = self.make_backup(NEWER, NEW_TIME)
        current_env = self.project / ".env"
        current_env.write_bytes(current_env.read_bytes().replace(b"203.0.113.1", b"203.0.113.2"))
        (self.project / "secrets/cloudflare-dns-token").write_bytes(b"rotated test token")
        old_files = self.files_under(old_backup)
        newer_files = self.files_under(new_backup)
        current_files = self.files_under(self.project)
        self.env["FAKE_RESTORE_WRITE"] = "1"

        result = self.restore(OLDER)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = self.upgrade_commands()
        self.assertLess(observed.index("config"), observed.index("pull"))
        self.assertLess(observed.index("pull"), observed.index("stop"))
        self.assertLess(observed.index("stop"), observed.index("up"))
        pull = next(command for command in self.docker_commands() if "pull" in command)
        self.assertEqual(pull[pull.index("--project-directory") + 1], str(self.project))
        self.assertNotEqual(Path(pull[pull.index("--env-file") + 1]), current_env)
        self.assertEqual(pull[pull.index("--policy") + 1], "missing")
        up = next(command for command in self.docker_commands() if "up" in command)
        self.assertEqual(up[up.index("--pull") + 1], "never")
        self.assertIn("--force-recreate", up)

        expected_active = {**old_files, USER_DATA: b"two old messages\nrestored DB boot record"}
        self.assert_files(self.project, expected_active)
        self.assertFalse((self.project / POST_BACKUP_UPLOAD).exists())
        self.assertEqual(self.files_under(old_backup), old_files)
        self.assertEqual(self.files_under(new_backup), newer_files)
        state = self.restore_info()
        self.assertEqual(self.info()["installed"], SOURCE)
        self.assertEqual(state["state"], "completed")
        self.assertEqual(state["request_id"], REQUEST_ID)
        self.assertEqual(state["selected_id"], OLDER)
        saved_current = Path(state["preserved"])
        self.assertEqual(self.files_under(saved_current), current_files)
        self.assertEqual(stat.S_IMODE(saved_current.parent.stat().st_mode), 0o700)
        self.assertFalse((self.backups / "pending").exists())

    def test_outside_incomplete_and_missing_backups_cannot_restore(self):
        old_backup = self.active_and_old_backup()
        linked = self.backups / "backup-Link00"
        linked.symlink_to(old_backup.parent)
        incomplete = self.backups / "backup-Miss00" / "project"
        incomplete.mkdir(parents=True)
        for backup_id in ("../" + OLDER, str(old_backup), linked.name, incomplete.parent.name, "backup-NoBack"):
            with self.subTest(backup_id=backup_id):
                result = self.restore(backup_id)
                self.assertNotEqual(result.returncode, 0)

        self.assertEqual(self.upgrade_commands(), [])
        self.assert_files(self.project, {**self.target, **self.preserved})
        self.assertTrue((self.project / POST_BACKUP_UPLOAD).is_file())

    def test_config_and_pull_failures_leave_current_project_intact(self):
        old_backup = self.active_and_old_backup()
        old_files = self.files_under(old_backup)
        current_files = self.files_under(self.project)
        for failed_stage, flag in (("config", "FAKE_RESTORE_CONFIG_FAIL"), ("pull", "FAKE_PULL_FAIL")):
            with self.subTest(stage=failed_stage):
                self.docker_log.unlink(missing_ok=True)
                self.env[flag] = "1"
                try:
                    self.assertNotEqual(self.restore().returncode, 0)
                finally:
                    del self.env[flag]
                observed = self.upgrade_commands()
                self.assertIn(failed_stage, observed)
                self.assertNotIn("stop", observed)
                self.assertNotIn("up", observed)
                self.assertEqual(self.files_under(self.project), current_files)
                self.assertEqual(self.files_under(old_backup), old_files)
                self.assertFalse((self.backups / "pending").exists())

    def test_conflicting_project_owner_during_restore_never_gets_stopped(self):
        self.active_and_old_backup()
        current_files = self.files_under(self.project)
        self.env["FAKE_RUNNING_OWNER"] = str(self.base / "unrelated-project")

        self.assertNotEqual(self.restore().returncode, 0)
        self.assertIn("pull", self.upgrade_commands())
        self.assertNotIn("stop", self.upgrade_commands())
        self.assertNotIn("up", self.upgrade_commands())
        self.assertEqual(self.files_under(self.project), current_files)
        self.assertFalse((self.backups / "pending").exists())

    def test_can_restore_a_backup_during_failed_upgrade_recovery(self):
        self.install_fixture(SOURCE, b"two old messages")
        self.env["FAKE_HEALTH_FAIL"] = "1"
        self.assertNotEqual(self.call("upgrade", TARGET).returncode, 0)
        self.assertTrue((self.backups / "pending").exists())
        old_backup = self.backup()
        (self.project / USER_DATA).write_bytes(b"unsuccessful migration data")
        del self.env["FAKE_HEALTH_FAIL"]

        result = self.restore(old_backup.parent.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / USER_DATA).read_bytes(), b"two old messages")
        self.assertEqual(self.info()["installed"], SOURCE)
        self.assertFalse((self.backups / "pending").exists())

    def test_health_failure_keeps_both_copies_and_blocks_start(self):
        old_backup = self.active_and_old_backup()
        old_files = self.files_under(old_backup)
        current_files = self.files_under(self.project)
        self.env["FAKE_HEALTH_FAIL"] = "1"

        self.assertNotEqual(self.restore().returncode, 0)
        self.assertEqual(self.upgrade_commands()[-4:], ["stop", "config", "up", "stop"])
        self.assertEqual(self.files_under(old_backup), old_files)
        state = self.restore_info()
        self.assertEqual(state["phase"], "recovery")
        self.assertEqual(self.files_under(Path(state["preserved"])), current_files)
        self.assertTrue((self.backups / "pending").exists())
        self.assertNotEqual(self.call("start").returncode, 0)
        self.call("autostart")
        self.assertEqual(self.upgrade_commands().count("up"), 1)

    def test_interruption_after_swapping_folders_keeps_recovery_guard(self):
        old_backup = self.active_and_old_backup()
        old_files = self.files_under(old_backup)
        current_files = self.files_under(self.project)
        self.env["FAKE_KILL_RESTORE"] = "1"

        self.assertNotEqual(self.restore().returncode, 0)
        self.assertIn("up", self.upgrade_commands())
        self.assertEqual(self.files_under(old_backup), old_files)
        state = self.restore_info()
        self.assertEqual(state["state"], "interrupted")
        self.assertEqual(self.files_under(Path(state["preserved"])), current_files)
        self.assertTrue((self.backups / "pending").exists())
        self.assertNotEqual(self.call("start").returncode, 0)

    def test_failed_swap_moves_current_project_back_before_return(self):
        old_backup = self.active_and_old_backup()
        old_files = self.files_under(old_backup)
        current_files = self.files_under(self.project)
        self.env["FAKE_RENAME_FAULT"] = "failed_staged_move"

        self.assertNotEqual(self.restore().returncode, 0)
        self.assertIn("stop", self.upgrade_commands())
        self.assertNotIn("up", self.upgrade_commands())
        self.assertEqual(self.files_under(self.project), current_files)
        self.assertEqual(self.files_under(old_backup), old_files)
        self.assertFalse((self.backups / "pending").exists())
        self.assertEqual(self.restore_info()["state"], "failed")
        self.assertEqual(self.call("start").returncode, 0)

    def test_retries_restore_when_interrupted_swap_leaves_live_folder_missing(self):
        old_backup = self.active_and_old_backup()
        old_files = self.files_under(old_backup)
        current_files = self.files_under(self.project)
        self.env["FAKE_RENAME_FAULT"] = "interrupted_after_displace"

        self.assertNotEqual(self.restore().returncode, 0)
        self.assertFalse(self.project.exists())
        self.assertNotIn("up", self.upgrade_commands())
        state = self.restore_info()
        self.assertEqual(state["state"], "interrupted")
        self.assertTrue(state["available"])
        preserved = Path(state["preserved"])
        self.assertEqual(self.files_under(preserved), current_files)
        self.assertTrue((self.backups / "pending").exists())
        self.assertNotEqual(self.call("start").returncode, 0)

        del self.env["FAKE_RENAME_FAULT"]
        retry = self.restore()
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(self.files_under(self.project), old_files)
        self.assertEqual(self.files_under(old_backup), old_files)
        self.assertEqual(self.files_under(preserved), current_files)
        self.assertFalse((self.backups / "pending").exists())


if __name__ == "__main__":
    unittest.main()
