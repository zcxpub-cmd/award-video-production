"""Install this release's dependencies in a user-owned environment and open the studio."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import venv
import webbrowser

from runtime_lock import lock_file

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
IDENTITY = "yingxu-community-workbench"
VERSION = "1.4.0"
HTTP = build_opener(ProxyHandler({}))


def existing_service(url, data_dir):
    try:
        with HTTP.open(url + "api/health", timeout=1.5) as response:
            health = json.load(response)
            return (health.get("identity") == IDENTITY and health.get("version") == VERSION
                    and health.get("workspace") == sha256(os.fsencode(data_dir)).hexdigest())
    except (OSError, URLError, ValueError):
        return False


def prepare_environment(cache):
    key = sha256(REQUIREMENTS.read_bytes()).hexdigest()[:12]
    directory = cache / f"py{sys.version_info.major}.{sys.version_info.minor}-{key}"
    ready = directory / ".installed"
    bin_path = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / ".setup.lock").open("a+b") as lock:
        try:
            lock_file(lock)
        except OSError:
            raise RuntimeError("另一窗口正在安装，请等其完成后再启动。") from None
        if not ready.is_file() or not bin_path.is_file():
            print("首次安装：正在准备影序专用 Python 环境，需联网下载依赖。", flush=True)
            venv.EnvBuilder(with_pip=True).create(directory)
            subprocess.run([str(bin_path), "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
                            "--index-url", "https://pypi.org/simple",
                            "--only-binary=:all:", "-r", str(REQUIREMENTS)], check=True)
            ready.touch()
    return bin_path


def media_available():
    def find(name):
        configured = os.environ.get("YINGXU_" + name.upper())
        homebrew = Path("/opt/homebrew/opt/ffmpeg-full/bin") / name
        return configured or (str(homebrew) if homebrew.is_file() else shutil.which(name))
    ffmpeg, ffprobe = find("ffmpeg"), find("ffprobe")
    if not ffmpeg or not ffprobe:
        return False
    try:
        encoders = subprocess.check_output([ffmpeg, "-hide_banner", "-encoders"], stderr=subprocess.STDOUT, timeout=10)
        filters = subprocess.check_output([ffmpeg, "-hide_banner", "-filters"], stderr=subprocess.STDOUT, timeout=10)
        subprocess.run([ffprobe, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
        return b"libx264" in encoders and b"overlay" in filters and b"ass" in filters
    except (OSError, subprocess.SubprocessError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装并打开影序开源工作台")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("YINGXU_COMMUNITY_DATA_DIR", Path.home()/".yingxu-community"/"projects")))
    parser.add_argument("--runtime-dir", type=Path, default=Path.home()/".yingxu-community"/"runtime")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--portable-ffmpeg", action="store_true", help="使用可下载的 FFmpeg 组件")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error("需要 Python 3.10 或更新版本。")
    if not 1024 <= args.port <= 65535:
        parser.error("端口需要为 1024 至 65535。")
    if not (ROOT / "frontend/dist-runtime/index.html").is_file():
        parser.error("缺少已构建界面，请下载 GitHub Releases 的开源发行 ZIP。")
    data_dir = args.data_dir.resolve()
    url = f"http://127.0.0.1:{args.port}/"
    if existing_service(url, data_dir):
        print(url, flush=True)
        if not args.no_open:
            webbrowser.open(url)
        return 0
    try:
        python = prepare_environment(args.runtime_dir.resolve())
        command = [str(python), "-m", "backend", "--port", str(args.port), "--data-dir", str(data_dir)]
        if args.portable_ffmpeg or not media_available():
            command.append("--portable-ffmpeg")
        with subprocess.Popen(command, cwd=ROOT) as child:
            try:
                while child.poll() is None:
                    if existing_service(url, data_dir):
                        print(f"影序开源工作台：{url}（关闭此窗口可停止服务）", flush=True)
                        if not args.no_open:
                            webbrowser.open(url)
                        return child.wait()
                    time.sleep(.5)
                print("工作台启动失败。请查看上方信息，检查端口、网络和本机媒体依赖。", file=sys.stderr)
                return child.returncode or 1
            except KeyboardInterrupt:
                if child.poll() is None:
                    child.terminate()
                return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"安装或启动失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
