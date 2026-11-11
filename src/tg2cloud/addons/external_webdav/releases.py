"""Stable, checksummed add-on sources and offline host-only runtime selection."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from tg2cloud.deployment import releases as core

FEATURE = "packaging/external-webdav.json"
CONTRACT = {"api": 2, "proxy_schema": 2, "owner": "tg2cloud.external_webdav"}
LEGACY_CONTRACT = dict(CONTRACT, api=1)


def contract(root: Path) -> dict:
    """Read a static capability marker; never infer a layout from missing files."""
    path = root / FEATURE
    try:
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("此稳定 Release 尚不包含受支持的外部 WebDAV；不会回退执行 main 或旧辅助代码。") from exc
    if not isinstance(value, dict) or type(value.get("api")) is not int or value not in (CONTRACT, LEGACY_CONTRACT):
        raise ValueError("不支持的外部 WebDAV 发布协议。")
    return value


def host_files(root: Path) -> list[str]:
    files = ["scripts/run_source.py", "src/tg2cloud/__init__.py", "src/tg2cloud/version.py", "src/tg2cloud/config.py",
             FEATURE]
    if contract(root) == LEGACY_CONTRACT:
        files.append("install-webdav.sh")
    else:
        files.extend(("src/tg2cloud/cli/commands.py", "src/tg2cloud/cli/management.py",
                      "src/tg2cloud/deployment/uninstall.py", "src/tg2cloud/addons/external_webdav/entry.py",
                      "src/tg2cloud/addons/external_webdav/cli.py", "src/tg2cloud/addons/external_webdav/service.py"))
        if any((root / name).exists() or (root / name).is_symlink() for name in ("uninstall.sh", "install-webdav.sh")):
            raise ValueError("统一管理源码仍包含已退役的独立 Shell 入口。")
    for directory in ("cli", "deployment", "addons"):
        files.extend(path.relative_to(root).as_posix() for path in (root / "src/tg2cloud" / directory).rglob("*.py"))
    for relative in files:
        path = root / relative
        if not path.is_file() or path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError("离线维护源码缺失或经过链接。")
    return sorted(set(files))


def supported(root: Path) -> None:
    host_files(root)


def valid_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"github.com", "release-assets.githubusercontent.com"}
            or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("只允许 GitHub 正式 HTTPS 发布资源。")


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        valid_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def read_asset(url: str, limit: int) -> bytes:
    valid_url(url)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "TG2Cloud-external-WebDAV"})
        with urllib.request.build_opener(Redirect()).open(request, timeout=60) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("发布资源超过安全上限。")
        return body
    except OSError as exc:
        raise ValueError("正式发布资源下载失败；不输出带令牌重定向 URL，不使用 main。") from exc


def download(destination: Path) -> tuple[Path, dict]:
    client = core.ReleaseClient()
    release = client.resolve()
    metadata = client.json(core.API + "/releases/tags/" + release.tag)
    if metadata.get("draft") is not False or metadata.get("prerelease") is not False or metadata.get("tag_name") != release.tag:
        raise ValueError("正式发布元数据变化。")
    name = f"TG2Cloud-{release.tag}-source.tar.gz"
    assets = metadata.get("assets", [])
    urls = {}
    for expected in (name, "SHA256SUMS.txt"):
        found = [asset for asset in assets if asset.get("name") == expected]
        if len(found) != 1:
            raise ValueError("稳定 Release 缺少唯一源码包／SHA256 清单；不使用未校验代码。")
        url = found[0].get("browser_download_url", "")
        if url != f"https://github.com/jiajiaxd/TG2Cloud/releases/download/{release.tag}/{expected}":
            raise ValueError("发布资源不属于预期仓库和 Tag。")
        urls[expected] = url
    sums = read_asset(urls["SHA256SUMS.txt"], 16384).decode("ascii")
    matches = re.findall(r"^([0-9a-f]{64})  " + re.escape(name) + r"$", sums, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("源码包缺少唯一 SHA256；校验和不是数字签名。")
    body = read_asset(urls[name], core.MAX_ARCHIVE)
    if hashlib.sha256(body).hexdigest() != matches[0]:
        raise ValueError("源码包校验失败。")
    archive = destination / name
    with archive.open("xb") as writer:
        writer.write(body)
    archive.chmod(0o600)
    root = destination / "source"
    core.extract_source(archive, root)
    supported(root)
    if core.source_version(root) != release.version or client.resolve(release.tag) != release:
        raise ValueError("版本或正式 Tag 标识在下载期间变化。")
    return root, {"tag": release.tag, "commit": release.commit, "archive_sha256": matches[0], "source": "stable-release"}
