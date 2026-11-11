"""Offline LAN boundaries. Never contacts a NAS, VPS, Docker or cloud account."""

from __future__ import annotations

import ast
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from test_deployment import BASH, bash_path

import tg2cloud.cli.terminal as tgdep_terminal
import tg2cloud.deployment.install as tgdep_install
import tg2cloud.deployment.instances as tgdep_instances
import tg2cloud.deployment.payload as tgdep_payload
import tg2cloud.deployment.preflight as tgdep_preflight
import tg2cloud.deployment.releases as tgdep_releases
import tg2cloud.deployment.upgrade as tgdep_upgrade
from tg2cloud.deployment.host import SafeLog
from tg2cloud.deployment.profiles import PRODUCTS
from tg2cloud.deployment.proxy import lan

ROOT = Path(__file__).resolve().parents[1]
IP = "192.168.26.5"
RELEASE = tgdep_releases.Release("v" + PRODUCTS["clouddrive2"].app_version, "a" * 40)


def interface(address=IP, *, name="eth0", flags=None, prefix=24):
    return {"ifname": name, "flags": flags if flags is not None else ["UP"],
            "addr_info": [{"family": "inet", "local": address, "prefixlen": prefix}]}


def instance(product, *, present=True, version=None):
    return tgdep_instances.Instance(product, Path(product.install_dir), present,
                        version or (product.app_version if present else ""), present,
                        "gateway@sha256:" + "b" * 64 if present else "",
                        {"BOT_TOKEN": "FAKE_OFFLINE_SECRET", "TG2CLOUD_STORAGE_BACKEND": product.key} if present else {},
                        b"BOT_TOKEN=FAKE_OFFLINE_SECRET\n" if present else b"")


def inspected(product, *, running=True):
    directory = lan.LAN_ROOT / product.key
    return {"image": lan.NGINX_IMAGE, "running": running, "network": "host", "readonly": True,
            "privileged": False, "user": "101:101", "entrypoint": ["nginx"], "command": ["-g", "daemon off;"],
            "cap_add": None, "cap_drop": ["ALL"], "security": ["no-new-privileges:true"],
            "tmpfs": {"/tmp": "rw,noexec,nosuid,mode=1777,size=64m"},
            "labels": {"com.tg2cloud.managed": "true", "com.tg2cloud.role": "lan-management",
                       "com.tg2cloud.edition": product.key, "com.docker.compose.project": lan.container_name(product),
                       "com.docker.compose.service": "lan", "com.docker.compose.project.working_dir": str(directory),
                       "com.docker.compose.project.config_files": str(directory / "compose.json")},
            "mounts": [{"Type": "bind", "Source": str(directory / "nginx.conf"),
                        "Destination": "/etc/nginx/nginx.conf", "RW": False}]}


