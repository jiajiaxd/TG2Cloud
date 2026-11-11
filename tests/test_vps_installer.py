"""Offline boundary tests: no VPS, Docker daemon, Telegram or cloud requests."""

from __future__ import annotations

import ast
import base64
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tg2cloud.cli.terminal as tgdep_terminal
import tg2cloud.cli.vps as tgdep_vps
import tg2cloud.deployment.configuration as tgdep_configuration
import tg2cloud.deployment.install as tgdep_install
import tg2cloud.deployment.instances as tgdep_instances
import tg2cloud.deployment.payload as tgdep_payload
import tg2cloud.deployment.preflight as tgdep_preflight
import tg2cloud.deployment.releases as tgdep_releases
import tg2cloud.deployment.upgrade as tgdep_upgrade
from tg2cloud.cli import vps as cli
from tg2cloud.deployment import architecture
from tg2cloud.deployment.host import LocalFiles, LocalSession, SafeLog, edition_lock
from tg2cloud.deployment.profiles import PRODUCTS
from tg2cloud.deployment.proxy.manager import ProxyEnvironment, ProxyReport
from tg2cloud.deployment.resources import StorageAssessment

ROOT = Path(__file__).resolve().parents[1]
_major, _minor, _patch = tgdep_releases.version_tuple(PRODUCTS["clouddrive2"].app_version)
RELEASE = tgdep_releases.Release(f"v{_major}.{_minor}.{_patch + 1}", "a" * 40)
VALUES = {
    "api_id": "123456", "user_id": "123456789", "api_hash": "a" * 32,
    "bot_token": "123456789:FAKE_LOCAL_TEST_VALUE_NOT_A_REAL_TOKEN",
    "webdav_user": "tg2cloud", "webdav_password": "FAKE $() #@ secret", "target": "Telegram",
    "budget": "20", "reserve": "8", "timezone": "Asia/Shanghai", "admin_password": "FAKE_ADMIN_SECRET",
}


def report(state="healthy", domain="files.example.test"):
    return ProxyReport(domain, state, "local test report", ())


