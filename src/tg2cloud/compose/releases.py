"""Immutable official Compose bundles; never execute moving main or tag guesses."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

from tg2cloud.addons.external_webdav.releases import read_asset
from tg2cloud.compose import packaging, runtime
from tg2cloud.deployment import releases


def verify_tools(root: Path, *, require_manager: bool = True) -> dict:
    tools = root / "https-tools"
    manifest = tools / "manifest.json"
    if (tools.resolve() != tools or tools.is_symlink() or manifest.is_symlink()
            or not manifest.is_file() or manifest.stat().st_nlink != 1 or manifest.stat().st_size > 256 * 1024):
        raise ValueError("Compose 离线工具清单不安全")
    body = manifest.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    for name in (("https.sh", "manage.sh") if require_manager else ("https.sh",)):
        launcher = root / name
        if (launcher.is_symlink() or not launcher.is_file() or launcher.stat().st_nlink != 1
                or launcher.stat().st_size > 16384 or launcher.resolve() != launcher):
            raise ValueError("Compose 管理入口缺失或不安全")
        pins = re.findall(r'hexdigest\(\) != "([a-f0-9]{64})"', launcher.read_text(encoding="utf-8"))
        if pins != [digest]:
            raise ValueError("Compose 管理入口与离线清单不一致")
    value = json.loads(body)
    if (not isinstance(value, dict) or set(value) != {"format", "files"}
            or type(value.get("format")) is not int or value["format"] != 1
            or not isinstance(value.get("files"), dict) or not 1 <= len(value["files"]) <= 500):
        raise ValueError("Compose 离线清单无法识别")
    for name, expected in value["files"].items():
        relative = PurePosixPath(name)
        allowed = (name == "scripts/run_source.py" or name in {
            "packaging/compose/docker-compose.clouddrive2.yml", "packaging/compose/docker-compose.openlist.yml"}
            or bool(re.fullmatch(r"src/tg2cloud/(?:[a-z_][a-z0-9_]*/)*[a-z_][a-z0-9_]*\.py", name)))
        if (not allowed or relative.is_absolute() or relative.as_posix() != name or ".." in relative.parts
                or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)
                ):
            raise ValueError("Compose 离线工具完整性检查失败")
    expected_files = {*value["files"], "manifest.json"}
    directories = {parent.as_posix() for name in expected_files for parent in PurePosixPath(name).parents
                   if parent != PurePosixPath(".")}
    actual = set()
    for directory, names, leaves in os.walk(tools, followlinks=False):
        for name in names + leaves:
            path = Path(directory) / name
            relative = path.relative_to(tools).as_posix()
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode) and relative in directories:
                continue
            if (not stat.S_ISREG(info.st_mode) or relative not in expected_files or info.st_nlink != 1
                    or info.st_size > 2 * 1024**2):
                raise ValueError("Compose 离线工具包含未知资源、目录或链接")
            if relative != "manifest.json" and hashlib.sha256(path.read_bytes()).hexdigest() != value["files"][relative]:
                raise ValueError("Compose 离线工具完整性检查失败")
            actual.add(relative)
    if actual != expected_files:
        raise ValueError("Compose 离线工具不完整")
    return value


def download(edition: str, destination: Path, *, tag=None, client=None) -> Path:
    if edition not in {"clouddrive2", "openlist"}:
        raise ValueError("必须明确选择 Edition")
    client = client or releases.ReleaseClient()
    release = client.resolve(tag)
    metadata = client.json(releases.API + "/releases/tags/" + release.tag)
    if (metadata.get("tag_name") != release.tag or metadata.get("draft") is not False
            or metadata.get("prerelease") is not False):
        raise ValueError("只接受正式稳定 Compose 发布包")
    name = f"TG2Cloud-{release.tag}-compose-{edition}.tar.gz"
    assets = metadata.get("assets", [])
    urls = {}
    for expected in (name, "COMPOSE-SHA256SUMS.txt"):
        matches = [item for item in assets if item.get("name") == expected]
        expected_url = f"https://github.com/jiajiaxd/TG2Cloud/releases/download/{release.tag}/{expected}"
        if len(matches) != 1 or matches[0].get("browser_download_url") != expected_url:
            raise ValueError("正式 Compose 资产未齐或地址不属于当前仓库和 Tag")
        urls[expected] = expected_url
    sums = read_asset(urls["COMPOSE-SHA256SUMS.txt"], 16384).decode("ascii")
    hashes = re.findall(r"^([0-9a-f]{64})  " + re.escape(name) + r"$", sums, re.MULTILINE)
    body = read_asset(urls[name], releases.MAX_ARCHIVE)
    if len(hashes) != 1 or hashlib.sha256(body).hexdigest() != hashes[0]:
        raise ValueError("Compose 发布包校验失败；不会使用 main")
    archive = destination / name
    with archive.open("xb") as writer:
        writer.write(body)
    root = destination / "bundle"
    releases.extract_source(archive, root)
    verify_tools(root)
    info = runtime.metadata(root, expected_version=release.version)
    if (info.get("edition") != edition or info.get("version") != release.version or info.get("commit") != release.commit
            or info.get("format") != 3 or releases.source_version(root / "https-tools") != release.version
            or not re.search(r"@sha256:[a-f0-9]{64}$", info["image"])
            or (root / "docker-compose.yml").read_text(encoding="utf-8") != packaging.render(root / "https-tools", edition, info["image"])
            or client.resolve(release.tag) != release):
        raise ValueError("Compose 包、工具、Edition、Tag 或提交身份不一致")
    return root
