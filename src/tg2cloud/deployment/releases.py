from __future__ import annotations

import json
import re
import shutil
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tg2cloud.deployment.compatibility import literal_version

API = "https://api.github.com/repos/jiajiaxd/TG2Cloud"
TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SHA = re.compile(r"[0-9a-f]{40}")
MAX_ARCHIVE = 100 * 1024 * 1024


class ReleaseLookupError(RuntimeError):
    """Classified public lookup error; never include a remote response body."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def download_baseline(client, tag: str, destination: Path, log) -> Path:
    from tg2cloud.deployment import baselines

    if not TAG.fullmatch(tag):
        raise ValueError("历史基线必须是正式版本")
    record = baselines.CATALOG.get(tag)
    if record:
        release = Release(tag, record["commit"])
        source = client.download(release, destination)
        baselines.verify(source, tag, release.commit)
        log("历史源码基线：" + tag + "；本版可信目录核验通过（仍需比对实例文件）")
        return source
    return client.download(client.resolve(tag), destination)


def validate_public_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {
        "api.github.com", "codeload.github.com", "raw.githubusercontent.com",
    } or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("下载地址必须是公开 GitHub HTTPS 地址")


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_public_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def open_public(url: str, *, timeout: float):
    validate_public_url(url)
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "TG2Cloud-VPS-installer",
    })
    return urllib.request.build_opener(PublicRedirect()).open(request, timeout=timeout)


def version_tuple(version: str) -> tuple[int, int, int]:
    match = TAG.fullmatch("v" + version)
    if not match:
        raise ValueError("版本号不是正式 X.Y.Z 格式")
    return tuple(map(int, match.groups()))


def source_version(root: Path) -> str:
    try:
        value = literal_version(root)
        version_tuple(value)
        return value
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError("无法安全读取程序版本；不会猜测版本或覆盖实例") from exc


@dataclass(frozen=True)
class Release:
    tag: str
    commit: str

    @property
    def version(self) -> str:
        return self.tag[1:]


class ReleaseClient:
    """Public HTTPS only: no credentials, main fallback, or executable assets."""

    def json(self, url: str) -> dict:
        try:
            with open_public(url, timeout=25) as response:
                body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError("GitHub 响应过大")
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError("GitHub 响应格式不正确")  # noqa: TRY004 - invalid wire format
            return value
        except urllib.error.HTTPError as exc:
            messages = {404: "正式 Release／Tag 不存在，可能已删除；未知旧版请先备份并人工核对",
                        429: "GitHub 请求限流，请稍后重试",
                        403: "GitHub 拒绝访问或达到 API 限额，请稍后核对网络与额度"}
            raise ReleaseLookupError(messages.get(exc.code, "GitHub 服务返回 HTTP " + str(exc.code))
                                     + "；未改用 main 或修改实例", status=exc.code) from None
        except (OSError, ValueError) as exc:
            raise ReleaseLookupError("无法读取 GitHub 正式 Release；网络/TLS/超时或响应无效，不会改用 main") from exc

    def resolve(self, tag: str | None = None) -> Release:
        if tag is not None and not TAG.fullmatch(tag):
            raise ValueError("只允许正式 vX.Y.Z Tag")
        release = self.json(API + ("/releases/tags/" + tag if tag else "/releases/latest"))
        name = release.get("tag_name", "")
        if release.get("draft") is not False or release.get("prerelease") is not False or not TAG.fullmatch(name):
            raise ValueError("拒绝草稿、RC 或非正式版本")
        if tag and name != tag:
            raise ValueError("Release Tag 不一致")
        item = self.json(API + "/git/ref/tags/" + name).get("object", {})
        for _ in range(5):
            sha = item.get("sha", "")
            if not SHA.fullmatch(sha):
                raise ValueError("Release 提交标识无效")
            if item.get("type") == "commit":
                return Release(name, sha)
            if item.get("type") != "tag":
                break
            item = self.json(API + "/git/tags/" + sha).get("object", {})
        raise ValueError("无法将 Release 固定到唯一 commit")

    def download(self, release: Release, destination: Path) -> Path:
        archive = destination / (release.commit + ".tar.gz")
        try:
            url = "https://codeload.github.com/jiajiaxd/TG2Cloud/tar.gz/" + release.commit
            with open_public(url, timeout=60) as response, archive.open("xb") as writer:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE:
                        raise ValueError("源码归档过大")
                    writer.write(chunk)
            root = destination / ("source-" + release.commit)
            extract_source(archive, root)
            if source_version(root) != release.version:
                raise ValueError("Tag 与源码版本不一致")
            return root
        except (OSError, tarfile.TarError) as exc:
            raise RuntimeError("稳定版本源码下载/解包失败；未修改运行实例") from exc


def extract_source(archive: Path, root: Path) -> None:
    """Never extract links, devices, traversal, duplicates, or an archive bomb."""
    root.mkdir(mode=0o700)
    seen: set[str] = set()
    top = None
    total = 0
    with tarfile.open(archive, "r:gz") as source:
        for number, member in enumerate(source):
            parts = PurePosixPath(member.name).parts
            if (number >= 20000 or not parts or member.name.startswith("/")
                    or ".." in parts or "\\" in member.name or "\x00" in member.name
                    or not (member.isfile() or member.isdir())):
                raise ValueError("源码归档包含不安全路径或文件类型")
            if top is None:
                top = parts[0]
            if parts[0] != top:
                raise ValueError("源码归档包含多个顶层目录")
            if len(parts) == 1:
                if not member.isdir():
                    raise ValueError("源码归档顶层不是目录")
                continue
            name = "/".join(parts[1:])
            if name in seen:
                raise ValueError("源码归档包含重复路径")
            seen.add(name)
            total += member.size
            if member.size < 0 or member.size > 32 * 1024 * 1024 or total > 250 * 1024 * 1024:
                raise ValueError("源码归档解压大小超限")
            target = root.joinpath(*parts[1:])
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with source.extractfile(member) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                target.chmod(0o600)
