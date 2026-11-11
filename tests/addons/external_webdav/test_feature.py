from __future__ import annotations

import ast
import base64
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tg2cloud.addons.external_webdav import (
    cli,
    config,
    nginx,
    releases,
    scope,
    verification,
)
from tg2cloud.addons.external_webdav.service import Service
from tg2cloud.deployment import uninstall
from tg2cloud.deployment.host import SafeLog
from tg2cloud.deployment.profiles import PRODUCTS
from tg2cloud.deployment.proxy import maintenance
from tg2cloud.deployment.proxy.manager import (
    DomainProxyManager,
    render_compose,
    render_config_set,
)
from tg2cloud.deployment.proxy.state import (
    certificate_domains,
    empty_state,
    has_routes,
    normalize_state,
    state_with_route,
    state_without_route,
)

ROOT = Path(__file__).resolve().parents[3]
SECRET = "Kp9!synthetic-Qx8uLz-7mR"
XML = b'<D:multistatus xmlns:D="DAV:"><D:response><D:href>/dav/</D:href><D:propstat><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response></D:multistatus>'


def route(edition="openlist", *, enabled=True):
    return {"kind": "external_webdav", "owner": config.OWNER, "edition": edition,
            "instance_dir": PRODUCTS[edition].install_dir, "domain": edition + "-files.example.test",
            "enabled": enabled, "backend_port": PRODUCTS[edition].management_port,
            "auth_file": f"external-auth/{edition}.htpasswd"}


def shared():
    return {"version": 2, "domains": {"clouddrive2": {"domain": "admin.example.test", "backend_port": 19798}},
            "external_webdav": {"openlist": route()}}


def env(relative="Telegram", user="bot-reader"):
    return {"WEBDAV_" + key + "_B64": base64.b64encode(value.encode()).decode()
            for key, value in {"URL": PRODUCTS["openlist"].webdav_url, "USERNAME": user, "TARGET_PATH": relative}.items()}