class NonSeekableTty(io.RawIOBase):
    """Exercise real Python buffering without needing a Windows /dev/tty."""

    def __init__(self, mode, source, output, *, terminal=True):
        self.mode = mode
        self.source = source
        self.output = output
        self.terminal = terminal

    def readable(self):
        return "r" in self.mode or "+" in self.mode

    def writable(self):
        return "w" in self.mode or "+" in self.mode

    def isatty(self):
        return self.terminal

    def fileno(self):
        return 42

    def readinto(self, target):
        return self.source.readinto(target)

    def write(self, data):
        return self.output.write(data)


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(patch.object(architecture, "check_docker"))

    def fixture(self, text="", *, terminal=True):
        source, output = io.BytesIO(text.encode()), io.BytesIO()
        streams = []

        def open_tty(path, mode, *, encoding, buffering):
            self.assertEqual(path, "/dev/tty")
            self.assertEqual(encoding, "utf-8")
            self.assertEqual(buffering, 1)
            raw = NonSeekableTty(mode, source, output, terminal=terminal)
            self.assertFalse(raw.seekable())
            # The old r+ implementation raises UnsupportedOperation here, just
            # as open('/dev/tty', 'r+') does on Linux. No permissive Mock stream.
            if "+" in mode:
                buffer = io.BufferedRandom(raw)
            elif mode == "r":
                buffer = io.BufferedReader(raw)
            else:
                self.assertEqual(mode, "w")
                buffer = io.BufferedWriter(raw)
            stream = io.TextIOWrapper(buffer, encoding=encoding, line_buffering=True)
            streams.append(stream)
            return stream

        self.addCleanup(lambda: [stream.close() for stream in streams])
        termios = SimpleNamespace(ECHO=8, TCSANOW=0, tcgetattr=Mock(return_value=[0, 0, 0, 8]), tcsetattr=Mock())
        self.contexts.enter_context(patch.dict("sys.modules", {"termios": termios}))
        opened = self.contexts.enter_context(patch.object(tgdep_terminal, "open", side_effect=open_tty, create=True))
        return opened, streams, output, termios

    def test_nonseekable_terminal_confirmation_defaults_to_cancel_and_accepts_y(self):
        opened, streams, output, _ = self.fixture("\ny\n")
        ui = tgdep_terminal.Terminal()
        self.assertFalse(ui.confirm("CONFIRM"))
        self.assertTrue(ui.confirm("CONFIRM"))
        self.assertEqual([call.args[1] for call in opened.call_args_list], ["r", "w"])
        self.assertIn(b"CONFIRM [y/N] [n]: ", output.getvalue())
        ui.close()
        self.assertTrue(all(stream.closed for stream in streams))

    def test_saved_credentials_require_each_confirmation_and_never_use_log(self):
        for answer in ("\n", "y\n"):
            with self.subTest(confirmed=answer == "y\n"):
                _, _, output, _ = self.fixture(answer * 3)
                ui = tgdep_terminal.Terminal()
                logs = []
                config = tgdep_configuration.new_config(PRODUCTS["openlist"], VALUES)
                tgdep_terminal.show_credentials(ui, PRODUCTS["openlist"], config, SafeLog(logs.append))
                ui.close()
                terminal = output.getvalue().decode("utf-8")
                for secret in (VALUES["webdav_password"], VALUES["admin_password"]):
                    self.assertEqual(secret in terminal, answer == "y\n")
                    self.assertNotIn(secret, "\n".join(logs))
                self.assertNotIn(VALUES["bot_token"], terminal)
                self.assertNotIn(VALUES["api_hash"], terminal)
                self.assertIn("不代表当前密码", "\n".join(logs))

    def test_malformed_saved_credentials_are_not_echoed_or_reset(self):
        ui = Mock()
        logs = []
        config = {
            "WEBDAV_USERNAME_B64": "!invalid-private-fixture!",
            "WEBDAV_PASSWORD_B64": tgdep_configuration.encoded("secret\x1b[31m"),
            "OPENLIST_ADMIN_PASSWORD": "secret\nunsafe",
        }
        tgdep_terminal.show_credentials(ui, PRODUCTS["openlist"], config, SafeLog(logs.append))
        ui.reveal.assert_not_called()
        for value in config.values():
            self.assertNotIn(value, "\n".join(logs))

    def test_clouddrive_legacy_saved_keys_do_not_reveal_openlist_password(self):
        ui = Mock()
        config = {
            "CD2_WEBDAV_USERNAME_B64": tgdep_configuration.encoded("tg2cloud"),
            "CD2_WEBDAV_PASSWORD_B64": tgdep_configuration.encoded(VALUES["webdav_password"]),
            "OPENLIST_ADMIN_PASSWORD": VALUES["admin_password"],
        }
        tgdep_terminal.show_credentials(ui, PRODUCTS["clouddrive2"], config, SafeLog(lambda _line: None))
        self.assertEqual(ui.reveal.call_count, 2)
        self.assertEqual(ui.reveal.call_args.args, ("WebDAV 密码", VALUES["webdav_password"]))

    def test_prompt_is_flushed_before_read_and_does_not_use_stdin(self):
        _, _, output, _ = self.fixture("answer\n")
        ui = tgdep_terminal.Terminal()
        reader = ui.read_line

        def read_after_prompt():
            self.assertIn(b"PROMPT: ", output.getvalue())
            return reader()

        with patch.object(ui, "read_line", side_effect=read_after_prompt), patch("sys.stdin", Mock(readline=Mock(side_effect=AssertionError("must not read stdin")))):
            self.assertEqual(ui.ask("PROMPT"), "answer")
        ui.close()

    def test_parent_menu_leaves_pasted_child_answers_and_empty_email_in_tty(self):
        _, _, _, _ = self.fixture("15\ndav.example.test\n\n")
        parent = tgdep_terminal.Terminal()
        child = tgdep_terminal.Terminal()
        self.assertEqual(parent.ask("MENU"), "15")
        self.assertEqual(child.ask("DOMAIN"), "dav.example.test")
        self.assertEqual(child.ask("EMAIL", validate=lambda value: value), "")
        child.close()
        parent.close()

    def test_normal_input_recovers_echo_off_and_restores_callers_flags(self):
        _, _, _, termios = self.fixture("visible\n")
        termios.tcgetattr.return_value = [0, 0, 0, 0]
        ui = tgdep_terminal.Terminal()
        self.assertEqual(ui.ask("DOMAIN"), "visible")
        self.assertEqual(termios.tcsetattr.call_args_list[0].args[2][3] & termios.ECHO, termios.ECHO)
        self.assertEqual(termios.tcsetattr.call_args_list[-1].args[2][3], 0)
        ui.close()

    def test_complete_bracketed_paste_envelope_and_unicode_are_read_as_one_field(self):
        self.fixture("\x1b[200~dav.example.test\x1b[201~\n资料/电影\n")
        ui = tgdep_terminal.Terminal()
        self.assertEqual(ui.ask("DOMAIN"), "dav.example.test")
        self.assertEqual(ui.ask("PATH"), "资料/电影")
        ui.close()

    def test_secret_input_never_written_and_echo_restored(self):
        _, streams, output, termios = self.fixture("FAKE_SECRET\n")
        ui = tgdep_terminal.Terminal()
        write = streams[1].write

        def inspect_prompt(text):
            if text.startswith("PASSWORD"):
                self.assertEqual(termios.tcsetattr.call_args.args[2][3] & termios.ECHO, 0)
            return write(text)

        with patch.object(streams[1], "write", side_effect=inspect_prompt):
            self.assertEqual(ui.ask("PASSWORD", secret=True, default="FAKE_DEFAULT_SECRET"), "FAKE_SECRET")
        self.assertNotIn(b"FAKE_SECRET", output.getvalue())
        self.assertNotIn(b"FAKE_DEFAULT_SECRET", output.getvalue())
        self.assertEqual(termios.tcsetattr.call_args_list[0].args[2][3] & termios.ECHO, 0)
        self.assertEqual(termios.tcsetattr.call_args_list[-1].args[2][3] & termios.ECHO, termios.ECHO)
        ui.close()

    def test_interrupted_secret_input_restores_echo(self):
        _, _, output, termios = self.fixture()
        ui = tgdep_terminal.Terminal()
        with patch.object(ui, "read_line", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            ui.ask("PASSWORD", secret=True)
        self.assertEqual(termios.tcsetattr.call_args_list[-1].args[2][3] & termios.ECHO, termios.ECHO)
        self.assertIn(b"PASSWORD: \n", output.getvalue().replace(b"\r\n", b"\n"))
        ui.close()

    def test_eof_and_invalid_input_do_not_echo_values(self):
        _, _, output, _ = self.fixture("DO_NOT_LOG_INVALID_VALUE\ny\n")
        ui = tgdep_terminal.Terminal()

        def only_y(value):
            if value != "y":
                raise ValueError("invalid")
            return value

        self.assertEqual(ui.ask("VALIDATE", validate=only_y), "y")
        self.assertNotIn(b"DO_NOT_LOG_INVALID_VALUE", output.getvalue())
        with self.assertRaises(EOFError):
            ui.confirm("CONFIRM")
        ui.close()

    def test_non_terminal_and_partial_open_close_streams(self):
        opened, streams, _, _ = self.fixture(terminal=False)
        with self.assertRaisesRegex(RuntimeError, "交互终端"):
            tgdep_terminal.Terminal()
        self.assertTrue(all(stream.closed for stream in streams))
        reader = io.StringIO()
        opened.side_effect = [reader, OSError("fixture: output unavailable")]
        with self.assertRaises(OSError):
            tgdep_terminal.Terminal()
        self.assertTrue(reader.closed)

    def test_main_requires_actual_terminal_confirmation_for_both_editions(self):
        baseline = patch.object(tgdep_releases, "download_baseline", return_value=ROOT)
        baseline.start()
        self.addCleanup(baseline.stop)
        for product in PRODUCTS.values():
            for check, answer in ((True, ""), (False, "\n"), (False, "y\n"), (False, "")):
                with self.subTest(edition=product.key, check=check, answer=answer):
                    opened, streams, _, _ = self.fixture(answer)
                    instance = tgdep_instances.Instance(product, ROOT, True, version=product.app_version)
                    plan = tgdep_install.Plan(instance, "upgrade", Mock())
                    client = Mock()
                    client.resolve.side_effect = [RELEASE, tgdep_releases.Release("v" + instance.version, "b" * 40)]
                    client.download.return_value = ROOT
                    messages = []
                    args = ["--edition", product.key] + (["--check"] if check else [])
                    with patch.object(tgdep_preflight, "validate_host"), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=instance), patch.object(tgdep_releases, "ReleaseClient", return_value=client), patch.object(tgdep_install, "make_plan", return_value=plan), patch.object(tgdep_install, "execute_plan") as execute, patch.object(cli, "SafeLog", return_value=SafeLog(messages.append)):
                        self.assertEqual(tgdep_vps.main(args), 1 if not check and not answer else 0)
                    if check:
                        opened.assert_not_called()
                        self.assertIn("TG2CLOUD_CLI_CHECK=OK", "".join(messages))
                    elif answer == "\n":
                        self.assertIn("TG2CLOUD_CLI_RESULT=CANCELLED", "".join(messages))
                    if answer == "y\n":
                        execute.assert_called_once()
                    else:
                        execute.assert_not_called()
                    self.assertTrue(all(stream.closed for stream in streams))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Real Linux controlling PTY; no VPS or Docker calls")
    def test_real_linux_tty_confirmation_secret_and_interrupt(self):
        import pty
        import select

        code = r'''
import fcntl, os, termios, subprocess, sys
os.setsid()
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
from tg2cloud.cli.terminal import Terminal
ui = Terminal()
try:
    assert not ui.confirm("CONFIRM_DEFAULT")
    assert ui.confirm("CONFIRM_YES")
    assert ui.ask("HANDOFF") == "15"
    child = r"""
from tg2cloud.addons.external_webdav.cli import WebDAVTerminal
from tg2cloud.deployment.proxy.state import validate_domain, validate_email
ui = WebDAVTerminal()
try:
    assert ui.ask("CHILD_DOMAIN", validate=validate_domain) == "dav.example.test"
    assert ui.ask("CHILD_EMAIL", validate=validate_email) == ""
    print("CHILD_OK", flush=True)
finally:
    ui.close()
"""
    subprocess.run([sys.executable, "-B", "-c", child], check=True)
    before = termios.tcgetattr(0)
    assert ui.ask("PASSWORD", secret=True) == "FAKE_PTY_SECRET"
    assert termios.tcgetattr(0) == before
    print("SECRET_OK", flush=True)
    try:
        ui.ask("INTERRUPT", secret=True)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("Ctrl-C must interrupt the prompt")
    assert termios.tcgetattr(0) == before
    print("PTY_OK", flush=True)
finally:
    ui.close()
'''
        master, slave = pty.openpty()
        process = None
        transcript = bytearray()
        try:
            process = subprocess.Popen([sys.executable, "-B", "-c", code], stdin=slave, stdout=slave, stderr=slave, cwd=ROOT)

            def read_until(marker):
                deadline = time.monotonic() + 10
                while marker not in transcript:
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, "PTY prompt timed out: " + repr(bytes(transcript)))
                    ready, _, _ = select.select([master], [], [], remaining)
                    self.assertTrue(ready, "PTY prompt timed out: " + repr(bytes(transcript)))
                    transcript.extend(os.read(master, 4096))

            read_until(b"CONFIRM_DEFAULT [y/N] [n]: ")
            os.write(master, b"\n")
            read_until(b"CONFIRM_YES [y/N] [n]: ")
            os.write(master, b"y\n")
            read_until(b"HANDOFF: ")
            os.write(master, b"15\ndav.example.test\n\n")
            read_until(b"CHILD_OK")
            read_until(b"PASSWORD: ")
            os.write(master, b"FAKE_PTY_SECRET\n")
            read_until(b"INTERRUPT: ")
            os.write(master, b"\x03")
            read_until(b"PTY_OK")
            self.assertEqual(process.wait(timeout=10), 0, bytes(transcript))
            self.assertNotIn(b"FAKE_PTY_SECRET", transcript)
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            os.close(master)
            os.close(slave)


