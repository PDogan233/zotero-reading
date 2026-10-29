"""Explicit, standard-library-only updates of a managed standalone Skill."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


NAME = "zotero-reading"
MANIFEST = "package-manifest.json"
MAX_DOWNLOAD = 10 * 1024 * 1024
MAX_EXPANDED = 50 * 1024 * 1024
REQUIRED = {"SKILL.md", "INSTALL.md", "run.ps1", "install.ps1", "scripts/bootstrap.py",
            "scripts/zotero_notes.py", "scripts/reading_sessions.py", "scripts/skill_updates.py",
            "references/reading-workflow.md", "references/report-format.md"}


class UpdateError(RuntimeError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", value):
        raise UpdateError("只支持major.minor.patch格式的正式版本。")
    return tuple(map(int, value.split(".")))


def repository_name(value):
    if not isinstance(value, str):
        raise UpdateError("请明确指定GitHub仓库，格式为账号/仓库名。")
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/").rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value) or value.split("/")[1] in (".", ".."):
        raise UpdateError("GitHub仓库必须是账号/仓库名或其https://github.com地址。")
    return value


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise UpdateError("包内包含不安全的文件路径。")
    parts = name.split("/")
    for part in parts:
        if (part in ("", ".", "..") or part.rstrip(" .") != part
                or re.search(r'[\x00-\x1f<>:"|?*]', part)
                or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)):
            raise UpdateError("包内包含不安全的文件路径。")
    return name


def no_links(path, recursive=False):
    path = Path(path).absolute()
    entries = list(path.parents)
    for entry in entries:
        if entry.exists() and (stat.S_ISLNK(entry.lstat().st_mode) or getattr(entry.lstat(), "st_file_attributes", 0) & 0x400):
            raise UpdateError("更新路径含符号链接或目录链接，请先核对实际安装位置。")
    entries = [path]
    while entries:
        entry = entries.pop()
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise UpdateError("更新路径含符号链接或目录链接，请先核对实际安装位置。")
        if recursive and stat.S_ISDIR(info.st_mode):
            entries.extend(entry.iterdir())


def snapshot(directory):
    no_links(directory, recursive=True)
    return {path.relative_to(directory).as_posix(): sha256(path)
            for path in Path(directory).rglob("*") if path.is_file()}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_data(value):
    if not isinstance(value, dict) or value.get("name") != NAME or not isinstance(value.get("files"), dict) or not value["files"]:
        raise UpdateError("目标不是带有效manifest的托管zotero-reading技能。")
    version_tuple(value.get("version"))
    names = set()
    for name, digest in value["files"].items():
        safe_name(name)
        folded = name.casefold()
        if folded == MANIFEST.casefold() or folded in names or not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            raise UpdateError("包的manifest存在冲突文件或无效摘要。")
        names.add(folded)
    if any(str(parent).casefold() in names for name in names for parent in PurePosixPath(name).parents if str(parent) != "."):
        raise UpdateError("包内文件和目录名称冲突。")
    return value


def installed_manifest(directory):
    no_links(directory, recursive=True)
    path = Path(directory) / MANIFEST
    try:
        return manifest_data(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise UpdateError("请指定完整的已安装Skill目录；源码项目不能直接覆盖更新。") from error


def local_changes(directory, manifest):
    changes = []
    for name, expected in manifest["files"].items():
        path = Path(directory) / name
        if not path.is_file():
            changes.append({"path": name, "kind": "missing"})
        elif sha256(path) != expected:
            changes.append({"path": name, "kind": "modified"})
    return changes


class GitHubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        url = urllib.parse.urlsplit(newurl)
        host = url.hostname or ""
        if (url.scheme != "https" or url.username or url.password
                or not (host in ("api.github.com", "github.com") or host.endswith(".githubusercontent.com"))):
            raise UpdateError("GitHub下载跳转到了未经支持的地址，停止下载。")
        return super().redirect_request(request, fp, code, message, headers, newurl)


class GitHub:
    def __init__(self):
        self.opener = urllib.request.build_opener(GitHubRedirects())

    def request(self, url, accept="application/vnd.github+json"):
        return self.opener.open(urllib.request.Request(url, headers={"Accept": accept,
            "User-Agent": "zotero-reading-skill-updater", "X-GitHub-Api-Version": "2022-11-28"}), timeout=30)

    def latest(self, repository):
        with self.request(f"https://api.github.com/repos/{repository}/releases/latest") as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise UpdateError("GitHub版本信息超出大小限制。")
        return json.loads(raw)

    def download(self, asset, destination):
        with self.request(asset["url"], "application/octet-stream") as response, Path(destination).open("wb") as stream:
            size = 0
            for block in iter(lambda: response.read(65536), b""):
                size += len(block)
                if size > MAX_DOWNLOAD or size > asset["size"]:
                    raise UpdateError("下载文件超过发行信息声明的大小。")
                stream.write(block)


def release_info(release, repository):
    if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
        raise UpdateError("仅接受GitHub已发布的正式Release。")
    tag = release.get("tag_name", "")
    version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else tag
    version_tuple(version)
    expected = f"{NAME}-{version}-skill.zip"
    if not isinstance(release.get("assets"), list):
        raise UpdateError("GitHub发行信息缺少附件列表。")
    assets = [asset for asset in release["assets"] if isinstance(asset, dict) and asset.get("name") == expected]
    if len(assets) != 1:
        raise UpdateError(f"正式Release必须且只能附带一个{expected}，源码ZIP不能代替Skill包。")
    asset = assets[0]
    url = asset.get("url", "")
    if not isinstance(url, str) or not re.fullmatch(re.escape(f"https://api.github.com/repos/{repository}/releases/assets/") + r"\d+", url, re.I):
        raise UpdateError("发行附件地址与所选GitHub仓库不一致。")
    if (asset.get("state") != "uploaded" or type(asset.get("size")) is not int
            or not 0 < asset["size"] <= MAX_DOWNLOAD):
        raise UpdateError("发行附件尚未就绪或超过大小限制。")
    if not isinstance(asset.get("digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", asset["digest"]):
        raise UpdateError("GitHub未提供附件SHA256，请发布者重新上传带digest的正式附件。")
    return {"version": version, "asset": asset,
            "release_url": f"https://github.com/{repository}/releases/tag/{urllib.parse.quote(tag, safe='')}"}


def check(directory, repository=None, github=None):
    directory = Path(directory).expanduser().absolute()
    current = installed_manifest(directory)
    directory = directory.resolve()
    repository = repository_name(repository or current.get("update_repository"))
    release = release_info((github or GitHub()).latest(repository), repository)
    newer = version_tuple(release["version"]) > version_tuple(current["version"])
    result = {"status": "update_available" if newer else "up_to_date", "repository": repository,
              "current_version": current["version"], "latest_version": release["version"],
              "skill_dir": str(directory), "release_url": release["release_url"],
              "local_changes": local_changes(directory, current)}
    return result, current, release


def unpack(package, destination, version, repository):
    """Validate the entire ZIP before writing any archive member, never extractall."""
    with zipfile.ZipFile(package) as archive:
        infos = archive.infolist()
        if len(infos) > 1000 or sum(info.file_size for info in infos) > MAX_EXPANDED:
            raise UpdateError("发行包解压大小超过限制。")
        seen, files = set(), {}
        prefix = NAME + "/"
        for info in infos:
            safe_name(info.filename.rstrip("/") if info.is_dir() else info.filename)
            if info.filename.casefold() in seen or not info.filename.startswith(prefix):
                raise UpdateError("发行包有重复文件或不属于zotero-reading目录。")
            seen.add(info.filename.casefold())
            if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK or info.flag_bits & 1:
                raise UpdateError("发行包不能包含链接或加密文件。")
            if not info.is_dir():
                files[info.filename.removeprefix(prefix)] = archive.read(info)
        try:
            manifest = manifest_data(json.loads(files[MANIFEST]))
        except (KeyError, ValueError) as error:
            raise UpdateError("发行包缺少有效manifest。") from error
        if manifest["version"] != version or repository_name(manifest.get("update_repository")).casefold() != repository.casefold():
            raise UpdateError("包内版本或更新仓库与GitHub发行信息不一致。")
        if set(files) != set(manifest["files"]) | {MANIFEST} or not REQUIRED.issubset(manifest["files"]):
            raise UpdateError("发行包文件清单不完整或包含未登记文件。")
        for name, digest in manifest["files"].items():
            if hashlib.sha256(files[name]).hexdigest() != digest:
                raise UpdateError("包内文件摘要校验失败：" + name)
        for name, data in files.items():
            if name.endswith(".py"):
                compile(data, name, "exec")
        for name, data in files.items():
            path = Path(destination) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return manifest


def healthcheck(directory, version):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(directory) / "scripts/bootstrap.py"), "--version"],
                            capture_output=True, text=True, encoding="utf-8", timeout=30, env=environment)
    if result.returncode or result.stdout.strip() != "zotero-reading " + version:
        raise UpdateError("新版入口版本检查失败，停止或恢复旧版；未连接Zotero。")


def copy_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


@contextmanager
def update_lock(directory):
    try:
        descriptor = os.open(directory, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise UpdateError("该技能有未结束的更新锁。请先核对其他更新进程；异常退出后由用户确认清理锁。") from error
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        Path(directory).unlink()


def apply(directory, data_root, repository=None, overwrite_local=False, github=None):
    directory, data_root = Path(directory).absolute(), Path(data_root).absolute()
    github = github or GitHub()
    result, current, release = check(directory, repository, github)
    directory = Path(result["skill_dir"])
    if result["status"] == "up_to_date":
        return result
    if result["local_changes"] and not overwrite_local:
        return dict(result, status="local_changes", action="发行文件有本地修改，未下载/覆盖。接收方明确同意后才使用--overwrite-local。")
    baseline = snapshot(directory)
    no_links(data_root)
    data_root = data_root.resolve()
    if data_root == directory or data_root.is_relative_to(directory) or directory.is_relative_to(data_root):
        raise UpdateError("更新数据目录与技能安装目录必须相互独立；请确认--data-dir或ZOTERO_READING_HOME。")
    work = data_root / ".local/skill-updates"
    no_links(work)
    work.mkdir(parents=True, exist_ok=True)
    identifier = hashlib.sha256(os.path.normcase(str(directory)).encode("utf-8")).hexdigest()[:16]
    with update_lock(work / (identifier + ".lock")), tempfile.TemporaryDirectory(prefix="staging-", dir=work) as temporary:
        temporary = Path(temporary)
        package, staged = temporary / "release.zip", temporary / NAME
        github.download(release["asset"], package)
        if package.stat().st_size != release["asset"]["size"] or "sha256:" + sha256(package) != release["asset"]["digest"]:
            raise UpdateError("整个下载ZIP的大小或SHA256与GitHub不一致；已安装技能未改动。")
        new = unpack(package, staged, release["version"], result["repository"])
        healthcheck(staged, new["version"])
        # A new managed filename must not silently claim a user's unrelated extra file.
        collisions = [{"path": name, "kind": "unmanaged_collision"} for name in new["files"]
                      if name not in current["files"] and (directory / name).exists()]
        if collisions and not overwrite_local:
            return dict(result, status="local_changes", local_changes=result["local_changes"] + collisions,
                        action="新版文件与本地额外文件重名；请先确认，未覆盖。")
        if installed_manifest(directory) != current or snapshot(directory) != baseline:
            raise UpdateError("下载期间技能文件发生变化，停止更新，请重新检查。")
        for name in set(new["files"]) | set(current["files"]) | {MANIFEST}:
            path = directory / name
            if path.exists() and not path.is_file():
                raise UpdateError("目标文件与已有目录冲突，请先人工核对：" + name)
            if any(parent.exists() and not parent.is_dir() for parent in path.parents if parent.is_relative_to(directory)):
                raise UpdateError("目标目录与已有文件冲突，请先人工核对：" + name)
        backup = work / ("backup-" + current["version"] + "-" + uuid.uuid4().hex)
        shutil.copytree(directory, backup)
        created = [name for name in new["files"] if not (directory / name).exists()]
        try:
            for name in new["files"]:
                copy_file(staged / name, directory / name)
            for name in set(current["files"]) - set(new["files"]):
                (directory / name).unlink(missing_ok=True)
            copy_file(staged / MANIFEST, directory / MANIFEST)
            # Same-size edits can keep a valid-looking timestamp-based .pyc cache.
            # These are generated caches, not extra user source files; backup holds them.
            for name in set(current["files"]) | set(new["files"]):
                path = directory / name
                if path.suffix == ".py":
                    cache = path.parent / "__pycache__"
                    if cache.is_dir():
                        for cached in cache.iterdir():
                            if cached.name.startswith(path.stem + ".") and cached.suffix == ".pyc":
                                cached.unlink()
            if local_changes(directory, new):
                raise UpdateError("更新后文件摘要校验失败。")
            healthcheck(directory, new["version"])
        except (Exception, KeyboardInterrupt) as error:
            try:
                for name in created:
                    (directory / name).unlink(missing_ok=True)
                shutil.copytree(backup, directory, dirs_exist_ok=True)
            except Exception as rollback_error:
                raise UpdateError(f"更新失败且自动恢复未完成。旧版备份保留于{backup}；停止使用并核对文件。") from rollback_error
            return dict(result, status="rolled_back", backup=str(backup),
                        action=f"更新失败，已恢复旧版：{type(error).__name__}。旧版及本地修改已保留。")
        return dict(result, status="updated", installed_version=new["version"], backup=str(backup),
                    data_dir=str(data_root), reload_required=True,
                    action="技能文件已更新；可在当前会话重新读取新版SKILL.md及reading-workflow.md后继续。客户端未发现更新时再刷新技能或新开会话；下一次阅读先setup，原报告不会自动重写。")


def main(argv=None, data_root=None, skill_directory=None):
    parser = argparse.ArgumentParser(description="按指令检查/更新当前已安装Skill；不操作Zotero笔记")
    parser.add_argument("action", choices=("check", "apply"))
    parser.add_argument("--repo", help="公开GitHub仓库账号/仓库；默认读取安装manifest")
    parser.add_argument("--skill-dir", type=Path, default=skill_directory or Path(__file__).resolve().parents[1])
    parser.add_argument("--overwrite-local", action="store_true", help="仅在接收方明确同意覆盖本地修改后使用")
    args = parser.parse_args(argv)
    if args.action == "check" and args.overwrite_local:
        parser.error("check不修改技能，不能使用--overwrite-local")
    try:
        if args.action == "check":
            result = check(args.skill_dir, args.repo)[0]
        else:
            if data_root is None:
                raise UpdateError("请通过run.ps1 skill-update调用，以固定使用当前数据目录。")
            result = apply(args.skill_dir, data_root, args.repo, args.overwrite_local)
    except urllib.error.HTTPError as error:
        action = ("尚无可读取的正式Release：请核对仓库是否已公开、已发布正式版及附件。"
                  if error.code == 404 else "GitHub请求失败；请检查网络、访问限制或API额度后重试，不连续自动重试。")
        result = {"status": "update_failed", "http_status": error.code, "action": action}
    except (UpdateError, OSError, ValueError, SyntaxError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        result = {"status": "update_failed", "action": str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("up_to_date", "update_available", "updated") else 2