class ConfigTests(unittest.TestCase):
    def test_logical_root_and_relative_are_distinct(self):
        self.assertEqual(config.logical_path("/网盘/视频 目录/"), "/网盘/视频 目录")
        self.assertEqual(config.logical_path("/", allow_root=True), "/")
        for value in ("/", "relative", "/a/../b", "/a//b", "/a\\b", "/a\nb"):
            with self.subTest(path=value), self.assertRaises(ValueError):
                config.logical_path(value)

    def test_bot_binding_tracks_directory_not_password(self):
        original = env()
        self.assertNotEqual(config.binding(original), config.binding(env("New")))
        self.assertNotEqual(config.binding(original), config.binding(env(user="other")))
        self.assertEqual(config.binding(original), config.binding(dict(original, WEBDAV_PASSWORD_B64="irrelevant")))

    def test_legacy_and_blank_primary_keys_follow_actual_bot_precedence(self):
        legacy = {"CD2_TARGET_PATH_B64": base64.b64encode(b"Old/Telegram").decode(), "WEBDAV_TARGET_PATH_B64": ""}
        self.assertEqual(config.decode(legacy, "TARGET_PATH"), "Old/Telegram")
        legacy["WEBDAV_TARGET_PATH_B64"] = base64.b64encode(b"New").decode()
        self.assertEqual(config.decode(legacy, "TARGET_PATH"), "New")
        self.assertEqual(config.decode({"WEBDAV_USERNAME_B64": "", "CD2_WEBDAV_USERNAME_B64": base64.b64encode(b"bot-user").decode()}, "USERNAME"), "bot-user")

    def test_accounts_never_reuse_bot_or_admin(self):
        for user in ("admin", "root", "administrator", "guest", "bot-reader", "a:b", "new\nuser", "bad user", "--flag"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                config.username(user, "bot-reader")
        self.assertEqual(config.username("phone-reader", "bot-reader"), "phone-reader")

    def test_password_generation_and_rejection(self):
        for value in (SECRET, "x", "short", "PASSWORD123456789", "symbols!@#$%^&*()[]{}:;=+?", "x" * 128):
            self.assertEqual(config.password(value), value)
        for value in ("", " " + SECRET, SECRET + "\n", SECRET + "\r", "a\tb", "x\x00y", "x\x7fy", "重复" * 20, "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.password(value)
        for _ in range(20):
            generated = config.new_password()
            self.assertEqual(len(generated), 9)
            self.assertRegex(generated, r"^[A-Za-z0-9]{9}$")
            for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]"):
                self.assertRegex(generated, pattern)
            self.assertEqual(config.password(generated), generated)

    def test_real_openssl_salted_slow_hash_and_rotation(self):
        executable = shutil.which("openssl")
        if executable is None and Path("F:/Program Files/Git/usr/bin/openssl.exe").is_file():
            executable = "F:/Program Files/Git/usr/bin/openssl.exe"
        self.assertIsNotNone(executable, "OpenSSL is a prerequisite of this feature test")
        first = config.password_hash(SECRET, executable=executable)
        self.assertRegex(first, config.HASH)
        self.assertNotEqual(first, config.password_hash(SECRET, executable=executable))
        self.assertEqual(first, config.password_hash(SECRET, existing=first, executable=executable))
        with self.assertRaisesRegex(ValueError, "不一致"):
            config.password_hash(SECRET + "-changed", existing=first, executable=executable)
        self.assertNotIn(SECRET, first)
        for value in ("x", config.new_password()):
            hashed = config.password_hash(value, executable=executable)
            self.assertEqual(hashed, config.password_hash(value, existing=hashed, executable=executable))

    def test_atomic_hash_replacement_is_seen_by_directory_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "auth" / "openlist.htpasswd"
            config.atomic(path, b"old-hash", mode=0o640)
            old_inode = path.stat().st_ino
            config.atomic(path, b"new-hash", mode=0o640)
            self.assertEqual(path.read_bytes(), b"new-hash")
            self.assertNotEqual(path.stat().st_ino, old_inode)

    def test_safe_log_redacts_secrets_and_headers(self):
        messages = []
        log = SafeLog(messages.append)
        log.register({"EXTERNAL_PASSWORD": SECRET})
        log("failed: " + SECRET)
        log("Authorization: Basic testfixture")
        self.assertNotIn(SECRET, "\n".join(messages))
        self.assertNotIn("testfixture", "\n".join(messages))


class SharedStateTests(unittest.TestCase):
    def test_v1_unchanged_and_v2_no_downgrade(self):
        self.assertEqual(normalize_state(json.dumps(empty_state())), empty_state())
        self.assertEqual(normalize_state(json.dumps(shared())), shared())
        for data in ({"version": 99, "domains": {}}, {"version": True, "domains": {}}, dict(shared(), future={}), dict(shared(), version=1)):
            with self.assertRaises(ValueError):
                normalize_state(json.dumps(data))

    def test_unknown_owner_auth_scope_or_type_is_rejected(self):
        for field, value in (("owner", "unknown"), ("kind", "management"), ("enabled", "yes"),
                             ("auth_file", "../../passwd"), ("instance_dir", "/opt/../private"), ("backend_port", 80)):
            state = shared()
            state["external_webdav"]["openlist"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_state(json.dumps(state))

    def test_management_reconfigure_and_remove_preserve_addon_and_cert(self):
        state = shared()
        updated = state_with_route(state, PRODUCTS["clouddrive2"], "new-admin.example.test")
        removed = state_without_route(updated, "clouddrive2")
        self.assertEqual(removed["external_webdav"], state["external_webdav"])
        self.assertTrue(has_routes(removed))
        self.assertEqual(certificate_domains(removed), ("openlist-files.example.test",))
        removed["external_webdav"]["openlist"]["enabled"] = False
        self.assertEqual(certificate_domains(removed), ("openlist-files.example.test",))

    def test_management_domain_collision(self):
        with self.assertRaisesRegex(ValueError, "WebDAV"):
            state_with_route(shared(), PRODUCTS["clouddrive2"], route()["domain"])

    def test_generated_config_has_independent_gate_and_preserves_management_block(self):
        files = render_config_set(shared())
        management = files["conf.d/20-clouddrive2.conf"]
        public = files["conf.d/30-external-webdav-openlist.conf"]
        self.assertIn("location = /dav", management)
        self.assertIn("return 403", management)
        for expected in ("auth_basic_user_file /etc/nginx/external-auth/openlist.htpasswd", "proxy_set_header Authorization $http_authorization",
                         "GET|HEAD|OPTIONS|PROPFIND", "return 405", "proxy_buffering off", "proxy_set_header Range $http_range",
                         "location = /dav", "location ^~ /dav/", "location / { return 404", "proxy_hide_header Location",
                         "limit_conn", "rate=2r/s", "client_max_body_size 16k", "access_log off", "proxy_max_temp_file_size 0"):
            self.assertIn(expected, public)
        self.assertNotIn(SECRET, public)
        self.assertIn("./external-auth:/etc/nginx/external-auth:ro", render_compose(certificate_domains(shared()), external_auth=True))
        self.assertNotIn("external-auth", render_compose())

    def test_disabled_route_stays_tls_but_has_no_proxy(self):
        text = nginx.render_route(route(enabled=False))
        self.assertNotIn("proxy_pass", text)
        self.assertIn("return 403", text)
        self.assertIn("listen 443 ssl", text)

    def test_method_guard_runs_before_limit_except_location_selection(self):
        for edition in ("clouddrive2", "openlist"):
            with self.subTest(edition=edition):
                text = nginx.render_route(route(edition))
                tls_server = text.split("listen 443 ssl;", 1)[1]
                server_policy, locations = tls_server.split("location / {", 1)
                self.assertIn("if ($request_method !~ ^(GET|HEAD|OPTIONS|PROPFIND)$) { return 405; }", server_policy)
                self.assertNotIn("if ($request_method", locations)
                self.assertEqual(locations.count("limit_except GET HEAD OPTIONS PROPFIND { deny all; }"), 2)

    def test_uri_guard_rejects_backslashes_without_breaking_regex_alternation(self):
        text = nginx.render_route(route())
        pattern = re.search(r'if \(\$request_uri ~\* "([^"]+)"\)', text).group(1)
        self.assertIn(r"\x5c", pattern)
        for path in (r"/dav/a\b", "/dav/a%5cb", "/dav/a%255Cb", "/dav/a%25255cb", "/dav/a%2fb",
                     "/dav/a%252fb", "/dav/%252e%252e/x", "/dav/a%00b"):
            with self.subTest(path=path):
                self.assertIsNotNone(re.search(pattern, path, re.IGNORECASE))
        for path in ("/dav/中文 video.mp4", "/dav/%E4%B8%AD%E6%96%87%20video.mp4", "/dav/file%25name.mp4"):
            with self.subTest(path=path):
                self.assertIsNone(re.search(pattern, path, re.IGNORECASE))

    def test_last_management_removal_keeps_proxy_alive(self):
        manager = DomainProxyManager(Mock(), PRODUCTS["clouddrive2"], {}, Mock())
        # This isolated proxy has no Compose registry; keep the real ownership probe.
        manager.session.run.return_value = (0, "")
        manager.read_state = Mock(return_value=shared())
        manager._activate = Mock()
        manager._compose = Mock(return_value=(0, ""))
        manager._verify_remaining_routes = Mock()
        manager._commit_state = Mock()
        manager._remove_locked()
        self.assertEqual(manager._activate.call_args.args[0]["domains"], {})
        self.assertTrue(manager._activate.call_args.args[0]["external_webdav"])
        self.assertFalse(any("stop" in call.args[0] for call in manager._compose.call_args_list))

    def test_activation_failure_preserves_other_edition_and_disables_selected(self):
        state = shared()
        state["external_webdav"]["clouddrive2"] = route("clouddrive2")
        manager = DomainProxyManager(Mock(), PRODUCTS["openlist"], {}, Mock())
        manager.read_state = Mock(return_value=state)
        manager._ensure_state_file = Mock()
        manager._activate = Mock(side_effect=[RuntimeError("candidate fails"), None])
        manager._compose = Mock(return_value=(0, ""))
        manager._commit_state = Mock()
        with self.assertRaises(RuntimeError):
            manager.apply_shared_state_locked(state)
        fallback = manager._commit_state.call_args.args[0]
        self.assertFalse(fallback["external_webdav"]["openlist"]["enabled"])
        self.assertTrue(fallback["external_webdav"]["clouddrive2"]["enabled"])

    def test_core_uninstall_refuses_dependent_gateway(self):
        with patch.object(uninstall, "docker_snapshot", return_value=({}, {})), patch.object(uninstall, "read_state", return_value=shared()), self.assertRaisesRegex(uninstall.UninstallError, "WebDAV"):
            uninstall.build_plan(("openlist",), Mock())

    def test_core_uninstall_guides_to_selected_addon_menu(self):
        with (patch.object(uninstall, "docker_snapshot", return_value=({}, {})),
              patch.object(uninstall, "read_state", return_value=shared()),
              self.assertRaisesRegex(uninstall.UninstallError, "15. 外部 WebDAV → 7. 卸载外部 WebDAV") as caught):
            uninstall.build_plan(("openlist",), Mock())
        self.assertNotIn("tg2cloud-webdav uninstall", str(caught.exception))

    def test_schema2_backup_requires_authentication_resources(self):
        with self.assertRaisesRegex(ValueError, "authentication"):
            maintenance.validate_auth_records(shared(), {})
        maintenance.validate_auth_records(shared(), {"proxy/external-auth/openlist.htpasswd": {"kind": "file"}})


class VerificationTests(unittest.TestCase):
    def test_xml_encoding_and_untrusted_href(self):
        self.assertEqual(verification.propfind(XML, route()["domain"]), ("/dav/",))
        for href in ("/dav/%E4%B8%AD%E6%96%87%20file.mp4", "https://openlist-files.example.test/dav/a.mp4"):
            self.assertTrue(verification.propfind(XML.replace(b"/dav/", href.encode()), route()["domain"]))
        for href in ("/davevil/", "/dav/../admin", "/dav/%252e%252e/foo", "http://127.0.0.1/dav/", "https://evil.test/dav/", "/dav/a?token=secret", "/dav/\\foo"):
            with self.subTest(href=href), self.assertRaises(ValueError):
                verification.propfind(XML.replace(b"/dav/", href.encode()), route()["domain"])
        with self.assertRaises(ValueError):
            verification.propfind(b'<!DOCTYPE x [<!ENTITY e "test">]>' + XML, route()["domain"])

    def test_authentication_directory_and_anonymous_denial(self):
        target = dict(route(), username="phone-reader")
        with patch.object(verification, "request", side_effect=[(207, XML, {}), (401, b"", {})]) as request:
            verification.check_backend(target, SECRET)
            self.assertEqual(request.call_args_list[0].kwargs["credentials"], ("phone-reader", SECRET))
        for status in (401, 403, 429, 500, 502):
            with patch.object(verification, "request", return_value=(status, b"", {})), self.assertRaisesRegex(ValueError, str(status)):
                verification.check_backend(target, SECRET)

    def test_real_probe_never_uses_destructive_methods(self):
        for method in ("DELETE", "PUT", "MOVE", "COPY", "LOCK", "PROPPATCH"):
            with self.assertRaises(ValueError):
                verification.request("example.test", 1, method, "/dav/")

    def test_range_sample_is_bounded_and_read_only(self):
        responses = [(200, b"", {"Content-Length": "42"}), (204, b"", {}), (206, b"x", {"Content-Range": "bytes 0-0/42"})]
        with patch.object(verification, "request", side_effect=responses) as request:
            verification.check_media(dict(route(), username="phone-reader"), SECRET, "中文 视频.mp4")
            self.assertEqual([call.args[2] for call in request.call_args_list], ["HEAD", "OPTIONS", "GET"])
            self.assertEqual(request.call_args.kwargs["headers"], {"Range": "bytes=0-0"})
            self.assertIn("%20", request.call_args.args[3])
        for path in ("/absolute", "../file", "a//b", "file?token=x", "file%2fsecret"):
            with self.assertRaises(ValueError):
                verification.check_media({}, SECRET, path)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ui, self.session = Mock(), Mock()
        self.messages = []
        self.service = Service(PRODUCTS["openlist"], self.session, SafeLog(self.messages.append), self.ui,
                               root=Path(self.temp.name).resolve())
        self.service.launcher = Path(self.temp.name).resolve() / "bin/tg2cloud-webdav"
        self.item = {"schema": 1, "owner": config.OWNER, "edition": "openlist", "instance_dir": "/opt/tg2cloud-openlist",
                     "domain": route()["domain"], "username": "phone-reader", "bot_root": "/网盘", "target_dir": "/网盘/Telegram",
                     "binding": config.binding(env()), "phase": "enabled", "scope_verification": "manual-native-readonly",
                     "backend_image": "pinned-test-image", "revision": "a" * 32}
        self.service.record = Mock(return_value=copy.deepcopy(self.item))
        self.service.locked = lambda: nullcontext()
        self.service.preflight = Mock(return_value=(SimpleNamespace(directory=PurePosixPath(self.item["instance_dir"]), config=env(), gateway_image="pinned-test-image"), shared()))
        self.service.manager = Mock()
        self.service.backup = Mock()
        self.service.revoke = Mock()
        self.service.save = Mock()
        self.ui.confirm.return_value = True
        self.ui.ask.return_value = SECRET
        self.real_scope_resolve = scope.resolve
        resolver = patch.object(scope, "resolve", return_value=scope.Root(reason="需首次补充目录"))
        self.scope_resolve = resolver.start()
        self.addCleanup(resolver.stop)
        address = patch.object(scope, "management_address", return_value="https://manage.example.test")
        address.start()
        self.addCleanup(address.stop)

    def test_status_does_not_download_probe_or_ask(self):
        self.service.maintain("status")
        self.service.preflight.assert_not_called()
        self.ui.ask.assert_not_called()
        self.assertNotIn(SECRET, "\n".join(self.messages))

    def test_install_is_idempotent(self):
        prepare = Mock()
        self.service.configure(install_dir=None, install=True, prepare_runtime=prepare)
        prepare.assert_not_called()
        self.service.preflight.assert_not_called()
        self.service.manager.apply_shared_state_locked.assert_not_called()

    def test_disable_revokes_before_shared_activation_and_preserves_other_routes(self):
        events = []
        self.service.revoke.side_effect = lambda: events.append("revoke")
        self.service.manager.apply_shared_state_locked.side_effect = lambda state, **kwargs: events.append("apply")
        self.service.maintain("disable")
        self.assertEqual(events, ["revoke", "apply"])
        state = self.service.manager.apply_shared_state_locked.call_args.args[0]
        self.assertEqual(state["domains"], shared()["domains"])
        self.assertFalse(state["external_webdav"]["openlist"]["enabled"])
        self.session.run.assert_not_called()

    def test_concurrent_revision_change_prevents_mutation(self):
        self.service.record.return_value["revision"] = "b" * 32
        with self.assertRaisesRegex(ValueError, "另一操作"):
            self.service.assert_record(self.item)
        self.service.revoke.assert_not_called()

    def test_directory_drift_cannot_enable_or_expand_scope(self):
        self.service.preflight.return_value[0].config = env("Expanded")
        with self.assertRaisesRegex(ValueError, "范围不自动扩大"):
            self.service.maintain("enable")
        self.service.manager.apply_shared_state_locked.assert_not_called()

    def test_failed_enable_revokes_and_records_repair_not_old_credentials(self):
        self.service.manager.apply_shared_state_locked.side_effect = RuntimeError("activation failed")
        self.service.auth_write = Mock()
        with patch.object(verification, "check_backend"), patch.object(config, "password_hash", return_value="test-hash"), self.assertRaises(RuntimeError):
            self.service.maintain("enable")
        self.assertEqual(self.service.revoke.call_count, 2)
        self.assertEqual(self.service.save.call_args.args[0]["phase"], "needs_repair")

    def configure_fixture(self):
        current = {"value": None}
        self.service.record.side_effect = lambda: copy.deepcopy(current["value"])
        self.service.save.side_effect = lambda item: current.update(value=copy.deepcopy(item))
        self.service.preflight.return_value = (self.service.preflight.return_value[0], empty_state())
        self.ui.ask.side_effect = [route()["domain"], "", "/网盘", "phone-reader", SECRET]
        self.service.auth_write = Mock()
        self.service.verify_mounted_hash = Mock()
        return current

    def test_confirmed_manual_native_account_install_does_not_touch_bot(self):
        current = self.configure_fixture()
        with patch.object(verification, "check_backend") as verify, patch.object(config, "password_hash", return_value="synthetic-hash"):
            self.service.configure(install_dir=None, install=True)
        self.assertEqual(current["value"]["phase"], "enabled")
        self.assertEqual(current["value"]["target_dir"], "/网盘/Telegram")
        self.assertEqual(current["value"]["scope_verification"], "manual-native-readonly")
        self.assertNotIn(SECRET, json.dumps(current["value"]))
        verify.assert_called_once()
        self.assertEqual(self.service.auth_write.call_args.args[0], b"phone-reader:synthetic-hash\n")
        self.session.run.assert_not_called()
        self.assertEqual([call.args for call in self.ui.show_password.call_args_list], [(SECRET,), (SECRET,)])
        self.ui.reveal.assert_not_called()
        self.assertNotIn(SECRET, "\n".join(self.messages))
        self.assertNotIn("EXTERNAL_WEBDAV=OK", "\n".join(self.messages))
        self.assertIn("安装完成，外部 WebDAV 已启用。", self.messages)
        self.assertIn("状态：已启用", self.messages)

    def test_cli_prepares_runtime_before_authentication_or_route_changes(self):
        current = self.configure_fixture()
        events = []
        self.service.revoke.side_effect = lambda: events.append("revoke")
        self.service.auth_write.side_effect = lambda content: events.append("auth")
        self.service.manager.apply_shared_state_locked.side_effect = lambda *args, **kwargs: events.append("route")
        args = SimpleNamespace(action="install", install_dir=None, sample_file="")
        with (patch.object(self.service, "install_runtime", side_effect=lambda *args: events.append("runtime")) as prepare,
              patch.object(cli, "source_identity", return_value={"source": "review-fixture"}),
              patch.object(verification, "check_backend"),
              patch.object(config, "password_hash", return_value="synthetic-hash")):
            cli.perform(self.service, args)
        self.assertEqual(events, ["runtime", "revoke", "auth", "route"])
        self.assertEqual(current["value"]["phase"], "enabled")
        prepare.assert_called_once_with(cli.source_root(), {"source": "review-fixture"})
        self.assertIn("安装完成，外部 WebDAV 已启用。", self.messages)

    def test_runtime_failure_or_interruption_preserves_previous_access_and_can_retry(self):
        for action in ("install", "configure"):
            for failure in (OSError, KeyboardInterrupt):
                with self.subTest(action=action, failure=failure.__name__):
                    current = self.configure_fixture()
                    if action == "configure":
                        current["value"] = copy.deepcopy(self.item)
                    previous = copy.deepcopy(current["value"])
                    self.messages.clear()
                    for mock in (self.service.save, self.service.revoke, self.service.auth_write,
                                 self.service.manager, self.ui.show_password):
                        mock.reset_mock()
                    args = SimpleNamespace(action=action, install_dir=None, sample_file="")
                    with (patch.object(self.service, "install_runtime", side_effect=failure("synthetic interruption")),
                          patch.object(cli, "source_identity", return_value={"source": "review-fixture"}),
                          self.assertRaises(failure)):
                        cli.perform(self.service, args)
                    self.assertEqual(current["value"], previous)
                    self.service.save.assert_not_called()
                    self.service.revoke.assert_not_called()
                    self.service.auth_write.assert_not_called()
                    self.service.manager.apply_shared_state_locked.assert_not_called()
                    self.ui.show_password.assert_not_called()
                    self.assertFalse(any("完成，外部 WebDAV 已启用" in message for message in self.messages))
                    # No pending record was written: the same install/configure
                    # operation can proceed after the code-write error is fixed.
                    self.ui.ask.side_effect = [route()["domain"], "", "/网盘", "phone-reader", SECRET]
                    with (patch.object(self.service, "install_runtime") as prepare,
                          patch.object(cli, "source_identity", return_value={"source": "review-fixture"}),
                          patch.object(verification, "check_backend"),
                          patch.object(config, "password_hash", return_value="synthetic-hash")):
                        cli.perform(self.service, args)
                    prepare.assert_called_once()
                    self.assertEqual(current["value"]["phase"], "enabled")

    def test_backend_failure_after_runtime_preparation_keeps_entry_closed(self):
        current = self.configure_fixture()
        args = SimpleNamespace(action="install", install_dir=None, sample_file="")
        with (patch.object(self.service, "install_runtime") as prepare,
              patch.object(cli, "source_identity", return_value={"source": "review-fixture"}),
              patch.object(verification, "check_backend", side_effect=ValueError("synthetic authentication failure")),
              self.assertRaisesRegex(ValueError, "synthetic authentication failure")):
            cli.perform(self.service, args)
        prepare.assert_called_once()
        self.assertEqual(current["value"]["phase"], "needs_repair")
        self.service.auth_write.assert_not_called()
        self.service.manager.apply_shared_state_locked.assert_not_called()
        self.assertNotIn("安装完成，外部 WebDAV 已启用。", self.messages)

    def test_declining_plan_performs_no_write(self):
        self.configure_fixture()
        self.ui.confirm.return_value = False
        prepare = Mock()
        self.service.configure(install_dir=None, install=True, prepare_runtime=prepare)
        prepare.assert_not_called()
        self.service.save.assert_not_called()
        self.service.revoke.assert_not_called()
        self.service.manager.apply_shared_state_locked.assert_not_called()
        self.ui.show_password.assert_not_called()

    def test_interrupted_manual_account_setup_remains_closed_and_repairable(self):
        current = self.configure_fixture()
        self.ui.show_password.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.service.configure(install_dir=None, install=True)
        self.assertEqual(current["value"]["phase"], "needs_repair")
        self.service.auth_write.assert_not_called()

    def test_actual_scope_and_username_are_used_for_both_editions(self):
        for edition, relative, bot_root, target in (
                ("clouddrive2", "", "/资料/归档", "/资料/归档"),
                ("openlist", "视频/周末", "/媒体 A", "/媒体 A/视频/周末"),
                ("clouddrive2", "Movies", "/", "/Movies")):
            with self.subTest(edition=edition):
                current = self.configure_fixture()
                self.messages.clear()
                self.service.product = PRODUCTS[edition]
                instance = self.service.preflight.return_value[0]
                instance.config = env(relative)
                user = "new-reader-" + edition
                self.ui.ask.side_effect = [route(edition)["domain"], "", bot_root, user, SECRET]
                with patch.object(verification, "check_backend"), patch.object(config, "password_hash", return_value="synthetic-hash"):
                    self.service.configure(install_dir=None, install=True)
                self.assertEqual(current["value"]["bot_root"], bot_root)
                self.assertEqual(current["value"]["target_dir"], target)
                self.assertEqual(current["value"]["username"], user)
                self.assertIn("Bot 保存目录：" + target, self.messages)
                self.assertIn("管理页：https://manage.example.test", self.messages)
                self.assertIn(("base path：" if edition == "openlist" else "根目录：") + target, self.messages)
                self.assertIn("目标目录：" + target, self.messages)
                self.assertIn("用户名：" + user, self.messages)
                self.assertNotIn("/115open/Telegram", "\n".join(self.messages))

    def test_enter_uses_default_external_username_but_preserves_existing_account_both_editions(self):
        for edition in PRODUCTS:
            for existing in (False, True):
                with self.subTest(edition=edition, existing=existing):
                    current = self.configure_fixture()
                    self.service.product = PRODUCTS[edition]
                    instance = self.service.preflight.return_value[0]
                    instance.directory = PurePosixPath(PRODUCTS[edition].install_dir)
                    if existing:
                        saved = copy.deepcopy(self.item)
                        saved.update(edition=edition, instance_dir=str(instance.directory), username="saved-reader")
                        current["value"] = saved
                    self.ui.ask.reset_mock()
                    answers = iter((route(edition)["domain"], "", "/网盘", "", SECRET))
                    self.ui.ask.side_effect = lambda *args, answers=answers, **kwargs: kwargs["validate"](next(answers) or kwargs.get("default", ""))
                    with patch.object(verification, "check_backend"), patch.object(config, "password_hash", return_value="synthetic-hash"):
                        self.service.configure(install_dir=None, install=not existing)
                    expected = "saved-reader" if existing else "tg2-webdav"
                    self.assertEqual(current["value"]["username"], expected)
                    username_prompt = self.ui.ask.call_args_list[3]
                    self.assertEqual(username_prompt.kwargs["default"], expected)
                    self.assertEqual("回车默认 tg2-webdav" in username_prompt.args[0], not existing)
                    self.assertEqual(current["value"]["target_dir"], "/网盘/Telegram")
                    self.session.run.assert_not_called()
                    self.assertNotIn(SECRET, "\n".join(self.messages))
        self.assertEqual(config.username("tg2-webdav", "bot-reader"), "tg2-webdav")
        with self.assertRaises(ValueError):
            config.username("tg2-webdav", "tg2-webdav")

    def test_blank_password_generates_nine_characters_and_short_manual_input_is_kept(self):
        for entered in ("", "short"):
            with self.subTest(generated=not entered):
                current = self.configure_fixture()
                answers = iter((route()["domain"], "", "/网盘", "phone-reader", entered))

                def answer(*args, answers=answers, **kwargs):
                    value = next(answers) or kwargs.get("default", "")
                    return kwargs["validate"](value)

                self.ui.ask.side_effect = answer
                self.ui.show_password.reset_mock()
                with patch.object(verification, "check_backend") as verify, patch.object(config, "password_hash", return_value="synthetic-hash"):
                    self.service.configure(install_dir=None, install=True)
                used = verify.call_args.args[1]
                if entered:
                    self.assertEqual(used, entered)
                else:
                    self.assertRegex(used, r"^[A-Za-z0-9]{9}$")
                self.assertEqual([call.args[0] for call in self.ui.show_password.call_args_list], [used, used])
                self.assertNotIn(used, json.dumps(current["value"]))

    def test_confirmed_root_is_only_reused_for_unchanged_instance_binding(self):
        self.scope_resolve.side_effect = self.real_scope_resolve
        for changed in ("none", "directory", "username", "backend", "instance"):
            with self.subTest(changed=changed):
                instance = SimpleNamespace(directory=PurePosixPath(self.item["instance_dir"]), config=env(), gateway_image="pinned-test-image")
                if changed == "directory":
                    instance.config = env("Other")
                elif changed == "username":
                    instance.config = env(user="other-bot")
                elif changed == "backend":
                    instance.gateway_image = "changed-test-image"
                elif changed == "instance":
                    instance.directory = PurePosixPath("/opt/custom")
                self.service.record.side_effect = None
                self.service.record.return_value = copy.deepcopy(self.item)
                self.service.preflight.return_value = (instance, shared())
                self.ui.ask.reset_mock()
                self.ui.ask.side_effect = ([route()["domain"], "", "phone-reader", SECRET] if changed == "none"
                                           else [route()["domain"], "", "/confirmed", "phone-reader", SECRET])
                self.ui.confirm.return_value = False
                with patch.object(scope, "openlist_root", side_effect=ValueError("unsupported")):
                    self.service.configure(install_dir=None)
                prompts = [call.args[0] for call in self.ui.ask.call_args_list]
                self.assertEqual(any("仅首次补充" in prompt for prompt in prompts), changed != "none")
                self.assertFalse(any("完整路径以确认" in prompt for prompt in prompts))
                self.service.save.assert_not_called()

    def test_automatically_resolved_root_needs_no_path_input_and_is_confirmed_in_plan(self):
        current = self.configure_fixture()
        self.scope_resolve.return_value = scope.Root("/媒体/家庭", "网关账号配置")
        self.ui.ask.side_effect = [route()["domain"], "", "phone-reader", SECRET]
        with patch.object(verification, "check_backend"), patch.object(config, "password_hash", return_value="synthetic-hash"):
            self.service.configure(install_dir=None, install=True)
        self.assertEqual(self.ui.ask.call_count, 4)
        self.assertEqual(current["value"]["target_dir"], "/媒体/家庭/Telegram")
        self.assertIn("Bot 保存目录：/媒体/家庭/Telegram", self.messages)
        self.assertIn("根目录：/媒体/家庭/Telegram" if not self.service.product.is_openlist
                      else "base path：/媒体/家庭/Telegram", self.messages)
        prompts = [call.args[0] for call in self.ui.confirm.call_args_list]
        self.assertIn("确认继续？", prompts)
        self.assertIn("已完成以上账号和权限设置？", prompts)

    def test_unsafe_bot_subdirectory_is_rejected_before_write_or_secret_display(self):
        for relative in ("../outside", "a//b", "a\\b", "a\nb"):
            with self.subTest(relative=relative):
                self.configure_fixture()
                self.service.preflight.return_value[0].config = env(relative)
                self.ui.ask.side_effect = [route()["domain"], ""]
                with self.assertRaises(ValueError):
                    self.service.configure(install_dir=None, install=True)
                self.service.save.assert_not_called()
                self.ui.show_password.assert_not_called()

    def test_phone_config_later_never_recovers_or_displays_a_password(self):
        self.service.maintain("print-config")
        self.ui.show_password.assert_not_called()
        self.assertNotIn(SECRET, "\n".join(self.messages))
        self.assertIn("密码（未保存明文）：使用你设置的外部专用密码", self.messages)

    def test_secret_in_backend_error_is_still_redacted_and_entry_stays_closed(self):
        current = self.configure_fixture()
        with (patch.object(verification, "check_backend", side_effect=ValueError("failed " + SECRET)),
              self.assertRaises(ValueError) as error):
            self.service.configure(install_dir=None, install=True)
        self.service.log(str(error.exception))
        self.assertNotIn(SECRET, "\n".join(self.messages))
        self.assertEqual(current["value"]["phase"], "needs_repair")
        self.service.auth_write.assert_not_called()
        self.service.manager.apply_shared_state_locked.assert_not_called()

    def test_declining_native_scope_confirmation_never_publishes(self):
        current = self.configure_fixture()
        self.ui.confirm.side_effect = [True, False]
        with patch.object(verification, "check_backend") as verify, self.assertRaisesRegex(ValueError, "未完成"):
            self.service.configure(install_dir=None, install=True)
        verify.assert_not_called()
        self.assertEqual(current["value"]["phase"], "needs_repair")
        self.service.auth_write.assert_not_called()

    def test_independent_uninstall_removes_only_owned_route(self):
        self.service.auth = Path(self.temp.name) / "owned.htpasswd"
        self.service.auth.write_bytes(b"synthetic-hash")
        self.service.directory.mkdir()
        self.service.record_path.write_text("synthetic-record")
        self.service.maintain("uninstall")
        updated = self.service.manager.apply_shared_state_locked.call_args.args[0]
        self.assertEqual(updated["domains"], shared()["domains"])
        self.assertEqual(updated["external_webdav"], {})
        self.assertFalse(self.service.auth.exists())
        self.assertFalse(self.service.record_path.exists())
        self.session.run.assert_not_called()


class EntryAndReleaseTests(unittest.TestCase):
    def test_unified_management_hints_do_not_require_the_compatibility_command(self):
        messages = []
        service = SimpleNamespace(log=messages.append)
        for check in (False, True):
            with patch.dict(os.environ, {"TG2CLOUD_MANAGER_MENU": "1"}):
                Service.management_hint(service, check=check)
            self.assertIn("\ntg2cloud\n选择 15. 外部 WebDAV", messages[-1])
            self.assertNotIn("tg2cloud-webdav", messages[-1])
            if check:
                self.assertIn("3. 检查连接与配置", messages[-1])
        with patch.dict(os.environ, {"TG2CLOUD_MANAGER_MENU": ""}):
            Service.management_hint(service)
            self.assertIn("tg2cloud-webdav", messages[-1])
            Service.management_hint(service, check=True)
            self.assertIn("tg2cloud-webdav check", messages[-1])

    def test_main_manager_context_skips_edition_choice_and_returns_without_mutation(self):
        service, ui, messages = Mock(), Mock(), []
        service.product, service.ui, service.log = PRODUCTS["openlist"], ui, messages.append
        service.record.return_value = None
        ui.ask.side_effect = lambda *args, **kwargs: kwargs["validate"]("0")
        with (patch.dict(os.environ, {"TG2CLOUD_MANAGER_MENU": "1"}),
              patch("tg2cloud.addons.external_webdav.discovery.host"),
              patch("tg2cloud.addons.external_webdav.service.Service", return_value=service) as factory,
              patch.object(cli, "WebDAVTerminal", return_value=ui), patch.object(cli.signal, "signal"),
              patch("tg2cloud.deployment.host.SafeLog", return_value=SafeLog(messages.append))):
            self.assertEqual(cli.main(["--edition", "openlist", "--install-dir", "/srv/family-openlist"]), 0)
        self.assertEqual(factory.call_args.args[0].key, "openlist")
        self.assertEqual(ui.ask.call_count, 1)
        self.assertIn("0.  返回主菜单", "\n".join(messages))
        self.assertNotIn("请选择存储网关", "\n".join(messages))
        self.assertNotIn("TG2Cloud 外部 WebDAV v", "\n".join(messages))
        self.assertNotIn("当前网关：", "\n".join(messages))
        service.configure.assert_not_called()
        service.install_runtime.assert_not_called()
        service.maintain.assert_not_called()

    def test_enter_defaults_to_first_edition_and_install_or_status_without_mutation(self):
        for installed in (False, True):
            with self.subTest(installed=installed):
                service, ui, messages = Mock(), Mock(), []
                service.record.return_value = {"phase": "enabled"} if installed else None
                service.configure.return_value = False
                values = iter(("1", "2" if installed else "1", "0", "0"))
                ui.ask.side_effect = lambda *args, values=values, **kwargs: kwargs["validate"](next(values))
                service.product, service.ui, service.log = PRODUCTS["clouddrive2"], ui, messages.append
                with (patch("tg2cloud.addons.external_webdav.discovery.host"),
                      patch("tg2cloud.addons.external_webdav.service.Service", return_value=service) as factory,
                      patch.object(cli, "WebDAVTerminal", return_value=ui), patch.object(cli.signal, "signal"),
                      patch("tg2cloud.deployment.host.SafeLog", return_value=SafeLog(messages.append))):
                    self.assertEqual(cli.main([]), 0)
                self.assertEqual(factory.call_args.args[0].key, "clouddrive2")
                gateway, operation = ui.ask.call_args_list[:2]
                self.assertEqual(gateway.args[0], "输入序号（回车默认为 1）")
                self.assertEqual(gateway.kwargs["default"], "1")
                self.assertEqual(operation.kwargs["default"], "2" if installed else "1")
                if installed:
                    service.maintain.assert_called_once_with("status", sample_file="")
                    service.configure.assert_not_called()
                else:
                    service.configure.assert_called_once()
                    options = service.configure.call_args.kwargs
                    self.assertEqual({key: value for key, value in options.items() if key != "prepare_runtime"},
                                     {"install_dir": None, "install": True, "sample_file": ""})
                    self.assertTrue(callable(options["prepare_runtime"]))
                service.install_runtime.assert_not_called()
                menu = next(text for text in messages if "10. 用户管理" in text)
                self.assertTrue(menu.startswith("1.  安装外部 WebDAV\n"))
                self.assertTrue(menu.endswith("0.  退出"))

    def test_real_terminal_enter_uses_default_once_and_label_columns_are_aligned(self):
        ui = cli.WebDAVTerminal.__new__(cli.WebDAVTerminal)
        ui.tty, ui.output = Mock(), io.StringIO()
        ui.read_line = Mock(return_value="\n")
        modes = SimpleNamespace(ECHO=8, TCSANOW=0, tcgetattr=Mock(return_value=[0, 0, 0, 8]), tcsetattr=Mock())
        messages = []
        with patch.dict(sys.modules, {"termios": modes}):
            result = cli.choose(ui, messages.append, "操作", tuple(zip(cli.ACTIONS, cli.ACTION_LABELS)), default="1")
        self.assertEqual(result, "install")
        self.assertEqual(ui.output.getvalue(), "输入序号（回车默认为 1）: ")
        self.assertNotIn("[1]", ui.output.getvalue())
        menu = messages[1].splitlines()
        for line, label in zip(menu, (*cli.ACTION_LABELS, "退出")):
            self.assertFalse(line.startswith(" "))
            self.assertEqual(line.index(label), 4)

    def test_idempotent_or_declined_install_never_replaces_offline_code(self):
        service = Mock()
        service.configure.return_value = False
        service.record.return_value = {"phase": "enabled"}
        service.product = PRODUCTS["openlist"]
        with (patch("tg2cloud.addons.external_webdav.discovery.host"),
              patch("tg2cloud.addons.external_webdav.service.Service", return_value=service),
              patch.object(cli, "WebDAVTerminal"), patch.object(cli.signal, "signal"),
              patch.object(cli, "source_identity", return_value={"source": "local-reviewed-source"}),
              patch("builtins.print")):
            self.assertEqual(cli.main(["install", "--edition", "openlist"]), 0)
        service.install_runtime.assert_not_called()

    def test_numbered_wizard_dispatches_chinese_menu_and_preserves_cli_actions(self):
        for edition, number in (("clouddrive2", "1"), ("openlist", "2")):
            for action, action_number in zip(cli.ACTIONS, map(str, range(1, 10))):
                with self.subTest(edition=edition, action=action):
                    service, ui = Mock(), Mock()
                    service.record.return_value = {"phase": "enabled", "instance_dir": PRODUCTS[edition].install_dir} if action == "upgrade" else None
                    service.configure.return_value = False
                    values = iter((number, action_number, "0", "0"))
                    ui.ask.side_effect = lambda *args, values=values, **kwargs: kwargs["validate"](next(values))
                    ui.confirm.return_value = False
                    messages = []
                    service.product, service.ui, service.log = PRODUCTS[edition], ui, messages.append
                    with (patch("tg2cloud.addons.external_webdav.discovery.host"),
                          patch("tg2cloud.addons.external_webdav.service.Service", return_value=service) as factory,
                          patch.object(cli, "WebDAVTerminal", return_value=ui), patch.object(cli.signal, "signal"),
                          patch("tg2cloud.deployment.host.SafeLog", return_value=SafeLog(messages.append))):
                        self.assertEqual(cli.main([]), 0)
                    self.assertEqual(factory.call_args.args[0].key, edition)
                    text = "\n".join(messages)
                    for label in cli.ACTION_LABELS:
                        self.assertIn(label, text)
                    if action in {"install", "configure"}:
                        self.assertEqual(service.configure.call_args.kwargs["install"], action == "install")
                    elif action != "upgrade":
                        service.maintain.assert_called_once_with(action, sample_file="")
                    ui.close.assert_called_once()

    def test_menu_rejects_invalid_values_and_accepts_legacy_names(self):
        ui, messages = Mock(), []
        ui.ask.side_effect = lambda *args, **kwargs: kwargs["validate"]("not-an-action")
        with self.assertRaises(ValueError):
            cli.choose(ui, messages.append, "操作", tuple(zip(cli.ACTIONS, cli.ACTION_LABELS)))
        for value, result in (("1", "install"), ("print-config", "print-config"), ("0", "")):
            ui.ask.side_effect = lambda *args, value=value, **kwargs: kwargs["validate"](value)
            self.assertEqual(cli.choose(ui, messages.append, "操作", tuple(zip(cli.ACTIONS, cli.ACTION_LABELS))), result)

    def test_exit_menu_does_not_probe_instances_or_mutate(self):
        ui = Mock()
        ui.ask.side_effect = lambda *args, **kwargs: kwargs["validate"]("0")
        with (patch("tg2cloud.addons.external_webdav.discovery.host"),
              patch("tg2cloud.addons.external_webdav.service.Service") as service,
              patch.object(cli, "WebDAVTerminal", return_value=ui), patch.object(cli.signal, "signal"), patch("builtins.print")):
            self.assertEqual(cli.main([]), 0)
        service.assert_not_called()
        ui.close.assert_called_once()

    def test_password_validation_explains_error_without_echoing_input(self):
        ui = cli.WebDAVTerminal.__new__(cli.WebDAVTerminal)
        ui.output = io.StringIO()
        with patch.object(cli.Terminal, "ask", side_effect=["sensitive bad input", "short"]) as ask:
            self.assertEqual(ui.ask("密码", secret=True, validate=config.password), "short")
        self.assertEqual(ask.call_count, 2)
        self.assertIn(config.INPUT_ERROR, ui.output.getvalue())
        self.assertNotIn("sensitive bad input", ui.output.getvalue())

    def test_password_display_is_private_terminal_only_not_logger_or_confirmation(self):
        ui = cli.WebDAVTerminal.__new__(cli.WebDAVTerminal)
        ui.output = io.StringIO()
        ui.confirm = Mock()
        with self.assertRaisesRegex(RuntimeError, "私有终端"):
            ui.show_password(SECRET)
        self.assertEqual(ui.output.getvalue(), "")
        ui.output.isatty = lambda: True
        with patch("builtins.print") as printed:
            ui.show_password(SECRET)
        self.assertEqual(ui.output.getvalue(), "密码：" + SECRET + "\n")
        ui.confirm.assert_not_called()
        printed.assert_not_called()

    def test_bootstrap_banner_hides_commit_but_retains_identity(self):
        release = releases.core.Release("v1.4.6", "a" * 40)
        prefix = "https://github.com/jiajiaxd/TG2Cloud/releases/download/v1.4.6/"
        name = "TG2Cloud-v1.4.6-source.tar.gz"
        body = b"synthetic verified archive"
        digest = hashlib.sha256(body).hexdigest()
        metadata = {"draft": False, "prerelease": False, "tag_name": release.tag,
                    "assets": [{"name": value, "browser_download_url": prefix + value} for value in (name, "SHA256SUMS.txt")]}
        client = Mock()
        client.resolve.return_value = release
        client.json.return_value = metadata
        output = io.StringIO()
        with (tempfile.TemporaryDirectory() as private,
              patch.object(releases.core, "ReleaseClient", return_value=client),
              patch.object(releases, "read_asset", side_effect=[(digest + "  " + name + "\n").encode(), body]),
              patch.object(releases.core, "extract_source"), patch.object(releases.core, "source_version", return_value=release.version),
              patch.object(releases, "supported"), patch("sys.stdout", output)):
            _, identity = releases.download(Path(private))
        self.assertEqual(identity, {"source": "stable-release", "tag": release.tag, "commit": release.commit, "archive_sha256": digest})
        self.assertNotIn(release.commit, output.getvalue())

    def test_help_without_site_packages_or_checkout_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-I", "-S", "-B", "-X", "utf8", str(ROOT / "scripts/run_source.py"), "webdav", "--help"],
                                    cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--edition", result.stdout)
        self.assertIn("print-config", result.stdout)

    def test_main_installers_and_bot_do_not_opt_in(self):
        block = re.compile(r"<<'PY'[^\n]*\n(.*?)^PY\s*$", re.MULTILINE | re.DOTALL)
        for name in ("install.sh", "install-lan.sh"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("external_webdav", block.sub("", source))
            self.assertNotIn("install-webdav.sh", source)
            self.assertNotIn("tg2cloud-webdav", source)
            for embedded in block.findall(source):
                tree = ast.parse(embedded)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "files" for target in node.targets):
                        # Downloading shared compatibility modules is not an
                        # activation. Exclude only the literal file allowlist,
                        # never executable statements or imports, from this guard.
                        self.assertTrue(all(isinstance(path, str) for path in ast.literal_eval(node.value)))
                        node.value = ast.Tuple(elts=[], ctx=ast.Load())
                self.assertNotIn("external_webdav", ast.unparse(tree))
        for name in ("src/tg2cloud/cli/vps.py", "src/tg2cloud/app.py"):
            self.assertNotIn("external_webdav", (ROOT / name).read_text(encoding="utf-8"))

    def test_main_dispatch_does_not_call_addon_installer(self):
        from tg2cloud.cli import commands

        for command, target in (("install", "tg2cloud.cli.vps.main"), ("lan", "tg2cloud.deployment.proxy.lan.main")):
            with self.subTest(command=command), patch(target, return_value=0) as operation, patch.object(cli, "main") as addon, patch.object(commands.signal, "signal"):
                self.assertEqual(commands.main([command, "--help"]), 0)
                operation.assert_called_once_with(["--help"])
                addon.assert_not_called()

    def test_stable_contract_and_host_bundle_are_complete(self):
        releases.supported(ROOT)
        files = releases.host_files(ROOT)
        self.assertIn("src/tg2cloud/addons/external_webdav/cli.py", files)
        self.assertIn("src/tg2cloud/deployment/proxy/manager.py", files)
        self.assertNotIn("src/tg2cloud/app.py", files)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "尚不包含"):
            releases.supported(Path(directory))

    def test_unified_contract_requires_management_code_and_rejects_old_or_unknown_entry_layout(self):
        self.assertEqual(releases.contract(ROOT), releases.CONTRACT)
        files = releases.host_files(ROOT)
        self.assertIn("src/tg2cloud/deployment/uninstall.py", files)
        self.assertIn("src/tg2cloud/addons/external_webdav/entry.py", files)
        self.assertNotIn("install-webdav.sh", files)
        self.assertFalse((ROOT / "uninstall.sh").exists())
        self.assertFalse((ROOT / "install-webdav.sh").exists())
        with tempfile.TemporaryDirectory() as private:
            root = Path(private).resolve()
            marker = root / releases.FEATURE
            marker.parent.mkdir()
            for api in (True, 2.0, "2", 999):
                marker.write_text(json.dumps(dict(releases.CONTRACT, api=api)))
                with self.subTest(api=api), self.assertRaisesRegex(ValueError, "不支持"):
                    releases.supported(root)
            marker.write_text(json.dumps(releases.CONTRACT))
            with self.assertRaisesRegex(ValueError, "缺失"):
                releases.supported(root)

    def test_offline_host_bundle_is_self_contained_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(PRODUCTS["openlist"], Mock(), Mock(), Mock(), root=root)
            launcher = root / "bin/tg2cloud-webdav"
            service.install_runtime(ROOT, {"source": "local-reviewed-source"}, launcher=launcher)
            runtime = next((root / "runtime").iterdir())
            self.assertNotIn("app.py", {path.name for path in (runtime / "src/tg2cloud").iterdir()})
            code = ("import sys; sys.path.insert(0," + repr(str(runtime / "src")) + "); "
                    "import tg2cloud.addons.external_webdav.service, tg2cloud.addons.external_webdav.cli; "
                    "assert not any(n.split('.')[0] in {'telethon','cryptg','psutil','PySide6'} for n in sys.modules)")
            result = subprocess.run([sys.executable, "-I", "-S", "-c", code], cwd=root,
                                    capture_output=True, text=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            before = launcher.read_bytes()
            service.install_runtime(ROOT, {"source": "local-reviewed-source"}, launcher=launcher)
            self.assertEqual(launcher.read_bytes(), before)
            nested = runtime / "src/tg2cloud/addons/external_webdav/nginx.py"
            nested.write_bytes(nested.read_bytes() + b"\n# synthetic tamper\n")
            with self.assertRaisesRegex(ValueError, "摘要不匹配"):
                service.install_runtime(ROOT, {"source": "local-reviewed-source"}, launcher=launcher)
            self.assertEqual(launcher.read_bytes(), before)

    def test_release_asset_host_allowlist(self):
        for url in ("http://github.com/a", "https://evil.test/a", "https://user:secret@github.com/a", "https://github.com:444/a"):
            with self.assertRaises(ValueError):
                releases.valid_url(url)
        releases.valid_url("https://github.com/LuoPoJunZi/TG2Cloud/releases/download/v9.0.0/SHA256SUMS.txt")

    def test_hash_not_secret_is_passed_to_openssl_argv(self):
        fake = "$6$rounds=200000$" + "a" * 16 + "$" + "b" * 86
        with patch.object(config.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=fake.encode())) as runner:
            config.password_hash(SECRET)
        self.assertNotIn(SECRET, repr(runner.call_args.args))
        self.assertEqual(runner.call_args.kwargs["input"], SECRET.encode() + b"\n")


class RuntimeInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tg2cloud-runtime-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        files = {name: b"# synthetic host source\n" for name in (
            "scripts/run_source.py", "src/tg2cloud/__init__.py", "src/tg2cloud/version.py",
            "src/tg2cloud/config.py", "src/tg2cloud/cli/__init__.py",
            "src/tg2cloud/cli/commands.py", "src/tg2cloud/cli/management.py", "src/tg2cloud/deployment/uninstall.py",
            "src/tg2cloud/addons/external_webdav/entry.py", "src/tg2cloud/addons/external_webdav/service.py",
            "src/tg2cloud/addons/external_webdav/cli.py")}
        files[releases.FEATURE] = json.dumps(releases.CONTRACT).encode()
        for name, body in files.items():
            path = self.source / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(body)
        self.service = Service(PRODUCTS["openlist"], Mock(), Mock(), Mock(), root=self.root / "addon")
        self.launcher = self.root / "bin/tg2cloud-webdav"
        self.launcher.parent.mkdir(mode=0o700)
        self.old_launcher = b'#!/bin/sh\n# TG2Cloud external_webdav managed\n# previous reviewed runtime\n'
        self.launcher.write_bytes(self.old_launcher)
        checksum = hashlib.sha256()
        for name in releases.host_files(self.source):
            checksum.update(name.encode() + b"\0" + (self.source / name).read_bytes())
        self.destination = self.service.root / "runtime" / checksum.hexdigest()

    def install(self):
        self.service.install_runtime(self.source, {"source": "local-reviewed-source"}, launcher=self.launcher)

    def assert_failure_preserved_runtime(self):
        self.assertEqual(self.launcher.read_bytes(), self.old_launcher)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.glob("stage-*")), [])

    def test_copy_failure_and_normal_interruption_clean_only_current_candidate_and_retry(self):
        for failure in (OSError, KeyboardInterrupt):
            with self.subTest(failure=failure.__name__):
                with patch("tg2cloud.addons.external_webdav.service.shutil.copyfile", side_effect=failure("synthetic copy failure")), self.assertRaises(failure):
                    self.install()
                self.assert_failure_preserved_runtime()
        self.install()
        self.assertTrue(self.destination.is_dir())
        self.assertNotEqual(self.launcher.read_bytes(), self.old_launcher)

    def test_manifest_failure_does_not_leave_candidate_or_replace_launcher(self):
        atomic = config.atomic

        def fail_manifest(path, *args, **kwargs):
            if path.name == "installation.json":
                raise OSError("synthetic manifest failure")
            return atomic(path, *args, **kwargs)

        with patch.object(config, "atomic", side_effect=fail_manifest), self.assertRaises(OSError):
            self.install()
        self.assert_failure_preserved_runtime()
        self.install()
        self.assertTrue(self.destination.is_dir())

    def test_corrupt_copy_is_rejected_before_promotion_and_can_retry(self):
        original = shutil.copyfile

        def corrupt_copy(source, target):
            result = original(source, target)
            target.write_bytes(target.read_bytes() + b"# synthetic corruption\n")
            return result

        with patch("tg2cloud.addons.external_webdav.service.shutil.copyfile", side_effect=corrupt_copy), self.assertRaisesRegex(ValueError, "摘要不匹配"):
            self.install()
        self.assert_failure_preserved_runtime()
        self.install()
        self.assertTrue(self.destination.is_dir())

    def test_failed_promotion_cleans_candidate_and_keeps_previous_launcher(self):
        original = os.replace

        def fail_promotion(source, target):
            if target == self.destination:
                raise OSError("synthetic promotion failure")
            return original(source, target)

        with patch("tg2cloud.addons.external_webdav.service.os.replace", side_effect=fail_promotion), self.assertRaises(OSError):
            self.install()
        self.assert_failure_preserved_runtime()
        self.install()
        self.assertTrue(self.destination.is_dir())

    def test_failed_launcher_write_keeps_old_command_and_retry_reuses_verified_bundle(self):
        atomic = config.atomic

        def fail_launcher(path, *args, **kwargs):
            if path == self.launcher:
                raise OSError("synthetic launcher failure")
            return atomic(path, *args, **kwargs)

        with patch.object(config, "atomic", side_effect=fail_launcher), self.assertRaises(OSError):
            self.install()
        self.assertTrue(self.destination.is_dir())
        self.assertEqual(self.launcher.read_bytes(), self.old_launcher)
        self.assertEqual(list(self.destination.parent.glob("stage-*")), [])
        with patch("tg2cloud.addons.external_webdav.service.shutil.copyfile") as copyfile:
            self.install()
        copyfile.assert_not_called()
        self.assertNotEqual(self.launcher.read_bytes(), self.old_launcher)

    def test_legacy_and_abandoned_candidates_are_preserved_without_blocking_new_install(self):
        self.destination.parent.mkdir(mode=0o700, parents=True)
        legacy = self.destination.with_name("stage-" + self.destination.name)
        abandoned = self.destination.with_name("stage-" + self.destination.name + "-abandoned")
        legacy.mkdir(mode=0o700)
        (legacy / "unknown-file").write_bytes(b"preserve unknown content")
        abandoned.write_bytes(b"preserve unknown file")
        self.install()
        self.assertEqual((legacy / "unknown-file").read_bytes(), b"preserve unknown content")
        self.assertEqual(abandoned.read_bytes(), b"preserve unknown file")
        self.assertTrue(self.destination.is_dir())
        self.assertEqual(set(self.destination.parent.glob("stage-*")), {legacy, abandoned})