class StandaloneBootstrapTests(unittest.TestCase):
    """Exercise the downloaded entry without network or deployment calls."""

    def setUp(self):
        native = patch.object(architecture, "check_docker")
        native.start()
        self.addCleanup(native.stop)
        content = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.embedded = content.split("<<'PY' &\n", 1)[1].split("\nPY\n", 1)[0]
        constants = {node.targets[0].id: node.value.value for node in ast.parse(self.embedded).body
                     if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and isinstance(node.value, ast.Constant)}
        self.pin = constants["installer_commit"]
        self.helper_version = constants["installer_version"]
        self.assertRegex(self.pin, r"^[0-9a-f]{40}$")
        self.release = {"tag_name": RELEASE.tag, "draft": False, "prerelease": False}
        self.item = {"object": {"type": "commit", "sha": "a" * 40}}
        self.urls = []

    def bootstrap(self, root, *, version=None, missing_helper=False):
        def open_fixture(request, *, timeout):
            self.assertEqual(timeout, 30)
            url = request.full_url
            self.urls.append(url)
            if url == tgdep_releases.API + "/releases/latest":
                return io.BytesIO(json.dumps(self.release).encode())
            if url == tgdep_releases.API + "/git/ref/tags/" + self.release["tag_name"]:
                return io.BytesIO(json.dumps(self.item).encode())
            prefix = "https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/" + self.pin + "/"
            self.assertTrue(url.startswith(prefix), "helper must not use main or the payload commit")
            name = url.removeprefix(prefix)
            self.assertIn(name, json.loads((ROOT / "packaging/bootstrap-manifest.json").read_text())["files"])
            if missing_helper:
                raise OSError("offline fixture: helper unavailable")
            from payload_fixture import historical_file
            data = historical_file(self.pin, name)
            if name == "src/tg2cloud/version.py":
                # The fixture represents the pinned helper revision, not a
                # future product version in the local working tree.
                data = version if version is not None else f'VERSION = "{self.helper_version}"\n'.encode()
            return io.BytesIO(data)

        opener = Mock()
        opener.open.side_effect = open_fixture
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["bootstrap", str(root)]), patch("sys.stdout", output), patch("sys.stderr", errors), patch("urllib.request.build_opener", return_value=opener):
            try:
                exec(compile(self.embedded, "install.sh bootstrap", "exec"), {})  # noqa: S102 - repository-owned code with mocked networking
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue()

    def test_wizard_pin_is_independent_of_stable_payload_commit_and_version(self):
        # The payload Release deliberately has no CLI files; helpers are fetched
        # from the reviewed source pin, not from that old/new payload Release.
        with tempfile.TemporaryDirectory() as private:
            root = Path(private)
            code, output, errors = self.bootstrap(root)
            self.assertEqual(code, 0, errors)
            self.assertIn("安装向导：v" + self.helper_version, output)
            self.assertIn("正式稳定版本：" + RELEASE.tag, output)
            self.assertNotIn(self.pin, output)
            self.assertNotIn("a" * 40, output)
            marker = root / ".bootstrap-release.json"
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), {
                "tag": RELEASE.tag, "commit": "a" * 40, "installer_commit": self.pin,
            })
            if os.name == "posix":
                self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            from payload_fixture import historical_file
            helpers = json.loads(historical_file(self.pin, "packaging/bootstrap-manifest.json"))["files"]
            self.assertEqual(len(self.urls), 2 + len(helpers))
            self.assertFalse(any("/main/" in url or "/heads/" in url for url in self.urls))

    def test_rc_draft_bad_tag_and_commit_stop_before_helpers(self):
        cases = ({"tag_name": RELEASE.tag + "-rc.1"}, {"draft": True}, {"prerelease": True},
                 {"tag_name": "main"}, {"commit": "main"})
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as private:
                self.setUp()
                if "commit" in case:
                    self.item["object"]["sha"] = case["commit"]
                else:
                    self.release.update(case)
                root = Path(private)
                code, _, _ = self.bootstrap(root)
                self.assertEqual(code, 2)
                self.assertFalse((root / ".bootstrap-release.json").exists())
                self.assertFalse(any("raw.githubusercontent.com" in url for url in self.urls))

    def test_helper_download_or_version_failure_does_not_create_marker(self):
        repeated = f'VERSION = "{self.helper_version}"\n' * 2
        for options in ({"missing_helper": True}, {"version": b'VERSION = "9.9.9"\n'},
                        {"version": repeated.encode()}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as private:
                root = Path(private)
                code, _, errors = self.bootstrap(root, **options)
                self.assertEqual(code, 2)
                self.assertIn("未修改 VPS", errors)
                self.assertFalse((root / ".bootstrap-release.json").exists())

    def test_version_validation_does_not_execute_downloaded_python(self):
        with tempfile.TemporaryDirectory() as private:
            root = Path(private)
            payload = (f'VERSION = "{self.helper_version}"\nraise RuntimeError("must not execute")\n').encode()
            code, _, errors = self.bootstrap(root, version=payload)
            self.assertEqual(code, 0, errors)

    def test_payload_tag_changed_after_bootstrap_stops_before_download_or_apply(self):
        messages = []
        with tempfile.TemporaryDirectory() as private:
            root = Path(private).resolve()
            marker = root / ".bootstrap-release.json"
            marker.write_text(json.dumps({"tag": "v1.1.2", "commit": "b" * 40}), encoding="utf-8")
            marker.chmod(0o600)
            client = Mock()
            client.resolve.return_value = tgdep_releases.Release("v1.1.2", "c" * 40)
            instance = tgdep_instances.Instance(PRODUCTS["clouddrive2"], root, False)
            with patch.dict(os.environ, {"TG2CLOUD_SOURCE_ROOT": str(root)}), patch.object(tgdep_preflight, "validate_host"), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=instance), patch.object(tgdep_releases, "ReleaseClient", return_value=client), patch.object(tgdep_configuration, "regular_private", side_effect=lambda path: path.read_bytes()), patch.object(cli, "SafeLog", return_value=SafeLog(messages.append)), patch.object(tgdep_install, "execute_plan") as apply:
                self.assertEqual(tgdep_vps.main(["--edition", "clouddrive2", "--check"]), 1)
            client.resolve.assert_called_once_with("v1.1.2")
            client.download.assert_not_called()
            apply.assert_not_called()
            self.assertIn("Tag 发生变化", "".join(messages))


