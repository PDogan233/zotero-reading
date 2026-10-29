"""First-use runtime setup and a stable entry point for local reading agents."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

from zotero_notes import Client, ZoteroError, default_data_root, friendly_error
from reading_sessions import timestamp, write_json


VERSION = "0.3.1"
PACKAGES = {"pypdf": "pypdf>=4,<7", "pypdfium2": "pypdfium2>=4,<6", "Pillow": "Pillow>=10,<13"}
SCRIPTS = Path(__file__).resolve().parent


class SetupError(RuntimeError):
    pass


def child_environment(python):
    environment = os.environ.copy()
    if Path(python).resolve() != Path(sys.executable).resolve():
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
    return environment


def dependency_versions(python, renderer=False):
    names = [("pypdf", "pypdf")] + ([("pypdfium2", "pypdfium2"), ("PIL", "Pillow")] if renderer else [])
    code = ("import importlib,importlib.metadata as m,json; names=" + repr(names)
            + "; [importlib.import_module(n) for n,p in names]; "
            + "print(json.dumps({p:m.version(p) for n,p in names}))")
    try:
        result = subprocess.run([str(python), "-X", "utf8", "-c", code], capture_output=True,
                                text=True, encoding="utf-8", timeout=30, env=child_environment(python))
        versions = json.loads(result.stdout) if result.returncode == 0 else None
        supported = {"pypdf": (4, 7), "pypdfium2": (4, 6), "Pillow": (10, 13)}
        if versions is not None and all(supported[n][0] <= int(v.split('.')[0]) < supported[n][1] for n, v in versions.items()):
            return versions
        return None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def runtime_python(data_root):
    return Path(data_root) / ".local/runtime" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_runtime(data_root, renderer=False, allow_install=True):
    """Reuse usable dependencies; install only into our own venv when needed."""
    managed = runtime_python(data_root)
    for python in dict.fromkeys((Path(sys.executable), managed)):
        versions = dependency_versions(python, renderer)
        if versions is not None:
            return {"python": str(python.resolve()), "packages": versions, "installed": False}
    if not allow_install:
        raise SetupError("缺少PDF依赖；允许首次联网初始化后重试，或提供已含pypdf的Python。")
    environment = managed.parent.parent
    # A moved or linked environment should not redirect package installation elsewhere.
    if environment.is_symlink() or not environment.resolve().is_relative_to(Path(data_root).resolve()):
        raise SetupError("运行环境路径指向数据目录之外，请选择独立的数据目录。")
    if managed.exists() and (not (environment / "pyvenv.cfg").is_file()
                             or not managed.resolve().is_relative_to(environment.resolve())):
        raise SetupError("已有运行时不是本数据目录的独立venv，停止安装以免改动其他Python。")
    try:
        environment.parent.mkdir(parents=True, exist_ok=True)
        if not managed.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        requirements = [PACKAGES["pypdf"]] + ([PACKAGES["pypdfium2"], PACKAGES["Pillow"]] if renderer else [])
        print("首次初始化：在独立环境中安装PDF依赖；不修改系统Python。", file=sys.stderr)
        subprocess.run([str(managed), "-m", "pip", "--isolated", "--disable-pip-version-check",
                        "install", "--no-input", "--only-binary=:all:",
                        "--index-url", "https://pypi.org/simple", *requirements],
                       stdout=sys.stderr, check=True, timeout=180, env=child_environment(managed))
    except (OSError, subprocess.SubprocessError) as error:
        raise SetupError("独立PDF环境初始化未完成。检查网络或Python的venv/pip组件后重试；已有会话未改动。") from error
    versions = dependency_versions(managed, renderer)
    if versions is None:
        raise SetupError("依赖安装后仍无法导入，请检查独立环境或指定其他Python。")
    return {"python": str(managed.resolve()), "packages": versions, "installed": True}


def check_zotero():
    try:
        client = Client()
        client.connect()
        return {"ready": True, "server_id": client.server_id, "write_authorization": "仅实际保存时申请"}
    except (ZoteroError, OSError) as error:
        if isinstance(error, ZoteroError) and "Server ID" in str(error):
            action = "当前接口没有Server ID。请确认运行Zotero 10+；本技能的笔记保存需要该版本。"
        else:
            action = friendly_error(error)
        return {"ready": False, "action": action,
                "settings": "Zotero → 设置 → 高级 → 允许此计算机上的其他应用程序与Zotero通信"}


def setup(data_root, allow_install=True, renderer=False, skip_zotero=False):
    runtime = ensure_runtime(data_root, renderer, allow_install)
    zotero = {"ready": None, "status": "not_checked"} if skip_zotero else check_zotero()
    result = {"status": "ready" if zotero["ready"] else ("runtime_ready" if skip_zotero else "needs_user_action"),
              "version": VERSION, "data_dir": str(data_root), "sessions": str(data_root / "sessions"),
              "runtime": runtime, "zotero": zotero}
    # No authorization key or paper contents belong in the setup receipt.
    write_json(data_root / ".local/setup.json", dict(result, checked_at=timestamp()))
    return result


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv in (["--help"], ["-h"], ["--version"]):
        return subprocess.call([sys.executable, "-X", "utf8", str(SCRIPTS / "zotero_notes.py"), *argv])
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("command", nargs="?", default="setup")
    args, remaining = parser.parse_known_args(argv)
    root = args.data_dir.expanduser().resolve() if args.data_dir else default_data_root()
    if args.command == "skill-update":
        from skill_updates import main as update_main
        return update_main(remaining, data_root=root)
    if args.command == "setup":
        options = argparse.ArgumentParser(description="首次初始化或重复检查，不写Zotero")
        options.add_argument("--no-install", action="store_true", help="只复用已有PDF依赖，不联网安装")
        options.add_argument("--renderer", action="store_true", help="同时检查/安装按需PDF渲染依赖")
        options.add_argument("--skip-zotero", action="store_true", help="只检查运行时，不访问本机接口")
        opts = options.parse_args(remaining)
        result = setup(root, not opts.no_install, opts.renderer, opts.skip_zotero)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in ("ready", "runtime_ready") else 2
    if args.command in ("paths", "--help", "-h", "--version"):
        python = sys.executable
    else:
        python = ensure_runtime(root, renderer=args.command == "render")["python"]
    entry = "paper_materials.py" if args.command in ("extract", "render") else "zotero_notes.py"
    return subprocess.call([str(python), "-X", "utf8", str(SCRIPTS / entry),
                            "--data-dir", str(root), args.command, *remaining], env=child_environment(python))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SetupError as error:
        print(json.dumps({"status": "setup_incomplete", "action": str(error)}, ensure_ascii=False))
        sys.exit(2)
