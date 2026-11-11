#!/usr/bin/env bash
# LAN install/management entry. Shared Python services own all operations.
set -Eeuo pipefail
umask 077

command -v python3 >/dev/null 2>&1 || {
  printf '需要 Python 3.10+；未安装任何依赖。\n' >&2
  exit 2
}
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 2)' || {
  printf '需要 Python 3.10 或更高版本。\n' >&2
  exit 2
}
script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "$script_root/src/tg2cloud/cli/commands.py" && -f "$script_root/scripts/run_source.py" ]]; then
  exec python3 -B "$script_root/scripts/run_source.py" lan "$@"
fi
if [[ -f "$script_root/scripts/lan_installer.py" && -f "$script_root/scripts/vps_installer.py" ]]; then
  cd -- "$script_root"
  exec python3 -B -m scripts.lan_installer "$@"
fi

# A remote entry must not import moving main or a revision not yet validated.
# Set this reviewed immutable pin only after the LAN module passes CI/review.
installer_commit="9aab857a40664b35eb19c67a1cb3efcfc8dc35ad"
if [[ ! "$installer_commit" =~ ^[0-9a-f]{40}$ ]]; then
  printf '内网向导固定版本配置无效；已停止，未修改系统。\n' >&2
  exit 2
fi

bootstrap_dir="$(mktemp -d /tmp/tg2cloud-lan-bootstrap.XXXXXXXX)"
child_pid=""
cleanup() {
  case "$bootstrap_dir" in
    /tmp/tg2cloud-lan-bootstrap.*) [[ -d "$bootstrap_dir" && ! -L "$bootstrap_dir" ]] && rm -rf -- "$bootstrap_dir" ;;
  esac
  return 0
}
trap cleanup EXIT
cancel() {
  if [[ -n "$child_pid" ]]; then
    kill -TERM -- "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  exit 130
}
trap cancel INT TERM HUP
python3 - "$bootstrap_dir" "$installer_commit" <<'PY' &
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

root, commit = Path(sys.argv[1]), sys.argv[2]

def validate(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("invalid public source URL")

class Redirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        validate(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)

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
try:
    for name in files:
        url = "https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/" + commit + "/" + name
        validate(url)
        with build_opener(Redirect()).open(Request(url, headers={"User-Agent": "TG2Cloud-LAN-bootstrap"}), timeout=30) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("source too large")
        target = root / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as writer:
            target.chmod(0o600)
            writer.write(data)
    print("TG2Cloud 内网安装向导源码已验证。")
except Exception:
    print("内网向导下载失败；不会改用 main/RC 或安装替代代码，未修改实例。", file=sys.stderr)
    sys.exit(2)
PY
child_pid="$!"
wait "$child_pid"
child_pid=""
cd -- "$bootstrap_dir"
python3 -B scripts/run_source.py lan "$@" &
child_pid="$!"
wait "$child_pid"
child_pid=""