class ApiTests(unittest.TestCase):
    def client(self, *, tag=RELEASE.tag, draft=False, prerelease=False):
        client = tgdep_releases.ReleaseClient()
        client.json = Mock(side_effect=[
            {"tag_name": tag, "draft": draft, "prerelease": prerelease},
            {"object": {"type": "commit", "sha": RELEASE.commit}},
        ])
        return client

    def test_latest_pins_commit_not_main(self):
        client = self.client()
        self.assertEqual(client.resolve(), RELEASE)
        self.assertEqual(client.json.call_args_list[0].args[0], tgdep_releases.API + "/releases/latest")
        self.assertEqual(client.json.call_args_list[1].args[0], tgdep_releases.API + "/git/ref/tags/" + RELEASE.tag)

    def test_reject_rc_draft_and_nonsemver(self):
        for kwargs in ({"tag": RELEASE.tag + "-rc.1"}, {"draft": True}, {"prerelease": True}, {"tag": "main"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.client(**kwargs).resolve()

    def test_specific_tag_cannot_select_prerelease(self):
        with self.assertRaises(ValueError):
            self.client().resolve(RELEASE.tag + "-rc.1")

    def test_tag_mismatch_and_invalid_sha(self):
        with self.assertRaises(ValueError):
            self.client().resolve("v1.1.2")
        client = self.client()
        client.json.side_effect = [
            {"tag_name": RELEASE.tag, "draft": False, "prerelease": False},
            {"object": {"type": "commit", "sha": "main"}},
        ]
        with self.assertRaises(ValueError):
            client.resolve()

    def test_annotated_tag_is_peeled(self):
        client = self.client()
        client.json.side_effect = [
            {"tag_name": RELEASE.tag, "draft": False, "prerelease": False},
            {"object": {"type": "tag", "sha": "b" * 40}},
            {"object": {"type": "commit", "sha": RELEASE.commit}},
        ]
        self.assertEqual(client.resolve(), RELEASE)

    def test_download_checks_source_version_without_execution(self):
        with tempfile.TemporaryDirectory() as private:
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w:gz") as archive:
                info = tarfile.TarInfo("repo/app/version.py")
                content = b'VERSION="9.9.9"\n'
                info.name = "repo/payload_clouddrive2/app/version.py"
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            with patch.object(tgdep_releases, "open_public", return_value=io.BytesIO(data.getvalue())), self.assertRaisesRegex(ValueError, "Tag"):
                tgdep_releases.ReleaseClient().download(RELEASE, Path(private))

    def test_only_public_https_urls_including_redirects(self):
        tgdep_releases.validate_public_url(tgdep_releases.API + "/releases/latest")
        for url in ("file:///etc/passwd", "http://api.github.com/x", "https://api.github.com.evil/x", "https://user:secret@api.github.com/x", "https://api.github.com:8443/x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                tgdep_releases.validate_public_url(url)
        with self.assertRaises(ValueError):
            tgdep_releases.PublicRedirect().redirect_request(None, None, 302, "", {}, "http://api.github.com/x")


class ArchiveTests(unittest.TestCase):
    def extract(self, members):
        with tempfile.TemporaryDirectory() as private:
            archive = Path(private) / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as writer:
                for name, kind in members:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = "/etc/passwd"
                    content = b"test"
                    info.size = len(content) if kind == tarfile.REGTYPE else 0
                    writer.addfile(info, io.BytesIO(content) if info.size else None)
            tgdep_releases.extract_source(archive, Path(private) / "source")

    def test_normal_source(self):
        self.extract([("repo/app/version.py", tarfile.REGTYPE)])

    def test_unsafe_paths_and_types(self):
        for name, kind in (("repo/../../escape", tarfile.REGTYPE), ("/tmp/escape", tarfile.REGTYPE),
                           ("repo/link", tarfile.SYMTYPE), ("repo/hard", tarfile.LNKTYPE),
                           ("repo/device", tarfile.CHRTYPE), ("repo\\escape", tarfile.REGTYPE)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract([(name, kind)])

    def test_duplicate_and_two_roots(self):
        for names in (("repo/a", "repo/a"), ("repo/a", "other/b")):
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.extract([(name, tarfile.REGTYPE) for name in names])


class VersionSourceTests(unittest.TestCase):
    def read_version(self, legacy, current=None):
        with tempfile.TemporaryDirectory() as private:
            root = Path(private).resolve()
            (root / "app").mkdir()
            (root / "app/__init__.py").write_text(legacy, encoding="utf-8")
            if current is not None:
                (root / "app/version.py").write_text(current, encoding="utf-8")
            return tgdep_releases.source_version(root)

    def test_published_legacy_literal_without_execution(self):
        self.assertEqual(self.read_version('__version__ = "1.0.2"\nraise RuntimeError("not executed")'), "1.0.2")

    def test_new_version_source_takes_precedence(self):
        self.assertEqual(self.read_version('__version__ = "1.0.2"', 'VERSION = "1.1.2"'), "1.1.2")

    def test_invalid_new_source_never_falls_back(self):
        for current in ('', 'VERSION = "bad"', 'VERSION = "1.1.2"\nVERSION = "1.1.3"', 'VERSION = "1.1.2-rc.1"'):
            with self.subTest(current=current), self.assertRaises(ValueError):
                self.read_version('__version__ = "1.0.2"', current)

    def test_legacy_dynamic_duplicate_or_nonstable_version_rejected(self):
        for legacy in ('__version__ = get_version()', '__version__ = "1.0.2"\n__version__ = "1.0.3"',
                       '__version__ = "1.0.2-rc.1"', 'VERSION = "1.0.2"'):
            with self.subTest(legacy=legacy), self.assertRaises(ValueError):
                self.read_version(legacy)

    def test_legacy_baseline_still_requires_exact_official_payload(self):
        with tempfile.TemporaryDirectory() as private:
            root = Path(private).resolve()
            source = root / "official"
            from payload_fixture import historical_payload
            historical_payload(source, "clouddrive2")
            payload = source / "payload_clouddrive2"
            (payload / "app/version.py").unlink()
            (payload / "app/__init__.py").write_text('__version__ = "1.0.2"\n', encoding="utf-8")
            destination = root / "installed"
            shutil.copytree(payload, destination)
            instance = tgdep_instances.Instance(PRODUCTS["clouddrive2"], destination, True, "1.0.2")
            tgdep_upgrade.assert_unmodified(instance, source)
            (destination / "app/main.py").write_text("# custom code\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "已发布版本不一致"):
                tgdep_upgrade.assert_unmodified(instance, source)


class ConfigPayloadTests(unittest.TestCase):
    def test_payloads_are_assembled_from_existing_manifest(self):
        for product in PRODUCTS.values():
            with self.subTest(edition=product.key), tempfile.TemporaryDirectory() as private:
                dest = Path(private) / "payload"
                tgdep_payload.build_payload(ROOT, product, dest)
                for name, source in tgdep_payload.payload_sources(ROOT, product).items():
                    self.assertEqual((dest / name).read_bytes(), source.read_bytes())
                self.assertTrue((dest / "LICENSE").is_file())
                self.assertFalse((dest / "tg2cloud-release.json").exists())
                self.assertEqual(tgdep_releases.source_version(dest), product.app_version)

    def test_public_payload_modes_do_not_touch_parent_or_candidate_secrets(self):
        for product in PRODUCTS.values():
            with self.subTest(edition=product.key), tempfile.TemporaryDirectory() as private:
                dest = Path(private) / "payload"
                candidate = Path(private) / "config.env"
                candidate.write_text("FAKE_CANDIDATE_SECRET", encoding="utf-8")
                candidate.chmod(0o600)
                with patch.object(Path, "chmod", autospec=True) as chmod:
                    tgdep_payload.build_payload(ROOT, product, dest)
                expected_files = {dest / name for name in tgdep_payload.payload_sources(ROOT, product)}
                expected_files.update(dest / name for name in ("LICENSE", "NOTICE", "README.md") if (ROOT / name).is_file())
                changed_files = {call.args[0] for call in chmod.call_args_list if call.args[1] == 0o644}
                self.assertEqual(changed_files, expected_files)
                for call in chmod.call_args_list:
                    path, mode = call.args
                    self.assertTrue(path.is_relative_to(dest))
                    self.assertNotEqual(path, dest)
                    self.assertIn(mode, (0o644, 0o755))
                self.assertEqual(candidate.read_text(encoding="utf-8"), "FAKE_CANDIDATE_SECRET")
                self.assertFalse((dest / "config.env").exists())
                self.assertFalse((dest / ".env").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits require Linux")
    def test_private_archive_source_becomes_readable_public_context_only(self):
        for product in PRODUCTS.values():
            with self.subTest(edition=product.key), tempfile.TemporaryDirectory() as private:
                source = Path(private) / "source"
                source.mkdir(mode=0o700)
                for original in (ROOT / "src/tg2cloud").rglob("*.py"):
                    path = source / original.relative_to(ROOT)
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    shutil.copyfile(original, path)
                    path.chmod(0o600)
                for relative in product.required_payload:
                    path = source / relative
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / relative, path)
                    path.chmod(0o600)
                (source / ".env").write_text("FAKE_SECRET_NOT_PUBLIC", encoding="utf-8")
                (source / ".env").chmod(0o600)
                candidate = Path(private) / "config.env"
                candidate.write_text("FAKE_CANDIDATE_SECRET", encoding="utf-8")
                candidate.chmod(0o600)
                dest = Path(private) / "payload"
                previous_umask = os.umask(0o077)
                try:
                    tgdep_payload.build_payload(source, product, dest)
                finally:
                    os.umask(previous_umask)
                for path in dest.rglob("*"):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o755 if path.is_dir() else 0o644, str(path))
                self.assertEqual(dest.stat().st_mode & 0o777, 0o700)
                self.assertEqual(Path(private).stat().st_mode & 0o777, 0o700)
                self.assertEqual(candidate.stat().st_mode & 0o777, 0o600)
                self.assertEqual((source / ".env").stat().st_mode & 0o777, 0o600)
                self.assertFalse((dest / ".env").exists())
                for name, path in tgdep_payload.payload_sources(source, product).items():
                    self.assertEqual((dest / name).read_bytes(), path.read_bytes())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_missing_resource_stops(self):
        with tempfile.TemporaryDirectory() as private, self.assertRaises(ValueError):
            tgdep_payload.payload_sources(Path(private), PRODUCTS["openlist"])

    def test_config_matches_saved_environment_contract_without_desktop(self):
        fixture = json.loads((ROOT / "tests/fixtures/deployment-config.json").read_text(encoding="utf-8"))
        self.assertEqual(VALUES, fixture["values"])
        for product in PRODUCTS.values():
            with self.subTest(edition=product.key):
                # Retain the historical fixture. Only obsolete output aliases
                # are intentionally omitted from newly generated v1.5.3 configs.
                expected = {key: value for key, value in fixture["expected"][product.key].items()
                            if not key.startswith("TG115_")}
                self.assertEqual(tgdep_configuration.new_config(product, VALUES), expected)

    def test_shell_characters_in_password_stay_encoded(self):
        config = tgdep_configuration.new_config(PRODUCTS["openlist"], VALUES)
        self.assertEqual(base64.b64decode(config["WEBDAV_PASSWORD_B64"]).decode(), VALUES["webdav_password"])
        self.assertNotIn(VALUES["webdav_password"], "\n".join(config.values()))

    def test_duplicate_config_and_invalid_cover_flag_rejected(self):
        for raw in (b"A=1\nA=2\n", b"export A=1", b"TG2CLOUD_REDEPLOY_APPLY_CONFIG=maybe"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                tgdep_configuration.parse_config(raw)
        self.assertEqual(tgdep_configuration.parse_config(b"A=$(touch /tmp/not-executed)\r\n"), {"A": "$(touch /tmp/not-executed)"})

    def test_logging_redacts_plain_encoded_and_unregistered_tokens(self):
        log = SafeLog()
        log.register(tgdep_configuration.new_config(PRODUCTS["openlist"], VALUES))
        text = "\n".join(VALUES[key] for key in ("api_hash", "bot_token", "webdav_password", "admin_password"))
        text += "\n" + tgdep_configuration.encoded(VALUES["webdav_password"]) + "\nhttps://user:UNKNOWN@host/\nPassword=UNKNOWN\nCookie: UNKNOWN"
        text += '\n{"access_token":"UNKNOWN","cookie":"UNKNOWN"}'
        result = log.clean(text)
        self.assertNotIn("UNKNOWN", result)
        for key in ("api_hash", "bot_token", "webdav_password", "admin_password"):
            self.assertNotIn(VALUES[key], result)

    def test_numeric_and_control_validators(self):
        for value in ("0", "-1", "$(id)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tgdep_configuration.positive(value)
        for value in ("nan", "inf", "-1", "0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tgdep_configuration.size_gb(value)
        with self.assertRaises(ValueError):
            tgdep_configuration.plain("password\nINJECTION=true")

    def test_install_paths_cannot_overlap_another_component(self):
        product = PRODUCTS["clouddrive2"]
        tgdep_configuration.check_product_directory(product, Path(product.install_dir))
        for path in ("/opt/tg2cloud-proxy", "/opt/tg2cloud-proxy/child", "/opt/tg2cloud-openlist", "/opt/tg2cloud-clouddrive2-backups", "/opt/tg115"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                tgdep_configuration.check_product_directory(product, Path(path))

    def test_foreign_cd2_repair_candidates_cannot_be_adopted(self):
        product = PRODUCTS["clouddrive2"]
        session = Mock()
        for listing in ("my-clouddrive2 unrelated/image:latest", "other vendor/clouddrive2@sha256:abc"):
            session.run.return_value = (0, listing)
            with self.subTest(listing=listing), self.assertRaisesRegex(ValueError, "其他 CloudDrive2"):
                tgdep_instances.check_foreign_gateway(product, session)
        session.run.return_value = (0, product.bot_container + " bot-image\n" + product.storage_container + " cloudnas/clouddrive2@sha256:abc")
        tgdep_instances.check_foreign_gateway(product, session)


class InstanceTests(unittest.TestCase):
    def setUp(self):
        # Orchestration fixtures have no daemon. Native platform refusal and
        # actual image inspection are exercised in test_architecture.py.
        for name in ("check_docker", "check_container"):
            boundary = patch.object(architecture, name)
            boundary.start()
            self.addCleanup(boundary.stop)
        self.private = tempfile.TemporaryDirectory()
        self.addCleanup(self.private.cleanup)
        # Windows hosted runners may expose TEMP through an 8.3 alias or a
        # junction. Canonicalize fixtures, not the production fail-closed checks.
        self.directory = Path(self.private.name).resolve() / "install"
        self.product = PRODUCTS["openlist"]
        tgdep_payload.build_payload(ROOT, self.product, self.directory)
        for name in ("data", "config", "downloads", "logs", "openlist/data"):
            (self.directory / name).mkdir(parents=True)
        self.raw = ("# retained comment\r\n" + "\r\n".join(k + "=" + v for k, v in tgdep_configuration.new_config(self.product, VALUES).items()) + "\r\n").encode()
        (self.directory / ".env").write_bytes(self.raw)
        (self.directory / ".env").chmod(0o600)
        self.instance = tgdep_instances.Instance(self.product, self.directory, True, self.product.app_version,
                                     False, tgdep_payload.gateway_image(ROOT, self.product), tgdep_configuration.parse_config(self.raw), self.raw)
        self.log = SafeLog(lambda _text: None)

    def test_current_newer_upgrade_and_major_boundaries(self):
        self.assertEqual(tgdep_upgrade.action_for(self.instance, RELEASE), "upgrade")
        self.assertEqual(tgdep_upgrade.action_for(self.instance, tgdep_releases.Release("v" + self.instance.version, "b" * 40)), "current")
        self.assertEqual(tgdep_upgrade.action_for(self.instance, tgdep_releases.Release("v1.0.0", "b" * 40)), "newer")
        with self.assertRaises(ValueError):
            tgdep_upgrade.action_for(self.instance, tgdep_releases.Release("v2.0.0", "b" * 40))

    def test_official_payload_with_crlf_is_not_a_local_edit(self):
        tgdep_upgrade.assert_unmodified(self.instance, ROOT)
        path = self.directory / "manage.sh"
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        tgdep_upgrade.assert_unmodified(self.instance, ROOT)
        path.write_bytes(path.read_bytes() + b"# LOCAL EDIT\n")
        with self.assertRaisesRegex(ValueError, "manage.sh"):
            tgdep_upgrade.assert_unmodified(self.instance, ROOT)

    def test_extra_app_source_is_not_overwritten(self):
        (self.directory / "app/custom.py").write_text("# private extension", encoding="utf-8")
        with self.assertRaises(ValueError):
            tgdep_upgrade.assert_unmodified(self.instance, ROOT)

    def test_partial_container_and_orphan_directory_stop(self):
        with patch.object(tgdep_configuration, "checked_directory", return_value=self.directory):
            for inventory in (set(), {self.product.bot_container}, {self.product.storage_container}):
                with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                    tgdep_instances.discover(self.product, inventory, Mock(), self.log)

    def test_docker_daemon_failure_is_not_fresh_install(self):
        session = Mock()
        session.run.side_effect = [(0, ""), (1, "")]
        with self.assertRaises(RuntimeError):
            tgdep_instances.docker_inventory(session)

    def containers(self):
        labels = {"com.docker.compose.project.working_dir": str(self.directory),
                  "com.docker.compose.project": "tg2cloud-openlist", "com.docker.compose.service": self.product.bot_service}
        bot = {"labels": labels, "image": "bot", "image_id": "sha256:" + "a" * 64, "running": False, "mounts": [
            {"Type": "bind", "Destination": "/" + name, "Source": str(self.directory / name)}
            for name in ("data", "config", "downloads", "logs")
        ]}
        gateway = {"labels": {**labels, "com.docker.compose.service": "openlist"}, "image": self.instance.gateway_image, "image_id": "sha256:" + "b" * 64,
                   "mounts": [{"Type": "bind", "Destination": "/opt/openlist/data", "Source": str(self.directory / "openlist/data")}]}
        return bot, gateway

    def discover(self, bot, gateway, actual=None):
        session = Mock()
        services = {self.product.bot_service: {"container_name": self.product.bot_container}, "openlist": {"container_name": self.product.storage_container}}
        def query(command, **_kwargs):
            if command.startswith("docker image inspect "):
                self.assertTrue(command.endswith((bot["image_id"], gateway["image_id"])))
                return 0, json.dumps({"os": "linux", "arch": architecture.normalize_architecture(architecture.platform.machine())})
            return 0, json.dumps(actual if command.startswith("docker exec ") else {"services": services})
        session.run.side_effect = query
        with patch.object(tgdep_configuration, "checked_directory", return_value=self.directory), patch.object(tgdep_instances, "inspect_container", side_effect=[bot, gateway]), patch.object(tgdep_configuration, "regular_private", side_effect=lambda path: path.read_bytes()):
            return tgdep_instances.discover(self.product, {self.product.bot_container, self.product.storage_container}, session, self.log)

    def test_complete_instance_retains_raw_config(self):
        result = self.discover(*self.containers())
        self.assertEqual(result.raw_config, self.raw)
        self.assertNotIn(VALUES["admin_password"], repr(result))
        # CD2's installer normalizes env line endings: refuse before writing.
        self.product = PRODUCTS["clouddrive2"]
        bot, gateway = self.containers()
        gateway["labels"]["com.docker.compose.service"] = "clouddrive2"
        gateway["mounts"] = []
        for destination, relative in (("/Config", "clouddrive/config"), ("/CloudNAS", "clouddrive/mounts")):
            (self.directory / relative).mkdir(parents=True)
            gateway["mounts"].append({"Type": "bind", "Destination": destination, "Source": str(self.directory / relative)})
        with self.assertRaisesRegex(ValueError, "CRLF"):
            self.discover(bot, gateway)

    def test_compose_bot_or_gateway_is_rejected_before_config_or_commands(self):
        for product in PRODUCTS.values():
            for side in (0, 1):
                with self.subTest(edition=product.key, side=side):
                    containers = self.containers()
                    containers[side]["labels"]["com.tg2cloud.install-mode"] = "compose"
                    session = Mock()
                    with patch.object(tgdep_configuration, "checked_directory", return_value=self.directory), patch.object(
                        tgdep_instances, "inspect_container", side_effect=containers
                    ), patch.object(tgdep_configuration, "regular_private") as config, self.assertRaisesRegex(ValueError, "独立 Docker Compose"):
                        tgdep_instances.discover(product, {product.bot_container, product.storage_container}, session, self.log)
                    session.run.assert_not_called()
                    config.assert_not_called()

    def test_script_instance_does_not_adopt_compose_markers(self):
        for name in ("compose-bundle.json", "tg2cloud-compose.json"):
            with self.subTest(marker=name):
                path = self.directory / name
                path.write_text("{}")
                with self.assertRaisesRegex(ValueError, "归属标记"):
                    self.discover(*self.containers())
                self.assertEqual(path.read_text(), "{}")
                path.unlink()  # Only this test's synthetic marker.

    def test_running_code_fingerprint_is_required(self):
        bot, gateway = self.containers()
        bot["running"] = True
        from tg2cloud.deployment.fingerprints import deployed_fingerprint
        actual = {"version": self.instance.version, "fingerprint": deployed_fingerprint(self.directory / "app")}
        self.assertTrue(self.discover(bot, gateway, actual).running)
        actual["fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "运行代码"):
            self.discover(bot, gateway, actual)

    def test_foreign_labels_and_gateway_mounts_stop(self):
        bot, gateway = self.containers()
        gateway["mounts"][0]["Source"] = "/opt/other/openlist/data"
        with self.assertRaises(ValueError):
            self.discover(bot, gateway)
        bot, gateway = self.containers()
        gateway["labels"]["com.docker.compose.project"] = "foreign"
        with self.assertRaises(ValueError):
            self.discover(bot, gateway)

    def test_upgrade_does_not_collect_credentials_or_configure_healthy_https(self):
        manager = Mock()
        manager.read_state.return_value = {"domains": {"openlist": {"domain": "files.example.test"}}}
        manager.status.return_value = report()
        ui, session = Mock(), Mock()
        session.run.return_value = (0, "")
        with patch.object(tgdep_install, "DomainProxyManager", return_value=manager), patch.object(tgdep_preflight, "resource_check"):
            plan = tgdep_install.make_plan(self.instance, RELEASE, ROOT, ROOT, session, self.log, ui)
        ui.ask.assert_not_called()
        manager.configure.assert_not_called()
        self.assertFalse(plan.configure_https)
        self.assertEqual(plan.config, self.instance.config)

    def test_gateway_image_change_is_not_automatic_database_migration(self):
        self.instance.gateway_image = "openlistteam/openlist@sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "网关镜像"), patch.object(tgdep_install, "DomainProxyManager") as manager:
            tgdep_install.make_plan(self.instance, RELEASE, ROOT, ROOT, Mock(), self.log, Mock())
        manager.assert_not_called()

    def test_upgrade_candidate_contains_only_preserve_flag(self):
        session = Mock()
        seen = []

        def install(command, **kwargs):
            # No credential can be in argv; read only the private candidate path.
            import shlex
            candidate = Path(shlex.split(command)[-1])
            seen.append(candidate.read_text(encoding="utf-8"))
            self.assertNotIn(VALUES["admin_password"], command)
            return 0, "TG2CLOUD_RESULT=SUCCESS\nTG2CLOUD_BOT_HEALTH=healthy\n"

        session.run.side_effect = install
        manager = Mock(external_plan=None)
        manager.read_state.return_value = {"version": 1, "domains": {}}
        plan = tgdep_install.Plan(self.instance, "upgrade", manager, self.instance.config)
        with patch.object(tgdep_configuration, "regular_private", side_effect=lambda path: path.read_bytes()):
            tgdep_install.apply_base(plan, RELEASE, ROOT, session, self.log)
        self.assertEqual(seen, ["TG2CLOUD_REDEPLOY_APPLY_CONFIG=false\n"])
        self.assertEqual((self.directory / ".env").read_bytes(), self.raw)
        self.assertEqual(json.loads((self.directory / "tg2cloud-release.json").read_text())["commit"], RELEASE.commit)

    def test_failed_install_does_not_record_new_version(self):
        tgdep_upgrade.record_release(self.directory, tgdep_releases.Release("v1.1.2", "b" * 40))
        session = Mock()
        session.run.return_value = (1, "TG2CLOUD_RESULT=FAILED\n")
        manager = Mock(external_plan=None)
        manager.read_state.return_value = {"version": 1, "domains": {}}
        with self.assertRaises(RuntimeError):
            tgdep_install.apply_base(tgdep_install.Plan(self.instance, "upgrade", manager), RELEASE, ROOT, session, self.log)
        self.assertEqual(json.loads((self.directory / "tg2cloud-release.json").read_text())["tag"], "v1.1.2")

    def test_verified_marker_requires_exit_success_and_explicit_confirmation(self):
        ui, session = Mock(), Mock()
        plan = tgdep_install.Plan(self.instance, "current", Mock())
        ui.confirm.return_value = False
        self.assertFalse(tgdep_install.verify_destination(plan, session, self.log, ui))
        session.run.assert_not_called()
        ui.confirm.return_value = True
        session.run.return_value = (1, "TG2CLOUD_DESTINATION=OK\n")
        with self.assertRaises(RuntimeError):
            tgdep_install.verify_destination(plan, session, self.log, ui)
        session.run.return_value = (0, "TG2CLOUD_DESTINATION=OK\n")
        self.assertTrue(tgdep_install.verify_destination(plan, session, self.log, ui))

    def test_execute_rechecks_env_before_write(self):
        changed = tgdep_instances.Instance(self.product, self.directory, True, self.instance.version, raw_config=b"CHANGED=1\n")
        with patch.object(tgdep_install, "edition_lock", return_value=nullcontext()), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=changed), patch.object(tgdep_install, "apply_base") as apply, self.assertRaisesRegex(ValueError, "已变更"):
            tgdep_install.execute_plan(tgdep_install.Plan(self.instance, "upgrade", Mock()), RELEASE, ROOT, ROOT, Mock(), self.log, Mock())
        apply.assert_not_called()

    def test_https_failure_does_not_report_acceptance(self):
        manager = Mock()
        manager.status.return_value = report("running_error")
        with patch.object(tgdep_install, "edition_lock", return_value=nullcontext()), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=self.instance), patch.object(tgdep_preflight, "resource_check"), patch.object(tgdep_install, "apply_base"), patch.object(tgdep_install, "verify_destination") as verify, self.assertRaisesRegex(RuntimeError, "HTTPS"):
            tgdep_install.execute_plan(tgdep_install.Plan(self.instance, "upgrade", manager), RELEASE, ROOT, ROOT, Mock(), self.log, Mock(), verify=True)
        verify.assert_not_called()

    def test_https_resume_offers_saved_credentials_without_reinstall(self):
        manager, ui, session = Mock(), Mock(), Mock()
        manager.status.return_value = report()
        plan = tgdep_install.Plan(self.instance, "current", manager, self.instance.config,
                        "files.example.test", configure_https=True)
        with patch.object(tgdep_install, "edition_lock", return_value=nullcontext()), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=self.instance), patch.object(tgdep_install, "verify_destination") as verify:
            tgdep_install.execute_plan(plan, RELEASE, ROOT, ROOT, session, self.log, ui)
        manager.configure.assert_called_once_with("files.example.test", "")
        calls = session.run.call_args_list
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
        verify.assert_not_called()
        self.assertEqual(ui.reveal.call_count, 3)
        self.assertEqual(ui.reveal.call_args_list[1].args, ("WebDAV 密码", VALUES["webdav_password"]))
        self.assertIn("可能已更改", ui.reveal.call_args_list[2].args[0])
        self.assertEqual((self.directory / ".env").read_bytes(), self.raw)

    def test_failed_https_resume_never_prompts_for_credentials(self):
        manager, ui = Mock(), Mock()
        manager.configure.side_effect = RuntimeError("fixture HTTPS failure")
        plan = tgdep_install.Plan(self.instance, "current", manager, self.instance.config,
                        "files.example.test", configure_https=True)
        with patch.object(tgdep_install, "edition_lock", return_value=nullcontext()), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=self.instance), self.assertRaisesRegex(RuntimeError, "HTTPS failure"):
            tgdep_install.execute_plan(plan, RELEASE, ROOT, ROOT, Mock(), self.log, ui)
        ui.reveal.assert_not_called()

    def test_explicit_credential_view_never_resolves_release_or_executes_plan(self):
        ui = Mock()
        with patch.object(tgdep_preflight, "validate_host"), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=self.instance), patch.object(tgdep_terminal, "Terminal", return_value=ui), patch.object(tgdep_releases, "ReleaseClient") as release, patch.object(tgdep_install, "execute_plan") as execute, patch.object(cli, "SafeLog", return_value=self.log):
            self.assertEqual(tgdep_vps.main(["--edition", "openlist", "--show-credentials"]), 0)
        release.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(ui.reveal.call_count, 3)
        self.assertEqual((self.directory / ".env").read_bytes(), self.raw)

    def test_credential_view_rejects_check_and_mutating_flags(self):
        for option in ("--check", "--configure-https", "--verify"):
            with self.subTest(option=option), patch.object(tgdep_preflight, "validate_host") as validate, patch.object(tgdep_terminal, "Terminal") as terminal, patch.object(cli, "SafeLog", return_value=self.log):
                self.assertEqual(tgdep_vps.main(["--edition", "openlist", "--show-credentials", option]), 1)
            validate.assert_not_called()
            terminal.assert_not_called()

    def test_credential_view_requires_explicit_edition(self):
        with patch.object(tgdep_preflight, "validate_host") as validate, patch.object(tgdep_terminal, "Terminal") as terminal, patch.object(cli, "SafeLog", return_value=self.log):
            self.assertEqual(tgdep_vps.main(["--show-credentials"]), 1)
        validate.assert_not_called()
        terminal.assert_not_called()

    def test_ordinary_upgrade_does_not_offer_or_reset_credentials(self):
        manager, ui = Mock(), Mock()
        manager.status.return_value = report()
        plan = tgdep_install.Plan(self.instance, "upgrade", manager, self.instance.config)
        with patch.object(tgdep_install, "edition_lock", return_value=nullcontext()), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=self.instance), patch.object(tgdep_preflight, "resource_check"), patch.object(tgdep_install, "apply_base"), patch.object(tgdep_install, "verify_destination") as verify:
            tgdep_install.execute_plan(plan, RELEASE, ROOT, ROOT, Mock(), self.log, ui)
        ui.reveal.assert_not_called()
        manager.configure.assert_not_called()
        verify.assert_not_called()

    def test_final_resource_recheck_stops_before_base_or_https_changes(self):
        manager = Mock()
        plan = tgdep_install.Plan(self.instance, "upgrade", manager, self.instance.config)
        with patch.object(tgdep_install, "edition_lock", return_value=nullcontext()), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=self.instance), patch.object(tgdep_preflight, "resource_check", side_effect=ValueError("资源不足")), patch.object(tgdep_install, "apply_base") as apply, self.assertRaisesRegex(ValueError, "资源不足"):
            tgdep_install.execute_plan(plan, RELEASE, ROOT, ROOT, Mock(), self.log, Mock())
        apply.assert_not_called()
        manager.configure.assert_not_called()

    def test_credential_view_does_not_install_when_instance_absent(self):
        absent = tgdep_instances.Instance(self.product, self.directory, False)
        with patch.object(tgdep_preflight, "validate_host"), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=absent), patch.object(tgdep_terminal, "Terminal") as terminal, patch.object(tgdep_releases, "ReleaseClient") as release, patch.object(cli, "SafeLog", return_value=self.log):
            self.assertEqual(tgdep_vps.main(["--edition", "openlist", "--show-credentials"]), 1)
        terminal.assert_not_called()
        release.assert_not_called()

    def test_fresh_plan_missing_host_tools_stops_before_collecting_secrets(self):
        absent = tgdep_instances.Instance(self.product, self.directory, False)
        manager, ui = Mock(), Mock()
        manager.read_state.return_value = {"domains": {}}
        manager.status.return_value = report("not_configured", "")
        manager.probe.side_effect = RuntimeError("VPS 缺少宿主依赖：ss, ip；安装 iproute2")
        ui.ask.side_effect = ["files.example.test", ""]
        with patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_install, "DomainProxyManager", return_value=manager), patch.object(tgdep_terminal, "collect_config") as collect, patch.object(tgdep_preflight, "resource_check") as resources, self.assertRaisesRegex(RuntimeError, "iproute2"):
            tgdep_install.make_plan(absent, RELEASE, ROOT, None, Mock(), self.log, ui)
        collect.assert_not_called()
        resources.assert_not_called()

    def test_main_cancelled_and_readonly_never_mutate(self):
        baseline = patch.object(tgdep_releases, "download_baseline", return_value=ROOT)
        baseline.start()
        self.addCleanup(baseline.stop)
        plan = tgdep_install.Plan(self.instance, "upgrade", Mock())
        for args in (["--edition", "openlist"], ["--edition", "openlist", "--check"]):
            ui = Mock()
            ui.confirm.return_value = False
            client = Mock()
            client.resolve.side_effect = [RELEASE, tgdep_releases.Release("v" + self.instance.version, "b" * 40)]
            client.download.return_value = ROOT
            with self.subTest(args=args), patch.object(tgdep_preflight, "validate_host"), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_instances, "discover", return_value=self.instance), patch.object(tgdep_releases, "ReleaseClient", return_value=client), patch.object(tgdep_terminal, "Terminal", return_value=ui), patch.object(tgdep_install, "make_plan", return_value=plan), patch.object(tgdep_install, "execute_plan") as execute, patch.object(cli, "SafeLog", return_value=self.log):
                self.assertEqual(tgdep_vps.main(args), 0)
            execute.assert_not_called()

    def test_wizard_defaults_to_single_detected_edition_not_a_new_install(self):
        baseline = patch.object(tgdep_releases, "download_baseline", return_value=ROOT)
        baseline.start()
        self.addCleanup(baseline.stop)
        ui = Mock()
        ui.ask.return_value = "2"
        ui.confirm.return_value = False
        client = Mock()
        client.resolve.side_effect = [RELEASE, tgdep_releases.Release("v" + self.instance.version, "b" * 40)]
        client.download.return_value = ROOT
        # New interactive preflight checks ownership of the offline command;
        # the test must not inspect or write a real host command directory.
        check_patch = patch.object(cli.runtime, "check_destination")
        check_patch.start()
        self.addCleanup(check_patch.stop)
        install_patch = patch.object(cli.runtime, "install")
        runtime_install = install_patch.start()
        self.addCleanup(install_patch.stop)
        with patch.object(tgdep_preflight, "validate_host"), patch.object(tgdep_instances, "docker_inventory", return_value={self.product.bot_container, self.product.storage_container}), patch.object(tgdep_instances, "discover", return_value=self.instance) as discover, patch.object(tgdep_releases, "ReleaseClient", return_value=client), patch.object(tgdep_terminal, "Terminal", return_value=ui), patch.object(tgdep_install, "make_plan", return_value=tgdep_install.Plan(self.instance, "upgrade", Mock())), patch.object(tgdep_install, "execute_plan") as execute, patch.object(cli, "SafeLog", return_value=self.log):
            self.assertEqual(tgdep_vps.main([]), 0)
        self.assertEqual(ui.ask.call_args.kwargs["default"], "2")
        self.assertEqual(discover.call_args.args[0].key, "openlist")
        execute.assert_not_called()
        runtime_install.assert_not_called()

    def test_resource_gate_uses_existing_assessment(self):
        session = Mock()
        session.run.return_value = (0, "probe fixture")
        with patch.object(tgdep_preflight, "build_probe_command", return_value="probe"), patch.object(tgdep_preflight, "parse_probe_output", return_value=Mock()), patch.object(tgdep_preflight, "assess_storage_choice", return_value=StorageAssessment(False, 100, "insufficient")), self.assertRaisesRegex(ValueError, "资源不足"):
            tgdep_preflight.resource_check(self.instance, self.instance.config, session, self.log)

    def test_fresh_config_requires_safe_dns_ports(self):
        fresh = tgdep_instances.Instance(self.product, self.directory, False)
        manager = Mock()
        manager.read_state.return_value = {"domains": {}}
        manager.status.return_value = report("not_configured", "")
        manager.probe.return_value = ProxyEnvironment("FAILED", "FAILED", "FREE", "FREE", ("203.0.113.10",), (), ("203.0.113.20",))
        ui = Mock()
        ui.ask.side_effect = ["files.example.test", ""]
        session = Mock()
        session.run.return_value = (0, "")
        with patch.object(tgdep_install, "DomainProxyManager", return_value=manager), patch.object(tgdep_instances, "docker_inventory", return_value=set()), self.assertRaisesRegex(ValueError, "DNS"):
            tgdep_install.make_plan(fresh, RELEASE, ROOT, None, session, self.log, ui)
        manager.configure.assert_not_called()

    def test_fresh_collects_but_never_installs_before_confirmation(self):
        fresh = tgdep_instances.Instance(self.product, self.directory, False)
        manager = Mock()
        manager.read_state.return_value = {"domains": {}}
        manager.status.return_value = report("not_configured", "")
        manager.probe.return_value = ProxyEnvironment("FAILED", "FAILED", "FREE", "FREE", ("203.0.113.10",), (), ("203.0.113.10",))
        ui = Mock()
        ui.ask.side_effect = ["files.example.test", ""]
        session = Mock()
        session.run.return_value = (1, "")  # Docker missing on a fresh VPS
        with patch.object(tgdep_install, "DomainProxyManager", return_value=manager), patch.object(tgdep_instances, "docker_inventory", return_value=set()), patch.object(tgdep_preflight, "choose_storage", return_value=("8", "8")) as storage, patch.object(tgdep_terminal, "collect_config", return_value=tgdep_configuration.new_config(self.product, VALUES)) as collect, patch.object(tgdep_preflight, "resource_check"), patch.object(tgdep_install, "apply_base") as apply:
            plan = tgdep_install.make_plan(fresh, RELEASE, ROOT, None, session, self.log, ui)
        storage.assert_called_once_with(fresh, session, self.log, ui)
        collect.assert_called_once_with(ui, self.product, storage=("8", "8"))
        self.assertTrue(plan.configure_https)
        self.assertEqual(plan.domain, "files.example.test")
        apply.assert_not_called()
        manager.configure.assert_not_called()

    def test_explicit_https_resume_reuses_domain(self):
        manager = Mock()
        manager.read_state.return_value = {"domains": {"openlist": {"domain": "original.example.test"}}}
        manager.status.return_value = report("running_error", "original.example.test")
        manager.detect.return_value = report("detected", "original.example.test")
        ui = Mock()
        ui.ask.return_value = ""
        current = tgdep_releases.Release("v" + self.instance.version, "b" * 40)
        with patch.object(tgdep_install, "DomainProxyManager", return_value=manager):
            plan = tgdep_install.make_plan(self.instance, current, ROOT, ROOT, Mock(), self.log, ui, configure_https=True)
        self.assertEqual(plan.domain, "original.example.test")
        self.assertTrue(plan.configure_https)
        self.assertEqual(ui.ask.call_count, 1)  # optional email only, never a domain switch
        manager.configure.assert_not_called()

    def test_unhealthy_https_blocks_implicit_upgrade(self):
        manager = Mock()
        manager.read_state.return_value = {"domains": {}}
        manager.status.return_value = report("not_configured", "")
        session = Mock()
        session.run.return_value = (0, "")
        with patch.object(tgdep_install, "DomainProxyManager", return_value=manager), self.assertRaisesRegex(ValueError, "HTTPS"):
            tgdep_install.make_plan(self.instance, RELEASE, ROOT, ROOT, session, self.log, Mock())

    def test_same_version_and_newer_never_call_base_installer(self):
        for action in ("current", "newer"):
            with self.subTest(action=action):
                session = Mock()
                tgdep_install.apply_base(tgdep_install.Plan(self.instance, action, Mock()), RELEASE, ROOT, session, self.log)
                session.run.assert_not_called()

    def test_linux_permissions_are_checked_before_loading_secrets(self):
        if os.name != "posix":
            self.skipTest("POSIX owner and mode checks")
        path = self.directory / ".env"
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "root"):
            tgdep_configuration.regular_private(path)


