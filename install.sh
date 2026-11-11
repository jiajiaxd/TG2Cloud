#!/usr/bin/env bash
# Linux install/upgrade entry. Windows deployers are frozen at v1.2.1.
set -Eeuo pipefail
umask 077

if ! command -v python3 >/dev/null 2>&1; then
  printf '需要 Python 3.10+。Debian/Ubuntu 可先手动执行：apt-get update && apt-get install -y python3 ca-certificates\n' >&2
  exit 2
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 2)' || {
  printf '需要 Python 3.10 或更高版本；未安装任何依赖。\n' >&2
  exit 2
}

script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "$script_root/src/tg2cloud/cli/commands.py" && -f "$script_root/scripts/run_source.py" ]]; then
  exec python3 -B "$script_root/scripts/run_source.py" install "$@"
fi
if [[ -f "$script_root/scripts/vps_installer.py" && -f "$script_root/scripts/vps_runtime.py" ]]; then
  cd -- "$script_root"
  exec python3 -B -m scripts.vps_installer "$@"
fi

# Standalone bootstrap: the wizard uses a reviewed, immutable source commit.
# The installed payload still comes only from the latest stable Release.
# Never install main/RC payloads or packages before wizard confirmation.
bootstrap_dir="$(mktemp -d /tmp/tg2cloud-cli-bootstrap.XXXXXXXX)"
child_pid=""
cleanup() {
  case "$bootstrap_dir" in
    /tmp/tg2cloud-cli-bootstrap.*)
      [[ -d "$bootstrap_dir" && ! -L "$bootstrap_dir" ]] && rm -rf -- "$bootstrap_dir"
      ;;
  esac
  return 0
}
trap cleanup EXIT
cancel() {
  if [[ -n "$child_pid" ]]; then
    kill -TERM -- "$child_pid" 2>/dev/null || true
    # Give the existing installer rollback time before deleting helper files.
    wait "$child_pid" 2>/dev/null || true
  fi
  exit 130
}
trap cancel INT TERM HUP
python3 - "$bootstrap_dir" <<'PY' &
import ast
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

root = Path(sys.argv[1])
api = "https://api.github.com/repos/jiajiaxd/TG2Cloud"
# Update this pin only after the helper revision passes its CI and review.
# It is independent of the target Release, which need not contain the CLI.
installer_commit = "60862325931197915ea8058261cca0f5f74599b3"
installer_version = "1.5.10"

def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in
        {"api.github.com", "raw.githubusercontent.com"}
        or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("invalid public download URL")

class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)

def fetch(url):
    validate_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "TG2Cloud-VPS-bootstrap"})
    with urllib.request.build_opener(PublicRedirect()).open(request, timeout=30) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("oversize response")
    return data

