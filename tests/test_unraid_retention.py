import json
import os
from pathlib import Path
import shutil
import time
import unittest

from test_unraid_upgrade import TARGET, UnraidUpgradeFixture


class UnraidRetentionTests(UnraidUpgradeFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        control = self.project / "data/postgres-data/global/pg_control"
        control.parent.mkdir()
        control.write_bytes(b"test database control data")

    def success(self, *args):
        result = self.call(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def marked_backup(self):
        self.success("upgrade", TARGET)
        path = Path(json.loads(self.success("upgrade_info"))["backup"])
        self.assertTrue((path.parent / ".fluxer-retention.json").is_file())
        return path

    def legacy_backup(self, backup, name):
        wrapper = self.backups / name
        wrapper.mkdir(mode=0o700)
        project = wrapper / "project"
        shutil.copytree(backup, project)
        newer = backup.parent.stat().st_mtime + 1
        os.utime(wrapper, (newer, newer))
        return project

    def advance_clock(self):
        future = int(time.time()) + 40 * 86400
        self.write_executable(self.base / "bin/date", f"#!/bin/sh\necho {future}\n")

    def test_retention_defaults_to_keep_all_and_rejects_invalid_days(self):
        self.assertEqual(json.loads(self.success("retention_info")), {"days": 0})
        for value in ("-1", "01", "1e2", "3651"):
            with self.subTest(value=value):
                self.assertNotEqual(self.call("retention_set", value).returncode, 0)
        self.assertEqual(json.loads(self.success("retention_info")), {"days": 0})

    def test_cleanup_keeps_latest_and_never_prunes_unmarked_or_preserved_data(self):
        marked = self.marked_backup()
        displaced = self.backups / "displaced-AbC123"
        displaced.mkdir(mode=0o700)
        (displaced / "data").write_bytes(b"data from before restore")
        incomplete = self.backups / ".backup-AbC123"
        incomplete.mkdir(mode=0o700)
        self.advance_clock()
        self.success("retention_set", "30")
        self.success("retention_cleanup")
        self.assertTrue(marked.is_dir(), "The newest complete backup should survive expiry.")

        legacy = self.legacy_backup(marked, "backup-Leg123")
        self.assertTrue(marked.is_dir(), "Saving a policy must leave backups in place.")
        self.success("retention_cleanup")
        self.assertFalse(marked.exists())
        self.assertTrue(legacy.is_dir())
        self.assertTrue(incomplete.is_dir())
        self.assertEqual((displaced / "data").read_bytes(), b"data from before restore")

    def test_cleanup_skips_recovery_and_disabled_policy(self):
        marked = self.marked_backup()
        self.legacy_backup(marked, "backup-Leg123")
        self.advance_clock()
        self.success("retention_cleanup")
        self.assertTrue(marked.is_dir())
        self.success("retention_set", "30")
        pending = self.backups / "pending"
        pending.touch()
        self.success("retention_cleanup")
        self.assertTrue(marked.is_dir())
        pending.unlink()
        self.success("retention_cleanup")
        self.assertFalse(marked.exists())

    def test_cleanup_preserves_a_changed_managed_backup(self):
        marked = self.marked_backup()
        self.legacy_backup(marked, "backup-Leg123")
        (marked / "data/postgres-data/PG_VERSION").write_bytes(b"changed copy\n")
        self.advance_clock()
        self.success("retention_set", "30")
        self.success("retention_cleanup")
        self.assertEqual((marked / "data/postgres-data/PG_VERSION").read_bytes(), b"changed copy\n")
