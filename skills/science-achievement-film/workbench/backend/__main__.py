import argparse
import os
from pathlib import Path

import uvicorn
from .server import create_app


def main():
    parser = argparse.ArgumentParser(description="影序开源工作台")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--data-dir", default=os.environ.get("YINGXU_COMMUNITY_DATA_DIR", str(Path.home()/".yingxu-community"/"projects")))
    parser.add_argument("--portable-ffmpeg", action="store_true", help="在本机工作台环境准备 FFmpeg 与 FFprobe")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口需要为 1024 至 65535")
    if args.portable_ffmpeg:
        from static_ffmpeg import run
        print("正在准备本机 FFmpeg 与 FFprobe，首次启动可能需要下载…", flush=True)
        ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
        os.environ["YINGXU_FFMPEG"] = str(ffmpeg)
        os.environ["YINGXU_FFPROBE"] = str(ffprobe)
    app = create_app(args.data_dir)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