class LocalRuntimeTests(unittest.TestCase):
    def test_local_adapter_rejects_arbitrary_sftp_targets(self):
        for path in ("/etc/passwd", "/tmp/unknown/file", "/tmp/tg2cloud-proxy-" + "a" * 32 + "/../escape"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                LocalFiles.validate(path)

    @unittest.skipUnless(os.name == "posix", "Linux flock integration; Windows is not a target VPS")
    def test_edition_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as private:
            path = Path(private) / "locks" / "openlist.lock"
            with edition_lock(path), self.assertRaises(RuntimeError), edition_lock(path):
                pass
            with edition_lock(path):
                pass

    def bash(self):
        result = shutil.which("bash")
        if not result and os.name == "nt":
            git = shutil.which("git")
            result = str(Path(git).parents[1] / "bin/bash.exe") if git else None
        if not result:
            self.skipTest("Bash unavailable")
        return result

    def test_stream_redaction_and_exit(self):
        messages = []
        log = SafeLog(messages.append)
        log.register({"BOT_TOKEN_B64": tgdep_configuration.encoded(VALUES["bot_token"])})
        session = LocalSession(log, bash=self.bash())
        code, output = session.run("printf '%s\\n' '" + VALUES["bot_token"] + "'; exit 7", stream=log, timeout=10)
        self.assertEqual(code, 7)
        self.assertIn(VALUES["bot_token"], output)  # private parser output only
        self.assertNotIn(VALUES["bot_token"], "".join(messages))

    @unittest.skipUnless(os.name == "posix", "Linux process-group cancellation")
    def test_timeout_kills_only_own_command(self):
        session = LocalSession(SafeLog(lambda _text: None), bash=self.bash())
        with self.assertRaises(TimeoutError):
            session.run("sleep 30", timeout=0.1)

    def test_entry_bash_syntax(self):
        result = subprocess.run([self.bash(), "-n", str(ROOT / "install.sh")], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.name == "posix", "Linux process substitution and bootstrap cleanup")
    def test_process_substitution_forwards_args_exit_and_cleans_bootstrap(self):
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
                command += "bash <(cat " + shlex.quote(str(ROOT / "install.sh")) + ") --edition clouddrive2 --check"
                env = {**os.environ, "FIXTURE_DIR": private, "FIXTURE_BOOTSTRAP_EXIT": str(bootstrap_exit), "FIXTURE_CLI_EXIT": str(cli_exit)}
                result = subprocess.run([self.bash(), "-c", command], cwd=private, env=env, capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, bootstrap_exit or cli_exit, result.stderr)
                fixture = Path(private)
                self.assertFalse(Path((fixture / "bootstrap-path").read_text().strip()).exists())
                if bootstrap_exit:
                    self.assertFalse((fixture / "cli-args").exists())
                else:
                    self.assertEqual((fixture / "cli-args").read_text().splitlines(), ["-B", "scripts/run_source.py", "install", "--edition", "clouddrive2", "--check"])

    def test_help_without_root_or_qt(self):
        import sys
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/run_source.py"), "install", "--help"], cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--configure-https", result.stdout)

    def test_cli_does_not_import_desktop_dependencies(self):
        source = (ROOT / "src/tg2cloud/cli/vps.py").read_text(encoding="utf-8")
        for module in ("legacy", "PySide6", "paramiko"):
            self.assertNotIn(module, [node.name for node in ast.walk(ast.parse(source))
                                     if isinstance(node, ast.alias)])

    def test_bootstrap_python_is_syntactically_valid(self):
        content = (ROOT / "install.sh").read_text(encoding="utf-8")
        embedded = content.split("<<'PY' &\n", 1)[1].split("\nPY\n", 1)[0]
        ast.parse(embedded)
        self.assertNotIn("/main/", embedded)
        self.assertIn(".bootstrap-release.json", embedded)


if __name__ == "__main__":
    unittest.main()