try:
    if not re.fullmatch(r"[0-9a-f]{40}", installer_commit):
        raise ValueError("invalid installer commit")
    release = json.loads(fetch(api + "/releases/latest"))
    tag = release.get("tag_name", "")
    if release.get("draft") is not False or release.get("prerelease") is not False or not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise ValueError("not a stable release")
    item = json.loads(fetch(api + "/git/ref/tags/" + tag))["object"]
    for _ in range(5):
        sha = item["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("invalid commit")
        if item["type"] == "commit":
            break
        if item["type"] != "tag":
            raise ValueError("invalid ref")
        item = json.loads(fetch(api + "/git/tags/" + sha))["object"]
    else:
        raise ValueError("tag recursion")
    files = (
        'packaging/compose/docker-compose.clouddrive2.yml',
        'packaging/compose/docker-compose.openlist.yml',
        'scripts/run_source.py',
        'src/tg2cloud/__init__.py',
        'src/tg2cloud/addons/__init__.py',
        'src/tg2cloud/addons/external_webdav/__init__.py',
        'src/tg2cloud/addons/external_webdav/__main__.py',
        'src/tg2cloud/addons/external_webdav/cli.py',
        'src/tg2cloud/addons/external_webdav/config.py',
        'src/tg2cloud/addons/external_webdav/discovery.py',
        'src/tg2cloud/addons/external_webdav/entry.py',
        'src/tg2cloud/addons/external_webdav/nginx.py',
        'src/tg2cloud/addons/external_webdav/releases.py',
        'src/tg2cloud/addons/external_webdav/scope.py',
        'src/tg2cloud/addons/external_webdav/service.py',
        'src/tg2cloud/addons/external_webdav/users.py',
        'src/tg2cloud/addons/external_webdav/verification.py',
        'src/tg2cloud/cli/__init__.py',
        'src/tg2cloud/cli/__main__.py',
        'src/tg2cloud/cli/commands.py',
        'src/tg2cloud/cli/management.py',
        'src/tg2cloud/cli/naming.py',
        'src/tg2cloud/cli/presentation.py',
        'src/tg2cloud/cli/proxy.py',
        'src/tg2cloud/cli/terminal.py',
        'src/tg2cloud/cli/vps.py',
        'src/tg2cloud/compose/__init__.py',
        'src/tg2cloud/compose/__main__.py',
        'src/tg2cloud/compose/access.py',
        'src/tg2cloud/compose/https.py',
        'src/tg2cloud/compose/lifecycle.py',
        'src/tg2cloud/compose/maintenance.py',
        'src/tg2cloud/compose/management.py',
        'src/tg2cloud/compose/packaging.py',
        'src/tg2cloud/compose/releases.py',
        'src/tg2cloud/compose/runtime.py',
        'src/tg2cloud/compose/webdav.py',
        'src/tg2cloud/config.py',
        'src/tg2cloud/deployment/__init__.py',
        'src/tg2cloud/deployment/architecture.py',
        'src/tg2cloud/deployment/backup.py',
        'src/tg2cloud/deployment/baselines.py',
        'src/tg2cloud/deployment/check.py',
        'src/tg2cloud/deployment/compatibility.py',
        'src/tg2cloud/deployment/configuration.py',
        'src/tg2cloud/deployment/diagnostics.py',
        'src/tg2cloud/deployment/feature_settings.py',
        'src/tg2cloud/deployment/fingerprints.py',
        'src/tg2cloud/deployment/host.py',
        'src/tg2cloud/deployment/install.py',
        'src/tg2cloud/deployment/instances.py',
        'src/tg2cloud/deployment/listening.py',
        'src/tg2cloud/deployment/payload.py',
        'src/tg2cloud/deployment/preflight.py',
        'src/tg2cloud/deployment/profiles.py',
        'src/tg2cloud/deployment/proxy/__init__.py',
        'src/tg2cloud/deployment/proxy/certificates.py',
        'src/tg2cloud/deployment/proxy/docker_nginx.py',
        'src/tg2cloud/deployment/proxy/external_config.py',
        'src/tg2cloud/deployment/proxy/external_entry.py',
        'src/tg2cloud/deployment/proxy/external_transaction.py',
        'src/tg2cloud/deployment/proxy/lan.py',
        'src/tg2cloud/deployment/proxy/maintenance.py',
        'src/tg2cloud/deployment/proxy/manager.py',
        'src/tg2cloud/deployment/proxy/rendering.py',
        'src/tg2cloud/deployment/proxy/state.py',
        'src/tg2cloud/deployment/readiness.py',
        'src/tg2cloud/deployment/releases.py',
        'src/tg2cloud/deployment/resources.py',
        'src/tg2cloud/deployment/runtime.py',
        'src/tg2cloud/deployment/uninstall.py',
        'src/tg2cloud/deployment/upgrade.py',
        'src/tg2cloud/deployment/users.py',
        'src/tg2cloud/domain/__init__.py',
        'src/tg2cloud/domain/naming.py',
        'src/tg2cloud/persistence/__init__.py',
        'src/tg2cloud/persistence/backup.py',
        'src/tg2cloud/persistence/bundle.py',
        'src/tg2cloud/persistence/paths.py',
        'src/tg2cloud/version.py',
    )
    for name in files:
        data = fetch("https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/" + installer_commit + "/" + name)
        target = root / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as output:
            os.chmod(target, 0o600)
            output.write(data)
    tree = ast.parse((root / "src/tg2cloud/version.py").read_text(encoding="utf-8"))
    versions = [n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Constant)
                and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets)]
    if versions != [installer_version]:
        raise ValueError("installer source version mismatch")
    marker = root / ".bootstrap-release.json"
    with marker.open("x", encoding="utf-8") as output:
        os.chmod(marker, 0o600)
        json.dump({"tag": tag, "commit": sha, "installer_commit": installer_commit}, output)
    print("TG2Cloud 安装向导：v" + installer_version)
    print("部署目标为正式稳定版本：" + tag)
except Exception:
    print("安装向导或稳定 Release 获取失败。请检查网络/限流；不会改用 main/RC 的部署代码，未修改 VPS 实例。", file=sys.stderr)
    sys.exit(2)
PY
child_pid="$!"
wait "$child_pid"
child_pid=""
cd -- "$bootstrap_dir"
python3 -B scripts/run_source.py install "$@" &
child_pid="$!"
wait "$child_pid"
child_pid=""