class AddressEnvironmentTests(unittest.TestCase):
    def test_explicit_rfc1918_only_and_no_commands_urls_or_implicit_guess(self):
        for value in (IP, "10.1.2.3", "172.16.0.5", "172.31.255.254"):
            self.assertEqual(lan.validate_ip(value), value)
        for value in ("127.0.0.1", "0.0.0.0", "8.8.8.8", "172.15.0.5", "172.32.0.5", "100.64.0.5",
                      "169.254.1.2", "192.168.026.5", "192.168.26.5:19798", "http://" + IP, "::1",
                      "files.example.test", "" , " " + IP, IP + ";id", None, 3232235525):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lan.validate_ip(value)

    def test_manual_address_must_be_on_enabled_host_interface(self):
        session = Mock()
        session.run.return_value = (0, json.dumps([interface("10.0.0.2"), interface()]))
        self.assertEqual(lan.validate_local_ip(IP, session), IP)
        for item in (interface(name="docker0"), interface(name="br-a1"), interface(name="veth123"),
                     interface(flags=[]), interface("192.168.26.0"), interface("192.168.26.255")):
            session.run.return_value = (0, json.dumps([item]))
            with self.subTest(interface=item), self.assertRaises(ValueError):
                lan.validate_local_ip(item["addr_info"][0]["local"], session)
        session.run.return_value = (1, "")
        with self.assertRaisesRegex(ValueError, "iproute2"):
            lan.validate_local_ip(IP, session)

    def test_invalid_address_is_rejected_before_reading_interfaces(self):
        session = Mock()
        with self.assertRaises(ValueError):
            lan.validate_local_ip("0.0.0.0", session)
        session.run.assert_not_called()

    def test_environment_accepts_absent_or_default_rootful_docker_without_installing(self):
        for responses in ([(0, ""), (1, "")], [(0, ""), (0, ""), (0, '"unix:///var/run/docker.sock"'), (0, '{"os":"linux","arch":"' + lan.architecture.normalize_architecture(lan.architecture.platform.machine()) + '","version":"28.0.0","security":[]}')]):
            session = Mock()
            session.run.side_effect = responses
            with patch.object(tgdep_preflight, "validate_host") as host, patch.dict(os.environ, {}, clear=True):
                lan.validate_environment(session)
            host.assert_called_once()
            self.assertFalse(any("apt" in call.args[0] for call in session.run.call_args_list))

    def test_remote_daemon_compose_injection_missing_tool_rootless_and_nondefault_context_rejected(self):
        native = lan.architecture.normalize_architecture(lan.architecture.platform.machine())
        for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CERT_PATH", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES"):
            session = Mock()
            with self.subTest(variable=name), patch.object(tgdep_preflight, "validate_host"), patch.dict(os.environ, {name: "external"}, clear=True), self.assertRaises(ValueError):
                lan.validate_environment(session)
            session.run.assert_not_called()
        for responses in ([(1, "")], [(0, ""), (0, ""), (0, '"tcp://external:2375"')],
                          [(0, ""), (0, ""), (0, '"unix:///var/run/docker.sock"'), (0, json.dumps({"os": "linux", "arch": native, "version": "28.0.0", "security": ["name=rootless"]}))],
                          [(0, ""), (0, ""), (0, '"unix:///var/run/docker.sock"'), (0, json.dumps({"os": "linux", "arch": native, "version": "27.5.1", "security": []}))]):
            session = Mock()
            session.run.side_effect = responses
            with self.subTest(responses=responses), patch.object(tgdep_preflight, "validate_host"), patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                lan.validate_environment(session)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(self.temp).resolve()
        self.stack.enter_context(patch.object(lan, "LAN_ROOT", self.root / "lan"))
        self.stack.enter_context(patch.object(lan, "HTTPS_STATE", self.root / "domains.json"))
        # Linux CI is not root. Simulate only fixture ownership, retaining real
        # permission bits, path resolution and file IO. Production requires root.
        if os.name == "posix" and os.getuid() != 0:
            real_stat = Path.stat

            def root_fixture_stat(path, *args, **kwargs):
                result = real_stat(path, *args, **kwargs)
                if path.is_relative_to(self.root):
                    fields = list(result)
                    fields[4] = 0
                    return os.stat_result(fields)
                return result

            self.stack.enter_context(patch.object(Path, "stat", root_fixture_stat))

    def test_state_is_separate_canonical_and_round_trips_both_editions(self):
        for product in PRODUCTS.values():
            with self.subTest(edition=product.key):
                self.assertIsNone(lan.load_state(product))
                lan.save_state(product, IP)
                self.assertEqual(lan.load_state(product), lan.state_for(product, IP))
                files = lan.render_files(product, IP)
                self.assertEqual(set(files), lan.FILES)
                for name, content in files.items():
                    self.assertEqual((lan.LAN_ROOT / product.key / name).read_text(), content)
                lan.save_state(product, IP)
                with self.assertRaisesRegex(ValueError, "切换"):
                    lan.save_state(product, "192.168.26.6")
        self.assertEqual({path.name for path in lan.LAN_ROOT.iterdir()}, set(PRODUCTS))

    def test_missing_extra_modified_oversize_or_boolean_schema_fail_without_overwrite(self):
        product = PRODUCTS["clouddrive2"]
        for corruption in ("extra", "missing", "config", "large", "schema"):
            with self.subTest(corruption=corruption):
                lan.save_state(product, IP)
                directory = lan.LAN_ROOT / product.key
                if corruption == "extra":
                    (directory / "custom.txt").write_text("user file")
                elif corruption == "missing":
                    (directory / "compose.json").unlink()
                elif corruption == "config":
                    (directory / "nginx.conf").write_text("user nginx config")
                elif corruption == "large":
                    (directory / "nginx.conf").write_text("a" * (128 * 1024 + 1))
                else:
                    value = lan.state_for(product, IP)
                    value["schema"] = True
                    (directory / "state.json").write_text(json.dumps(value))
                before = {path.name: path.read_bytes() for path in directory.iterdir()}
                with self.assertRaises(ValueError):
                    lan.load_state(product)
                with self.assertRaises(ValueError):
                    lan.save_state(product, IP)
                self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})
                shutil.rmtree(directory)  # only this test's private fixture

    def test_other_edition_https_does_not_block_selected_edition_but_selected_does(self):
        self.root.joinpath("domains.json").write_text(json.dumps({"domains": {"openlist": {"domain": "files.example.test"}}}))
        self.root.joinpath("domains.json").chmod(0o600)
        lan.reject_https_route(PRODUCTS["clouddrive2"])
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            lan.reject_https_route(PRODUCTS["openlist"])

    def test_unparseable_https_state_fails_closed(self):
        for content in ('{}', '[]', '{"domains": []}', 'bad json'):
            with self.subTest(content=content):
                lan.HTTPS_STATE.write_text(content)
                lan.HTTPS_STATE.chmod(0o600)
                with self.assertRaises(ValueError):
                    lan.reject_https_route(PRODUCTS["clouddrive2"])

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions")
    def test_private_permissions_and_nonroot_ownership_fail_closed(self):
        product = PRODUCTS["openlist"]
        lan.save_state(product, IP)
        directory = lan.LAN_ROOT / product.key
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((directory / "state.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((directory / "nginx.conf").stat().st_mode & 0o777, 0o644)
        directory.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "700"):
            lan.load_state(product)
        directory.chmod(0o700)
        (directory / "nginx.conf").chmod(0o666)
        with self.assertRaisesRegex(ValueError, "不安全"):
            lan.load_state(product)
        fake = Mock()
        fake.resolve.return_value = fake
        fake.is_symlink.return_value = False
        fake.is_dir.return_value = True
        fake.stat.return_value.st_uid = 1000
        fake.stat.return_value.st_mode = 0o700
        with self.assertRaisesRegex(ValueError, "root"):
            lan.private_directory(fake)

    def test_symlink_is_not_followed_or_deleted(self):
        product = PRODUCTS["openlist"]
        lan.save_state(product, IP)
        target = self.root / "user.txt"
        target.write_text("preserve me")
        path = lan.LAN_ROOT / product.key / "nginx.conf"
        path.unlink()
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks requires OS privileges")
        with self.assertRaisesRegex(ValueError, "链接"):
            lan.load_state(product)
        self.assertEqual(target.read_text(), "preserve me")


class GatewayTests(unittest.TestCase):
    def test_composition_keeps_loopback_backend_and_binds_only_explicit_lan_ip(self):
        for product in PRODUCTS.values():
            with self.subTest(edition=product.key):
                files = lan.render_files(product, IP)
                compose = json.loads(files["compose.json"])["services"]["lan"]
                self.assertEqual(compose["network_mode"], "host")
                self.assertNotIn("ports", compose)
                self.assertEqual(compose["user"], "101:101")
                self.assertTrue(compose["read_only"])
                self.assertEqual(compose["cap_drop"], ["ALL"])
                nginx = files["nginx.conf"]
                self.assertIn(f"listen {IP}:{product.management_port};", nginx)
                self.assertIn(f"proxy_pass http://127.0.0.1:{product.management_port};", nginx)
                self.assertIn("location ~* ^/dav(?:/|$) { return 403; }", nginx)
                self.assertIn("access_log off;", nginx)
                for forbidden in ("listen 80", "listen 443", "0.0.0.0", "ssl_certificate", "certbot"):
                    self.assertNotIn(forbidden, "\n".join(files.values()))
        self.assertNotIn("clouddrive2", lan.container_name(PRODUCTS["clouddrive2"]))

    def test_inspection_requires_exact_managed_identity_mounts_and_sandbox(self):
        for product in PRODUCTS.values():
            session = Mock()
            canonical = inspected(product)
            session.run.return_value = (0, json.dumps(canonical))
            self.assertEqual(lan.inspect_lan(product, session, {lan.container_name(product)}), canonical)
            for key, value in (("image", "other/nginx:latest"), ("network", "bridge"), ("readonly", False),
                               ("privileged", True), ("user", "root"), ("cap_add", ["NET_ADMIN"]),
                               ("cap_drop", []), ("security", []), ("tmpfs", {}), ("labels", {}), ("mounts", [])):
                session.run.return_value = (0, json.dumps({**canonical, key: value}))
                with self.subTest(edition=product.key, altered=key), self.assertRaisesRegex(ValueError, "不接管"):
                    lan.inspect_lan(product, session, {lan.container_name(product)})

    def test_absent_proxy_is_not_inspected_and_inspect_error_fails(self):
        product, session = PRODUCTS["openlist"], Mock()
        self.assertIsNone(lan.inspect_lan(product, session, set()))
        session.run.assert_not_called()
        session.run.return_value = (1, "")
        with self.assertRaises(ValueError):
            lan.inspect_lan(product, session, {lan.container_name(product)})

    def test_fixed_port_conflict_does_not_change_port_or_stop_external_container(self):
        with patch.object(lan.socket, "socket") as socket:
            socket.return_value.__enter__.return_value.bind.side_effect = OSError("in use")
            with self.assertRaisesRegex(ValueError, "更换端口"):
                lan.check_port(PRODUCTS["openlist"], IP, False)
            socket.return_value.__enter__.return_value.bind.assert_called_once_with((IP, 5244))
        with patch.object(lan.socket, "socket") as socket:
            lan.check_port(PRODUCTS["openlist"], IP, True)
            socket.assert_not_called()

    def test_backend_published_address_must_remain_loopback(self):
        for product in PRODUCTS.values():
            item, session = instance(product), Mock()
            port = str(product.management_port)
            session.run.side_effect = [(0, json.dumps({port + "/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]})), (0, "ready")]
            lan.check_backend(item, session, SafeLog(lambda _line: None))
            self.assertIn("manage.sh ready", session.run.call_args.args[0])
            for host in ("0.0.0.0", IP, "::"):
                session.run.side_effect = None
                session.run.return_value = (0, json.dumps({port + "/tcp": [{"HostIp": host, "HostPort": port}]}))
                with self.subTest(host=host), self.assertRaisesRegex(ValueError, "回环"):
                    lan.check_backend(item, session, SafeLog(lambda _line: None))

    def test_nat_only_port_owner_is_checked_before_installation(self):
        for product in PRODUCTS.values():
            session = Mock()
            lan.check_published_ports(product, session, set())
            session.run.assert_not_called()
            session.run.return_value = (0, f"foreign|127.0.0.1:{product.management_port}->{product.management_port}/tcp")
            with self.assertRaisesRegex(ValueError, "其他容器"):
                lan.check_published_ports(product, session, {"foreign"})
            session.run.return_value = (0, f"{product.storage_container}|127.0.0.1:{product.management_port}->{product.management_port}/tcp")
            lan.check_published_ports(product, session, {product.storage_container})
            session.run.return_value = (1, "")
            with self.assertRaisesRegex(ValueError, "无法核对"):
                lan.check_published_ports(product, session, {"foreign"})

    def test_local_management_and_dav_checks_require_our_response_marker(self):
        product = PRODUCTS["clouddrive2"]
        with patch.object(lan, "request_status", side_effect=[(200, product.key), (403, product.key), (403, product.key), (403, product.key)]) as probe:
            lan.check_entry(product, IP)
        self.assertEqual([(call.args[2], call.args[3]) for call in probe.call_args_list],
                         [("/", "GET"), ("/dav", "GET"), ("/dav/", "PROPFIND"), ("/DAV/", "PROPFIND")])
        for response in ((200, ""), (500, product.key), (403, product.key)):
            with patch.object(lan, "request_status", return_value=response), self.assertRaises(ValueError):
                lan.check_entry(product, IP)
        with patch.object(lan, "request_status", side_effect=[(200, product.key), (200, product.key)]), self.assertRaises(ValueError):
            lan.check_entry(product, IP)

    def test_startup_probes_are_bounded_and_never_repeat_writes(self):
        with patch.object(lan, "check_entry", side_effect=[OSError("starting"), None]) as probe, patch.object(lan.time, "sleep") as sleep:
            lan.wait_for_entry(PRODUCTS["openlist"], IP)
            self.assertEqual(probe.call_count, 2)
            sleep.assert_called_once_with(0.5)
        with patch.object(lan, "check_entry", side_effect=ValueError("blocked")), patch.object(lan.time, "monotonic", side_effect=[0, 21]), self.assertRaisesRegex(RuntimeError, "未通过"):
            lan.wait_for_entry(PRODUCTS["openlist"], IP)

    def test_http_probe_does_not_use_environment_proxy_follow_redirects_or_echo_body(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.code = 200
        response.headers.get.return_value = "openlist"
        opener = Mock()
        opener.open.return_value = response
        with patch.object(lan.urllib.request, "build_opener", return_value=opener) as build:
            self.assertEqual(lan.request_status(PRODUCTS["openlist"], IP, "/"), (200, "openlist"))
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], lan.NoRedirect)
        self.assertEqual(opener.open.call_args.args[0].full_url, f"http://{IP}:5244/")
        response.read.assert_not_called()
        self.assertIsNone(lan.NoRedirect().redirect_request(None, None, 302, "", {}, "https://external.test/"))


class PlanExecutionTests(unittest.TestCase):
    def assert_readonly_feedback(self, session, offset=0):
        calls = session.run.call_args_list[offset:]
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[0].args, ("docker exec " + self.product.bot_container + " python -B -m tg2cloud.monitoring.readiness",))
        self.assertEqual(calls[0].kwargs, {"timeout": 20})
        expected = (self.product.bot_container, self.product.storage_container,
                    "tg2cloud-proxy-nginx", "tg2cloud-proxy-certbot")
        for call, name in zip(calls[1:], expected):
            args = shlex.split(call.args[0])
            self.assertEqual(args[:4], ["docker", "container", "inspect", "--format"])
            self.assertEqual(len(args), 6)
            self.assertEqual(args[-1], name)
            self.assertEqual(call.kwargs, {"timeout": 10})
            self.assertNotIn(".Config.Env", args[4])
            self.assertNotIn(".Config.Cmd", args[4])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.messages = []
        self.log = SafeLog(self.messages.append)
        self.product = PRODUCTS["clouddrive2"]
        self.instance = instance(self.product)
        self.patches = {}
        self.stack.enter_context(patch.object(lan, "validate_environment"))
        self.stack.enter_context(patch.object(lan.architecture, "ensure_image"))
        self.stack.enter_context(patch.object(lan.architecture, "check_container"))
        mocks = {"load_state": lan.state_for(self.product, IP), "reject_https_route": None,
                 "validate_local_ip": IP, "inspect_lan": None, "check_port": None,
                 "check_backend": None, "check_entry": None, "wait_for_entry": None, "save_state": None}
        for name, value in mocks.items():
            self.patches[name] = self.stack.enter_context(patch.object(lan, name, return_value=value))
        targets = {"assert_unmodified": tgdep_upgrade, "payload_sources": tgdep_payload,
                   "check_foreign_gateway": tgdep_instances, "resource_check": tgdep_preflight,
                   "show_credentials": tgdep_terminal, "verify_destination": tgdep_install}
        for name, target in targets.items():
            self.patches[name] = self.stack.enter_context(patch.object(target, name))
        self.patches["docker_inventory"] = self.stack.enter_context(patch.object(tgdep_instances, "docker_inventory", return_value=set()))
        self.patches["gateway_image"] = self.stack.enter_context(patch.object(tgdep_payload, "gateway_image", return_value=self.instance.gateway_image))
        self.patches["choose_storage"] = self.stack.enter_context(patch.object(tgdep_preflight, "choose_storage", return_value=("8", "8")))

    def plan(self, **kwargs):
        return lan.make_plan(self.instance, RELEASE, ROOT, ROOT, Mock(), self.log, **kwargs)

    def test_existing_nonlan_instance_is_never_converted(self):
        self.patches["load_state"].return_value = None
        with self.assertRaisesRegex(ValueError, "不转换"):
            self.plan()
        self.patches["assert_unmodified"].assert_not_called()

    def test_https_legacy_partial_or_modified_instance_is_not_auto_fixed(self):
        self.patches["reject_https_route"].side_effect = ValueError("已有 HTTPS")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            self.plan()
        self.patches["reject_https_route"].side_effect = None
        self.patches["assert_unmodified"].side_effect = ValueError("手改程序")
        with self.assertRaisesRegex(ValueError, "手改"):
            self.plan()
        self.patches["save_state"].assert_not_called()

    def test_upgrade_preserves_raw_config_and_saved_address_without_prompt(self):
        self.instance.version = "1.1.4"
        ui = Mock()
        plan = self.plan(ui=ui)
        self.assertEqual(plan.action, "upgrade")
        self.assertEqual(plan.address, IP)
        self.assertEqual(plan.config, self.instance.config)
        self.patches["choose_storage"].assert_not_called()
        ui.ask.assert_not_called()
        self.patches["resource_check"].assert_called_once()
        with self.assertRaisesRegex(ValueError, "切换"):
            self.plan(address="192.168.26.6")
        self.patches["save_state"].assert_not_called()

    def test_gateway_digest_migration_is_not_silently_applied(self):
        self.instance.version = "1.1.4"
        self.patches["gateway_image"].return_value = "different@sha256:" + "c" * 64
        with self.assertRaisesRegex(ValueError, "人工迁移"):
            self.plan()

    def test_final_capacity_loss_does_not_save_lan_state_or_deploy(self):
        self.instance.version = "1.1.4"
        plan = self.plan()
        self.patches["resource_check"].side_effect = ValueError("资源不足")
        with patch.object(lan, "edition_lock", return_value=nullcontext()), patch.object(tgdep_instances, "discover", return_value=self.instance), patch.object(tgdep_install, "apply_base") as apply, self.assertRaisesRegex(ValueError, "资源不足"):
            lan.execute(plan, RELEASE, ROOT, ROOT, Mock(), self.log, Mock())
        apply.assert_not_called()
        self.patches["save_state"].assert_not_called()

    def test_new_install_needs_explicit_ip_and_collects_no_secrets_on_check(self):
        self.instance = instance(self.product, present=False)
        self.patches["load_state"].return_value = None
        with self.assertRaisesRegex(ValueError, "--lan-ip"):
            self.plan()
        with patch.object(tgdep_terminal, "collect_config") as collect:
            plan = self.plan(address=IP)
        collect.assert_not_called()
        self.assertEqual(plan.action, "install")
        self.assertEqual(plan.config, {})
        self.patches["resource_check"].assert_called_once()
        self.patches["check_port"].assert_any_call(self.product, "127.0.0.1", False)
        self.patches["save_state"].assert_not_called()

    def test_manual_ip_preflight_precedes_credentials_and_default_install_confirmation(self):
        self.instance = instance(self.product, present=False)
        self.patches["load_state"].return_value = None
        ui = Mock()
        ui.ask.return_value = IP
        with patch.object(tgdep_terminal, "collect_config", return_value={"BOT_TOKEN": "FAKE_OFFLINE_SECRET"}) as collect:
            plan = self.plan(ui=ui)
        ui.ask.assert_called_once()
        collect.assert_called_once()
        self.assertEqual(collect.call_args.kwargs, {"storage": ("8", "8")})
        self.assertEqual(plan.address, IP)
        self.patches["validate_local_ip"].side_effect = ValueError("not local")
        with patch.object(tgdep_terminal, "collect_config") as collect, self.assertRaises(ValueError):
            self.plan(ui=ui)
        collect.assert_not_called()

    def test_orphan_proxy_is_not_adopted_for_new_install(self):
        self.instance = instance(self.product, present=False)
        self.patches["load_state"].return_value = None
        self.patches["inspect_lan"].return_value = inspected(self.product)
        with self.assertRaisesRegex(ValueError, "不接管"):
            self.plan(address=IP)

    def test_current_newer_and_broken_entry_plans_do_not_rebuild_before_confirmation(self):
        self.patches["inspect_lan"].return_value = inspected(self.product)
        self.assertTrue(self.plan().entry_healthy)
        self.instance.version = f"{int(self.product.app_version.split('.')[0]) + 1}.0.0"
        self.assertEqual(self.plan().action, "newer")
        self.patches["check_entry"].side_effect = OSError("refused")
        self.assertFalse(self.plan().entry_healthy)
        self.patches["save_state"].assert_not_called()

    def execute_fixture(self, plan, *, current=None, session=None):
        session = session or Mock(run=Mock(return_value=(0, "")))
        current = current or self.instance
        self.patches["load_state"].return_value = plan.saved
        self.patches["inspect_lan"].side_effect = [None, inspected(self.product)]
        self.stack.enter_context(patch.object(lan, "edition_lock", return_value=nullcontext()))
        self.discover = self.stack.enter_context(patch.object(tgdep_instances, "discover", return_value=current))
        apply = self.stack.enter_context(patch.object(tgdep_install, "apply_base"))
        return session, apply

    def test_execute_resumes_only_owned_entry_after_base_and_never_modifies_https(self):
        plan = self.plan()
        session, apply = self.execute_fixture(plan)
        lan.execute(plan, RELEASE, ROOT, ROOT, session, self.log, Mock())
        apply.assert_called_once_with(plan, RELEASE, ROOT, session, self.log)
        self.assertTrue(all(call.kwargs.get("install_dir") == self.product.install_dir for call in self.discover.call_args_list))
        self.patches["save_state"].assert_called_once_with(self.product, IP)
        self.patches["wait_for_entry"].assert_called_once()
        commands = [call.args[0] for call in session.run.call_args_list]
        self.assertEqual(len(commands), 9)
        self.assertIn("run --rm --no-deps lan -t", commands[2])
        self.assertTrue(all("compose.json" in command for command in commands[:4]))
        self.assert_readonly_feedback(session, offset=4)
        self.assertFalse(any("certbot" in command or "tg2cloud-proxy" in command for command in commands[:4]))
        self.patches["verify_destination"].assert_not_called()
        self.assertIn("HTTPS=NOT_APPLICABLE", "\n".join(self.messages))

    def test_confirmed_config_or_state_race_stops_before_writing(self):
        for kind in ("config", "state"):
            with self.subTest(kind=kind):
                plan = self.plan()
                current = instance(self.product)
                if kind == "config":
                    current.raw_config = b"changed"
                session, apply = self.execute_fixture(plan, current=current)
                if kind == "state":
                    self.patches["load_state"].return_value = {"changed": True}
                with self.assertRaisesRegex(ValueError, "变化"):
                    lan.execute(plan, RELEASE, ROOT, ROOT, session, self.log, Mock())
                apply.assert_not_called()
                self.patches["save_state"].assert_not_called()

    def test_proxy_failure_keeps_mode_record_and_never_claims_success(self):
        plan = self.plan()
        session, apply = self.execute_fixture(plan, session=Mock(run=Mock(return_value=(1, "failed"))))
        with self.assertRaisesRegex(RuntimeError, "保留"):
            lan.execute(plan, RELEASE, ROOT, ROOT, session, self.log, Mock())
        apply.assert_called_once()
        self.patches["save_state"].assert_called_once()
        self.assertNotIn("TG2CLOUD_LAN_BASE=OK", "\n".join(self.messages))
        self.patches["verify_destination"].assert_not_called()

    def test_healthy_entry_revalidated_without_restart_and_verify_requires_explicit_flow(self):
        plan = self.plan()
        plan.entry_healthy = True
        session, apply = self.execute_fixture(plan)
        self.patches["inspect_lan"].side_effect = None
        self.patches["inspect_lan"].return_value = inspected(self.product)
        lan.execute(plan, RELEASE, ROOT, ROOT, session, self.log, Mock(), verify=True)
        self.assert_readonly_feedback(session)
        self.patches["show_credentials"].assert_not_called()
        self.patches["verify_destination"].assert_called_once()
        apply.assert_called_once()

    def test_management_url_is_shown_before_credentials_and_verify_for_both_editions(self):
        for product in PRODUCTS.values():
            for action in ("install", "current"):
                with self.subTest(edition=product.key, action=action):
                    self.product = product
                    before = instance(product, present=action != "install")
                    after = instance(product)
                    saved = lan.state_for(product, IP) if before.present else None
                    plan = lan.Plan(before, action, IP, saved, dict(after.config))
                    session, _apply = self.execute_fixture(plan, current=before)
                    self.discover.side_effect = [before, after]
                    self.messages.clear()
                    url_line = f"{product.display_name} 内网管理页：http://{IP}:{product.management_port}"

                    def show_credentials(*_args, expected_url=url_line):
                        self.assertIn(expected_url, self.messages)
                        self.messages.append("OFFLINE_CREDENTIALS_PROMPT")

                    def verify(*_args, expected_url=url_line):
                        self.assertIn(expected_url, self.messages)
                        self.assertIn("OFFLINE_CREDENTIALS_PROMPT", self.messages)
                        self.messages.append("OFFLINE_VERIFY_PROMPT")

                    self.patches["show_credentials"].side_effect = show_credentials
                    self.patches["verify_destination"].side_effect = verify
                    lan.execute(plan, RELEASE, ROOT, ROOT, session, self.log, Mock(), verify=action == "current")
                    self.assertLess(self.messages.index(url_line), self.messages.index("OFFLINE_VERIFY_PROMPT"))
                    self.assertIn("完成后再确认写入验收", "\n".join(self.messages))
                    self.assertNotIn("FAKE_OFFLINE_SECRET", "\n".join(self.messages))


class MainBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.product = PRODUCTS["openlist"]
        self.instance = instance(self.product)
        self.plan = lan.Plan(self.instance, "current", IP, lan.state_for(self.product, IP), dict(self.instance.config), True, True)
        self.messages = []
        self.log = SafeLog(self.messages.append)
        self.ui = Mock(confirm=Mock(return_value=False))
        self.stack.enter_context(patch.object(lan, "validate_environment"))
        self.stack.enter_context(patch.object(tgdep_instances, "docker_inventory", return_value=set()))
        self.stack.enter_context(patch.object(tgdep_instances, "discover", return_value=self.instance))
        self.stack.enter_context(patch.object(lan, "load_state", return_value=self.plan.saved))
        self.stack.enter_context(patch.object(lan, "SafeLog", return_value=self.log))
        client = Mock(resolve=Mock(return_value=RELEASE), download=Mock(return_value=ROOT))
        self.client = self.stack.enter_context(patch.object(tgdep_releases, "ReleaseClient", return_value=client))
        self.terminal = self.stack.enter_context(patch.object(tgdep_terminal, "Terminal", return_value=self.ui))
        self.stack.enter_context(patch.object(lan, "make_plan", return_value=self.plan))
        self.execute = self.stack.enter_context(patch.object(lan, "execute"))

    def test_check_does_not_open_terminal_write_config_or_apply(self):
        self.assertEqual(lan.main(["--edition", "openlist", "--check"]), 0)
        self.terminal.assert_not_called()
        self.execute.assert_not_called()
        self.assertIn("TG2CLOUD_LAN_CHECK=OK", "\n".join(self.messages))

    def test_check_fails_if_existing_entry_is_unhealthy_instead_of_claiming_pass(self):
        self.plan.entry_healthy = False
        self.assertEqual(lan.main(["--edition", "openlist", "--check"]), 1)
        self.execute.assert_not_called()
        self.assertNotIn("TG2CLOUD_LAN_CHECK=OK", "\n".join(self.messages))

    def test_check_rejects_verify_or_credentials_before_environment(self):
        for extra in ("--verify", "--show-credentials"):
            with self.subTest(extra=extra):
                self.assertEqual(lan.main(["--edition", "openlist", "--check", extra]), 1)
        self.execute.assert_not_called()
        self.client.assert_not_called()
        self.terminal.assert_not_called()

    def test_current_and_newer_do_not_install_or_restart(self):
        for action in ("current", "newer"):
            self.plan.action = action
            with self.subTest(action=action):
                self.assertEqual(lan.main(["--edition", "openlist"]), 0)
        self.execute.assert_not_called()
        self.ui.confirm.assert_not_called()

    def test_default_confirmation_declines_and_closes_terminal(self):
        self.plan.action = "upgrade"
        self.assertEqual(lan.main(["--edition", "openlist"]), 0)
        self.execute.assert_not_called()
        self.ui.confirm.assert_called_once()
        self.ui.close.assert_called_once()
        self.assertIn("CANCELLED", "\n".join(self.messages))

    def test_confirmation_yes_runs_only_the_selected_edition(self):
        self.plan.action = "upgrade"
        self.ui.confirm.return_value = True
        self.assertEqual(lan.main(["--edition", "openlist"]), 0)
        self.execute.assert_called_once()
        self.assertEqual(self.execute.call_args.args[0].instance.product.key, "openlist")

    def test_credentials_view_never_resolves_release_or_installs(self):
        with patch.object(lan, "reject_https_route"), patch.object(tgdep_terminal, "show_credentials") as show:
            self.assertEqual(lan.main(["--edition", "openlist", "--show-credentials"]), 0)
        show.assert_called_once()
        self.client.assert_not_called()
        self.execute.assert_not_called()

    def test_errors_redact_registered_credentials_and_interrupt_does_not_claim_rollback(self):
        self.log.register(self.instance.config)
        self.plan.action = "upgrade"
        self.ui.confirm.return_value = True
        self.execute.side_effect = RuntimeError("FAKE_OFFLINE_SECRET")
        self.assertEqual(lan.main(["--edition", "openlist"]), 1)
        self.assertNotIn("FAKE_OFFLINE_SECRET", "\n".join(self.messages))
        self.execute.side_effect = KeyboardInterrupt
        self.assertEqual(lan.main(["--edition", "openlist"]), 130)
        self.assertIn("不假定已恢复", "\n".join(self.messages))

    def test_standalone_bootstrap_is_stdlib_immutable_and_fail_closed(self):
        content = (ROOT / "install-lan.sh").read_text(encoding="utf-8")
        self.assertRegex(content, r'(?m)^installer_commit="[0-9a-f]{40}"$')
        self.assertIn('if [[ ! "$installer_commit" =~ ^[0-9a-f]{40}$ ]]; then', content)
        embedded = content.split("<<'PY' &\n", 1)[1].split("\nPY\n", 1)[0]
        ast.parse(embedded)
        self.assertNotIn("/main/", embedded)
        self.assertIn("'src/tg2cloud/deployment/proxy/lan.py'", embedded)
        self.assertIn("trap cancel INT TERM HUP", content)

    def test_bootstrap_downloads_exact_pin_and_bounded_allowlisted_sources(self):
        from payload_fixture import historical_file

        content = (ROOT / "install-lan.sh").read_text(encoding="utf-8")
        embedded = content.split("<<'PY' &\n", 1)[1].split("\nPY\n", 1)[0]
        pin = re.search(r'^installer_commit="([0-9a-f]{40})"$', content, re.MULTILINE)[1]
        urls = []

        def fetch(request, *, timeout):
            self.assertEqual(timeout, 30)
            urls.append(request.full_url)
            prefix = "https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/" + pin + "/"
            self.assertTrue(request.full_url.startswith(prefix))
            return io.BytesIO(historical_file(pin, request.full_url.removeprefix(prefix)))

        with tempfile.TemporaryDirectory() as private, patch("sys.argv", ["bootstrap", private, pin]), patch("sys.stdout", io.StringIO()), patch("urllib.request.build_opener", return_value=Mock(open=Mock(side_effect=fetch))):
            exec(compile(embedded, "LAN bootstrap", "exec"), {})  # noqa: S102 - repo-owned code, mocked networking
            self.assertTrue((Path(private) / "src/tg2cloud/deployment/proxy/lan.py").is_file())
        helpers = json.loads(historical_file(pin, "packaging/bootstrap-manifest.json"))["files"]
        self.assertEqual({url.rsplit(pin + "/", 1)[1] for url in urls}, set(helpers))
        self.assertEqual(len(urls), len(helpers))

    def test_bootstrap_rejects_failed_or_oversized_downloads_without_fallback(self):
        content = (ROOT / "install-lan.sh").read_text(encoding="utf-8")
        embedded = content.split("<<'PY' &\n", 1)[1].split("\nPY\n", 1)[0]
        for error in (OSError("FAKE_DOWNLOAD_SECRET"), None):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as private:
                opener = Mock()
                if error:
                    opener.open.side_effect = error
                else:
                    opener.open.return_value = io.BytesIO(b"x" * (2 * 1024 * 1024 + 1))
                errors = io.StringIO()
                with patch("sys.argv", ["bootstrap", private, "b" * 40]), patch("sys.stderr", errors), patch("urllib.request.build_opener", return_value=opener), self.assertRaises(SystemExit) as stopped:
                    exec(compile(embedded, "LAN bootstrap", "exec"), {})  # noqa: S102 - repo-owned code, mocked networking
                self.assertEqual(stopped.exception.code, 2)
                self.assertEqual(opener.open.call_count, 1)
                self.assertNotIn("FAKE_DOWNLOAD_SECRET", errors.getvalue())
                self.assertFalse((Path(private) / "src/tg2cloud/deployment/proxy/lan.py").exists())

    @unittest.skipUnless(os.name == "posix", "Linux process substitution and bootstrap cleanup")
    def test_process_substitution_forwards_arguments_exit_and_cleans_own_directory(self):
        content = (ROOT / "install-lan.sh").read_text(encoding="utf-8")
        # This test uses a fixed offline pin even before the reviewed online pin
        # is enabled; python3 is a shell fixture, never a real installer.
        content = re.sub(r'^installer_commit="[0-9a-f]*"$', 'installer_commit="' + "b" * 40 + '"', content, flags=re.MULTILINE)
        for bootstrap_exit, cli_exit in ((0, 0), (0, 7), (9, 0)):
            with self.subTest(bootstrap_exit=bootstrap_exit, cli_exit=cli_exit), tempfile.TemporaryDirectory() as private:
                command = r'''
python3() {
  if [[ "$1" == -c ]]; then return 0; fi
  if [[ "$1" == - ]]; then
    cat >/dev/null
    printf '%s\n' "$2" > "$FIXTURE_DIR/bootstrap-path"
    return "$FIXTURE_BOOTSTRAP_EXIT"
  fi
  printf '%s\n' "$@" > "$FIXTURE_DIR/cli-args"
  return "$FIXTURE_CLI_EXIT"
}
export -f python3
'''
                command += "bash <(printf %s " + shlex.quote(content) + ") --edition clouddrive2 --lan-ip " + IP + " --check"
                env = {**os.environ, "FIXTURE_DIR": private, "FIXTURE_BOOTSTRAP_EXIT": str(bootstrap_exit), "FIXTURE_CLI_EXIT": str(cli_exit)}
                result = subprocess.run(["bash", "-c", command], cwd=private, env=env, capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, bootstrap_exit or cli_exit, result.stderr)
                fixture = Path(private)
                self.assertFalse(Path((fixture / "bootstrap-path").read_text().strip()).exists())
                if bootstrap_exit:
                    self.assertFalse((fixture / "cli-args").exists())
                else:
                    self.assertEqual((fixture / "cli-args").read_text().splitlines(), ["-B", "scripts/run_source.py", "lan", "--edition", "clouddrive2", "--lan-ip", IP, "--check"])

    @unittest.skipUnless(BASH, "Bash unavailable")
    def test_local_lan_entry_from_another_working_directory_forwards_arguments_and_exit(self):
        for code in (0, 7):
            with self.subTest(code=code), tempfile.TemporaryDirectory(prefix="tg2cloud lan shell ") as private:
                directory = Path(private).resolve()
                tools = directory / "bin"
                tools.mkdir()
                python = tools / "python3"
                python.write_text('#!/usr/bin/env bash\nif [[ "$1" == -c ]]; then exit 0; fi\nprintf "%s\\n" "$@" > "$FIXTURE_ARGS"\nexit "$FIXTURE_EXIT"\n',
                                  encoding="utf-8", newline="\n")
                python.chmod(0o700)
                arguments = ["--edition", "openlist", "--lan-ip", IP, "--check"]
                command = "PATH=" + shlex.quote(bash_path(tools)) + ':"$PATH" bash ' + shlex.quote(bash_path(ROOT / "install-lan.sh"))
                command += " " + " ".join(map(shlex.quote, arguments))
                output = directory / "arguments"
                result = subprocess.run([BASH, "-c", command], cwd=directory,
                                        env={**os.environ, "FIXTURE_ARGS": bash_path(output), "FIXTURE_EXIT": str(code)},
                                        capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(output.read_text(encoding="utf-8").splitlines(),
                                 ["-B", bash_path(ROOT / "scripts/run_source.py"), "lan", *arguments])

    def test_lan_entry_imports_only_public_linux_helpers(self):
        tree = ast.parse((ROOT / "src/tg2cloud/deployment/proxy/lan.py").read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertIn("tg2cloud.deployment.profiles", imports)
        self.assertIn("tg2cloud.deployment.proxy.manager", imports)
        self.assertNotIn("tg2cloud.cli.vps", imports)
        self.assertFalse(any(name.startswith(("legacy", "PySide6", "paramiko")) for name in imports))

    def test_help_and_shell_syntax_do_not_require_qt_root_or_docker(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/run_source.py"), "lan", "--help"], cwd=ROOT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--lan-ip", result.stdout)
        bash = shutil.which("bash")
        if not bash and os.name == "nt":
            git = shutil.which("git")
            bash = str(Path(git).parents[1] / "bin/bash.exe") if git else None
        if bash:
            result = subprocess.run([bash, "-n", str(ROOT / "install-lan.sh")], capture_output=True, text=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
