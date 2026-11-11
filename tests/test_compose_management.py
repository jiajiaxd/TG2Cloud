"""Host-only Compose maintenance, private copies and conservative rollback."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_compose_https as fixtures

from tg2cloud.compose import lifecycle, maintenance, management, packaging, releases
from tg2cloud.compose.webdav import ComposeWebDAV
from tg2cloud.deployment.profiles import PRODUCTS
from tg2cloud.persistence.control import handle

ROOT = Path(__file__).resolve().parents[1]


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ComposeHttpsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        patch.object(management, "owned_file", side_effect=lambda path, **_: path.read_bytes()).start()

    def manager(self, edition="openlist"):
        core, _ = self.fixture.candidate(edition)
        return management.ComposeManagement(core.root, core.session, self.fixture.log, Mock(), source=ROOT)

    def test_both_editions_discover_read_only_and_keep_container_identity(self):
        for edition in PRODUCTS:
            self.fixture.containers.clear()
            manager = self.manager(edition)
            found = manager.discover()
            self.assertEqual(found.deployment_mode, "compose")
            self.assertEqual(found.product.key, edition)
            self.assertEqual(found.container_ids, ("2" * 64, "1" * 64))
            self.assertEqual(manager.recheck(found).raw_config, found.raw_config)
        self.assertFalse(any(token in command for command in self.fixture.commands for token in (" stop ", " up ", "restart")))

    def test_replaced_container_and_foreign_mount_are_refused(self):
        manager = self.manager()
        found = manager.discover()
        self.fixture.containers[manager.product.bot_container]["id"] = "f" * 64
        with self.assertRaises(ValueError):
            manager.recheck(found)
        self.fixture.containers[manager.product.bot_container]["mounts"][0]["Source"] = str(self.fixture.directory / "unrelated")
        with self.assertRaises(ValueError):
            manager.discover()

    def test_script_labels_or_files_never_enter_compose_maintenance(self):
        for edition in PRODUCTS:
            self.fixture.containers.clear()
            manager = self.manager(edition)
            for container in self.fixture.containers.values():
                container["labels"].pop("com.tg2cloud.install-mode")
            with self.assertRaises(ValueError):
                manager.discover()
            for container in self.fixture.containers.values():
                container["labels"]["com.tg2cloud.install-mode"] = "compose"
            for name in ("app", "remote_install.sh", "tg2cloud-release.json"):
                path = manager.root / name
                path.write_text("synthetic-script-owner")
                with self.assertRaisesRegex(ValueError, "一键脚本部署文件"):
                    manager.discover()
                self.assertEqual(path.read_text(), "synthetic-script-owner")
                path.unlink()

    def test_legacy_one_and_two_use_their_original_render(self):
        manager = self.manager()
        path = manager.root / "compose-bundle.json"
        original = json.loads(path.read_text())
        for number in (1, 2):
            value = original | {"format": number}
            if number == 1:
                value.pop("https_tools")
            path.write_text(json.dumps(value))
            (manager.root / "docker-compose.yml").write_text(packaging.render(ROOT, "openlist", fixtures.IMAGE, legacy=True))
            self.assertEqual(manager.discover().product.key, "openlist")

    def test_menu_reuses_shared_business_and_has_own_lifecycle(self):
        for name in ("logs", "verify", "readiness", "listening"):
            self.assertNotIn(name, management.ComposeManagement.__dict__)
        for name in ("upgrade", "remove", "backups", "external_webdav", "control"):
            self.assertIn(name, management.ComposeManagement.__dict__)
        manager = self.manager()
        manager.project = "test"
        command = manager.compose_command("up", "-d", manager.product.bot_service)
        self.assertIn("--project-name test", command)
        self.assertIn("--project-directory", command)
        self.assertNotIn(" down", command)

    def test_control_pause_uses_authorized_endpoint_without_stopping_gateway(self):
        manager = self.manager()
        found = manager.discover()
        found.running = True
        manager.ui.ask.return_value = "7"
        manager.ui.confirm.return_value = True
        with patch.object(manager, "recheck", return_value=found), patch.object(management, "edition_lock", return_value=nullcontext()), patch(
            "tg2cloud.deployment.feature_settings.request", return_value={"queue": {"paused": True, "active": 1}}
        ) as request:
            self.assertTrue(manager.control(found))
        self.assertEqual(request.call_args.args[2], "queue-pause")
        self.assertFalse(any("docker stop" in value for value in self.fixture.commands))

    def test_addon_checks_compose_owner_and_never_redeploys_business_services(self):
        manager = self.manager()
        found = manager.discover()
        service = ComposeWebDAV(manager)
        self.assertEqual(service.selected(manager.product, str(manager.root), manager.session, manager.log).directory, found.directory)
        with self.assertRaises(ValueError):
            service.selected(manager.product, str(manager.root / "foreign"), manager.session, manager.log)
        with self.assertRaises(ValueError):
            service.selected(PRODUCTS["clouddrive2"], None, manager.session, manager.log)
        self.assertFalse(any(" restart " in value or " up " in value for value in self.fixture.commands))


class OfflineToolsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, content in packaging.bundle_files(ROOT, "openlist", fixtures.IMAGE, "a" * 40).items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def test_tools_verify_and_help_work_without_bot_dependencies_from_other_cwd(self):
        releases.verify_tools(self.root)
        command = [sys.executable, "-I", "-S", "-B", "-c", ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                   "runpy.run_module('tg2cloud.compose.management',run_name='__main__')"), str(self.root / "https-tools/src"), "--help"]
        result = subprocess.run(command, cwd=self.root.parent, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("uninstall", result.stdout)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_changed_missing_extra_and_empty_directory_are_rejected(self):
        path = self.root / "https-tools/src/tg2cloud/version.py"
        original = path.read_bytes()
        path.write_bytes(original + b"\n# edited\n")
        with self.assertRaises(ValueError):
            releases.verify_tools(self.root)
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(ValueError):
            releases.verify_tools(self.root)
        path.write_bytes(original)
        (self.root / "https-tools/unrecognized").mkdir()
        with self.assertRaises(ValueError):
            releases.verify_tools(self.root)

    def test_download_never_falls_back_to_main_on_asset_mismatch(self):
        client = Mock()
        release = SimpleNamespace(tag="v1.5.7", version="1.5.7", commit="a" * 40)
        client.resolve.return_value = release
        client.json.return_value = {"tag_name": release.tag, "draft": False, "prerelease": False, "assets": []}
        with patch.object(releases, "read_asset") as read, self.assertRaises(ValueError):
            releases.download("openlist", self.root, client=client)
        read.assert_not_called()

    def test_early_bundle_without_helpers_stops_before_docker_or_initialization(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "compose-bundle.json").write_text('{"format":1}')
            logs, session, ui = [], Mock(), Mock()
            from tg2cloud.deployment.host import SafeLog
            with patch.object(management.preflight, "validate_host"), patch.object(
                management.architecture, "check_environment"
            ), patch.object(management, "owned_file", side_effect=lambda path: path.read_bytes()), patch.object(
                management, "initialize"
            ) as initialize:
                result = management.main(["status", "--root", str(root)], session=session, ui=ui, log=SafeLog(logs.append))
            self.assertEqual(result, 1)
            self.assertIn("早期 Compose 部署包", "\n".join(logs))
            session.run.assert_not_called()
            ui.confirm.assert_not_called()
            initialize.assert_not_called()
            self.assertEqual({path.name for path in root.iterdir()}, {"compose-bundle.json"})

    def official_asset(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            for path in sorted(self.root.rglob("*")):
                if path.is_file():
                    body = path.read_bytes()
                    member = tarfile.TarInfo("TG2Cloud-test/" + path.relative_to(self.root).as_posix())
                    member.size = len(body)
                    tar.addfile(member, io.BytesIO(body))
        body = archive.getvalue()
        release = SimpleNamespace(tag="v" + fixtures.VERSION, version=fixtures.VERSION, commit="a" * 40)
        name = "TG2Cloud-" + release.tag + "-compose-openlist.tar.gz"
        metadata = {"tag_name": release.tag, "draft": False, "prerelease": False, "assets": [
            {"name": item, "browser_download_url": "https://github.com/jiajiaxd/TG2Cloud/releases/download/" + release.tag + "/" + item}
            for item in (name, "COMPOSE-SHA256SUMS.txt")]}
        client = Mock()
        client.resolve.return_value, client.json.return_value = release, metadata
        sums = (hashlib.sha256(body).hexdigest() + "  " + name + "\n").encode()
        return client, sums, body

    def test_download_verifies_complete_bundle_and_rechecks_immutable_identity(self):
        client, sums, body = self.official_asset()
        destination = self.root / "download"
        destination.mkdir()
        with patch.object(releases, "read_asset", side_effect=[sums, body]):
            root = releases.download("openlist", destination, client=client)
        releases.verify_tools(root)
        self.assertEqual(json.loads((root / "compose-bundle.json").read_text())["format"], 3)
        self.assertEqual(client.resolve.call_count, 2)

    def test_bad_checksum_stops_before_unpacking_and_never_executes_candidate(self):
        client, sums, body = self.official_asset()
        with patch.object(releases, "read_asset", side_effect=[sums, body + b"changed"]), patch.object(
            releases.releases, "extract_source"
        ) as unpack, self.assertRaises(ValueError):
            releases.download("openlist", self.root, client=client)
        unpack.assert_not_called()

    def test_private_config_compare_and_swap_preserves_changed_input(self):
        path = self.root / "private-test"
        path.write_bytes(b"newer-user-config")
        with patch.object(maintenance, "owned_file", side_effect=lambda path, **_: path.read_bytes()), self.assertRaises(ValueError):
            maintenance.replace_private(path, b"candidate", expected=b"previous")
        self.assertEqual(path.read_bytes(), b"newer-user-config")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.instance = SimpleNamespace(version="1.5.7", running=True, container_ids=("b" * 64, "c" * 64))
        self.manager = SimpleNamespace(root=self.root, product=PRODUCTS["openlist"], ui=Mock(), log=Mock(), session=Mock(),
            core=SimpleNamespace(info={"format": 2}, validate=Mock(return_value={
                PRODUCTS["openlist"].bot_container: {"running": True}, PRODUCTS["openlist"].storage_container: {"running": True}})),
            checked_run=Mock(), recheck=Mock(return_value=self.instance), compose_command=lambda *args, **kwargs: "compose " + " ".join(args))
        self.manager.ui.ask.return_value = ""
        self.manager.ui.confirm.return_value = True
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        (self.candidate / "compose-bundle.json").write_text('{"version":"1.5.7"}')
        self.journals = []
        for name, value in (("edition_lock", nullcontext()), ("atomic_private", None), ("scheduler_state", (True, 0))):
            replacement = patch.object(lifecycle, name, return_value=value).start()
            if name == "atomic_private":
                replacement.side_effect = lambda path, record: self.journals.append(dict(record))
        patch.object(lifecycle.runtime, "operation_lock", return_value=nullcontext()).start()
        patch.object(lifecycle.releases, "download", return_value=self.candidate).start()
        patch.object(lifecycle.backup, "create", return_value=self.root / "backup.tar.gz").start()
        patch.object(lifecycle.backup, "container", side_effect=lambda session, name: {
            "id": "b" * 64 if name == self.manager.product.bot_container else "c" * 64, "running": True}).start()
        patch.object(lifecycle, "public_files", side_effect=lambda root: {"release-file": b"candidate" if root == self.candidate else b"old"}).start()
        self.switch = patch.object(lifecycle, "switch_public").start()
        self.addCleanup(patch.stopall)

    def test_failed_pull_restores_services_without_replacing_database(self):
        def command(text, **_):
            if "pull" in text:
                raise RuntimeError("synthetic pull failure")
        self.manager.checked_run.side_effect = command
        with self.assertRaises(RuntimeError):
            lifecycle.upgrade(self.manager, self.instance)
        self.assertEqual(self.journals[-1]["phase"], "rolled-back")
        self.switch.assert_not_called()
        self.assertIn("docker stop -t 45 " + "b" * 64, self.manager.checked_run.call_args_list[0].args[0])

    def test_changed_instance_is_not_started_during_rollback(self):
        self.manager.recheck.side_effect = [self.instance, ValueError("synthetic changed owner")]
        def command(text, **_):
            if "pull" in text:
                raise RuntimeError("synthetic pull failure")
        self.manager.checked_run.side_effect = command
        with self.assertRaises(RuntimeError):
            lifecycle.upgrade(self.manager, self.instance)
        self.assertFalse(any("up -d" in call.args[0] for call in self.manager.checked_run.call_args_list))
        self.assertNotEqual(self.journals[-1]["phase"], "rolled-back")

    def test_failed_new_bot_keeps_new_database_stops_bot_and_records_review(self):
        with patch.object(lifecycle, "wait_for_bot", side_effect=RuntimeError("synthetic health failure")), self.assertRaises(RuntimeError):
            lifecycle.upgrade(self.manager, self.instance)
        self.assertEqual(self.journals[-1]["phase"], "needs-review")
        self.switch.assert_called_once()
        self.assertIn("stop " + self.manager.product.bot_service, self.manager.checked_run.call_args.args[0])
        self.assertFalse(any("restore" in call.args[0] for call in self.manager.checked_run.call_args_list))

    def test_success_retains_pause_and_rechecks_identity_after_pull(self):
        with patch.object(lifecycle, "wait_for_bot", return_value={"version": "1.5.7"}):
            lifecycle.upgrade(self.manager, self.instance)
        self.assertEqual(self.journals[-1]["phase"], "completed")
        self.assertEqual(self.manager.recheck.call_count, 2)
        self.assertFalse(any("queue-resume" in call.args[0] for call in self.manager.checked_run.call_args_list))

    def test_active_work_refuses_upgrade_before_backup_or_service_stop(self):
        with patch.object(lifecycle, "scheduler_state", return_value=(True, 1)), self.assertRaises(ValueError):
            lifecycle.upgrade(self.manager, self.instance)
        self.manager.checked_run.assert_not_called()
        self.switch.assert_not_called()

    def test_safe_cleanup_does_not_include_other_edition_or_exported_backup(self):
        for child in ("data", "downloads", "logs", "config", "openlist/data", "clouddrive/config", "backups"):
            path = self.root / child
            path.mkdir(parents=True, exist_ok=True)
            (path / "keep-test").write_text("synthetic")
        with patch.object(lifecycle.backup, "mountpoints", return_value=set()):
            trees, _files = lifecycle.cleanup_plan(self.manager)
        planned = {str(path.relative_to(self.root)) for tree in trees for path, *_ in tree}
        self.assertTrue(any(path.startswith("openlist") for path in planned))
        self.assertFalse(any(path.startswith(("clouddrive", "backups")) for path in planned))
        for tree in trees:
            lifecycle.remove_tree(tree)
        self.assertTrue((self.root / "clouddrive/config/keep-test").exists())
        self.assertTrue((self.root / "backups/keep-test").exists())

    def test_cleanup_mount_or_unsafe_late_scope_does_not_delete_earlier_data(self):
        path = self.root / "data"
        path.mkdir()
        (path / "kept").write_text("synthetic")
        unsafe = self.root / "openlist"
        unsafe.mkdir()
        with patch.object(lifecycle.backup, "mountpoints", return_value={unsafe}), self.assertRaises(ValueError):
            lifecycle.cleanup_plan(self.manager)
        self.assertTrue((path / "kept").exists())


class ResourceAndControlTests(unittest.TestCase):
    def test_resource_constraints_and_actual_inspection(self):
        for values in ({"TG2CLOUD_BOT_MEMORY_LIMIT": "512M"}, {"TG2CLOUD_BOT_PIDS_LIMIT": "0"}, {"TG2CLOUD_BOT_CPUS": "nan"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                maintenance.validate_resources(values)
        values = {"TG2CLOUD_BOT_MEMORY_LIMIT": "1G", "TG2CLOUD_BOT_PIDS_LIMIT": "256", "TG2CLOUD_BOT_CPUS": "0.5"}
        maintenance.validate_resources(values)
        manager = SimpleNamespace(product=PRODUCTS["openlist"], checked_run=Mock(return_value="1073741824 500000000 256"))
        maintenance.verify_resource_limits(manager, values)
        self.assertNotIn("Config.Env", manager.checked_run.call_args.args[0])
        manager.checked_run.return_value = "0 0 0"
        with self.assertRaises(ValueError):
            maintenance.verify_resource_limits(manager, values)

    def test_queue_controls_are_admin_only_atomic_and_keep_tasks(self):
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
            connection.executescript("CREATE TABLE service_meta(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE tasks(state TEXT);")
            connection.executemany("INSERT INTO tasks VALUES(?)", [("queued",), ("uploading",), ("cleanup_pending",)])
            with self.assertRaises(ValueError):
                handle(connection, 123, {"admin_id": 456, "action": "queue-pause"})
            self.assertIsNone(connection.execute("SELECT value FROM service_meta").fetchone())
            for action, expected in (("queue-pause", True), ("queue-read", True), ("queue-resume", False)):
                result = handle(connection, 123, {"admin_id": 123, "action": action})
                self.assertEqual(result["queue"], {"paused": expected, "active": 2})
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 3)

    def test_encrypt_passphrase_is_only_stdin_and_plain_archive_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / "synthetic.tar.gz"
            source.write_bytes(b"private-test-archive")
            destination = root / "copy.gpg"
            calls = []
            def command(args, **kwargs):
                calls.append((args, kwargs))
                if "--symmetric" in args:
                    Path(args[args.index("--output") + 1]).write_bytes(b"synthetic-ciphertext")
                return SimpleNamespace(returncode=0)
            with patch.object(maintenance.shutil, "which", side_effect=lambda name: name), patch.object(
                maintenance.runtime, "private_config_file"
            ), patch.object(maintenance.subprocess, "run", side_effect=command):
                maintenance.encrypt_archive(source, destination, "SYNTHETIC-TEST-SECRET")
            self.assertEqual(destination.read_bytes(), b"synthetic-ciphertext")
            self.assertEqual(source.read_bytes(), b"private-test-archive")
            for args, kwargs in calls:
                self.assertNotIn("SYNTHETIC-TEST-SECRET", " ".join(args))
                self.assertNotIn("env", kwargs)
            self.assertEqual(calls[0][1]["input"], b"SYNTHETIC-TEST-SECRET\n")
            self.assertIn("--decrypt", calls[1][0])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(b"private-test-archive").hexdigest())

    def test_failed_encrypted_readback_does_not_publish_or_remove_plain_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source, destination = root / "original.tar.gz", root / "copy.gpg"
            source.write_bytes(b"synthetic-archive")
            def command(args, **kwargs):
                if "--symmetric" in args:
                    Path(args[args.index("--output") + 1]).write_bytes(b"cipher")
                return SimpleNamespace(returncode=1 if "--decrypt" in args else 0)
            with patch.object(maintenance.shutil, "which", side_effect=lambda name: name), patch.object(
                maintenance.runtime, "private_config_file"
            ), patch.object(maintenance.subprocess, "run", side_effect=command), self.assertRaises(ValueError):
                maintenance.encrypt_archive(source, destination, "SYNTHETIC-PASSWORD")
            self.assertFalse(destination.exists())
            self.assertEqual(source.read_bytes(), b"synthetic-archive")


if __name__ == "__main__":
    unittest.main()
