#!/usr/bin/env python3
"""Build a complete fictional 2.4-second project through the shipped CLIs.

No network, paid service, real research material, human voice, or web server.
Runtime reports belong to the output project and may contain local paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone

DURATION = 2.4
REQUIRED_SCRIPTS = ("demo_project.py", "content_tools.py", "material_wall.py", "media_tools.py", "archive_tools.py")
WALL_FILES = ("index.html", "app.js", "style.css", "home.html", "home.css", "home.js")
REQUIRED_FILTERS = {"testsrc2", "sine", "volume", "ass", "blackdetect", "freezedetect", "metadata"}


class DemoError(ValueError):
    pass


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        if isinstance(value, str):
            handle.write(value)
        else:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")


def run_process(command, timeout=180):
    result = subprocess.run([str(v) for v in command], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-3000:]
        raise DemoError(f"命令失败（exit {result.returncode}）：{detail}")
    return result


def preflight(args, source):
    ffmpeg, ffprobe = shutil.which(args.ffmpeg), shutil.which(args.ffprobe)
    if not ffmpeg or not ffprobe:
        raise DemoError("演示需要已有的 ffmpeg 和 ffprobe；请使用 --ffmpeg / --ffprobe 指定可执行文件，不会自动安装。")
    if not args.font.strip() or any(c in args.font for c in ",\n\r{}\\"):
        raise DemoError("--font 必须是本机可用的单个字体家族名")
    for name in REQUIRED_SCRIPTS:
        if not (source / name).is_file():
            raise DemoError(f"发行工具缺失：scripts/{name}")
    for name in WALL_FILES:
        if not (source.parent / "assets/wall" / name).is_file():
            raise DemoError(f"发行页面缺失：assets/wall/{name}")
    listed = run_process([ffmpeg, "-hide_banner", "-filters"], timeout=20).stdout
    filters = {parts[1] for line in listed.splitlines() if len(parts := line.split()) > 2}
    missing = sorted(REQUIRED_FILTERS - filters)
    if missing:
        note = "；烧录标题需带 libass 的 FFmpeg 构建" if "ass" in missing else ""
        raise DemoError(f"所选 ffmpeg 缺少过滤器：{', '.join(missing)}{note}。请指定满足能力的已有构建，不会自动安装。")
    run_process([ffprobe, "-version"], timeout=20)
    return ffmpeg, ffprobe


def run_stage(root, name, command, completed):
    result = run_process(command)
    # Only commands chosen by this demo are executed; bounded diagnostics suffice.
    record = {"stage": name, "returncode": result.returncode, "command": [str(v) for v in command], "stdout": result.stdout[-5000:], "stderr": result.stderr[-1500:]}
    write_new(root / "evidence" / f"{len(completed)+1:02d}-{name}.json", record)
    completed.append(name)
    return result


def create_inputs(root, font):
    manuscript = {
        "project_title": "虚构流程演示 · 非真实科研成果",
        "chapters": [{"chapter_id": "C01", "title": "虚构流程演示", "units": ["虚构示例，无真实参与单位"], "sentences": [{"id": "C01_S01", "text": "本片为合成测试图与正弦提示音，不是真实科研素材或配音。", "facts_review_status": "pending", "source_refs": []}]}],
        "pronunciations": [],
    }
    shots = {"shots": [{"asset_id": "DEMO_A01", "chapter_id": "C01", "source_path": "media/synthetic.mp4", "sentence_ids": ["C01_S01"], "source_in_s": 0, "source_out_s": DURATION, "semantic_reason": "演示素材路径、播放、标题与归档的技术链路；不支撑科学结论。", "origin": "FFmpeg lavfi 合成测试，非真实科研素材", "local_codex_generated": False, "text_policy": "保留合成测试标识", "review_status": "pending", "review_note": "待实际浏览器与播放器审看；正弦提示音不是配音。"}]}
    timing = {"width": 640, "height": 360, "font": font, "font_size": 22, "titles": [{"start": 0.1, "end": 1.9, "text": "虚构流程演示", "x": 320, "y": 65, "font_size": 32}, {"start": 0.1, "end": 1.9, "text": "合成测试图 · 非真实科研素材", "x": 320, "y": 110, "font_size": 22}], "subtitles": [{"start": 0.3, "end": 2.3, "text": "正弦提示音，非真实配音"}]}
    edit = {"version": 1, "canvas": {"width": 640, "height": 360, "fps": 25, "background": "black"}, "clips": [{"path": "media/synthetic.mp4", "kind": "video", "in": 0, "out": DURATION, "audio": True, "volume": 1, "chapter_id": "C01"}], "subtitles": "subtitle-timing.json", "chapters": [{"id": "C01", "start": 0, "end": DURATION}]}
    for filename, value in (("manuscript.json", manuscript), ("shots.json", shots), ("subtitle-timing.json", timing), ("edit.json", edit)):
        write_new(root / filename, value)


def start_here():
    return """# 虚构演示项目

这是一段 2.4 秒的 FFmpeg 测试图和低音量正弦提示音，不包含真实科研成果或真实配音。
是否完整完成以 demo-report.json 的 success 状态为准；出现 demo-failed.json 表示部分产物仅供排障，不能按成功交付使用。

- 成片：[delivery/film.mp4](delivery/film.mp4)
- 独立章：[delivery/C01.mp4](delivery/C01.mp4)
- 可编辑文稿：[manuscript/narration.docx](manuscript/narration.docx)
- 可编辑标题/字幕：[delivery/layers.ass](delivery/layers.ass)
- 素材墙：[wall/START_HERE.txt](wall/START_HERE.txt)
- 技术 QC：[evidence/qc.json](evidence/qc.json)
- 最终技术状态：[demo-report.json](demo-report.json)
- 归档：[archive/archive-manifest.json](archive/archive-manifest.json)

在本项目目录打开终端，启动素材墙：

```bash
python3 rebuild-tools/scripts/material_wall.py serve wall --port 8765
```

然后打开 http://127.0.0.1:8765/ ，从动态首页点「进入素材墙」。全部素材初始待审。审核与备注另存 wall/reviews.json，重启服务后可继续。

在本项目目录验证归档：

```bash
python3 rebuild-tools/scripts/archive_tools.py verify archive
```

源输入、脚本快照、页面、生成物和技术证据列入 archive-plan.json；依赖清单完整仅指本演示显式生产的文件集，不等于科学事实、播放器、原生编辑器或用户验收通过。归档 restore/rewrite-json 和真实播放器恢复检查仍是独立动作。

字体使用运行时指定的本机字体。须实际检查中文缺字、标题位置、音量、视频播放与拖动；自动解码不代替这些检查。合成提示音不能证明 TTS、发音或声音质量可用。

重新运行 demo_project.py 必须选择另一个全新输出目录。脚本和项目报告可能记录运行者的本机路径；公开发布源码时不要把运行输出目录一起提交。
"""


def demo(args):
    destination = Path(args.output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise DemoError("输出已存在；请选择全新目录，不会覆盖已有项目。")
    source = Path(__file__).resolve().parent
    ffmpeg, ffprobe = preflight(args, source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()  # Exclusive creation also protects against concurrent demos.
    root = destination.resolve()
    completed = []
    marker = root / "DEMO_IN_PROGRESS.json"
    write_new(marker, {"status": "in_progress", "duration_s": DURATION, "fictional": True})
    try:
        for folder in ("media", "evidence", "rebuild-tools/scripts", "rebuild-tools/assets/wall"):
            (root / folder).mkdir(parents=True)
        for name in REQUIRED_SCRIPTS:
            shutil.copyfile(source / name, root / "rebuild-tools/scripts" / name)
        for name in WALL_FILES:
            shutil.copyfile(source.parent / "assets/wall" / name, root / "rebuild-tools/assets/wall" / name)
        scripts = root / "rebuild-tools/scripts"
        create_inputs(root, args.font)
        write_new(root / "START_HERE.md", start_here())
        python = sys.executable
        media_cli = [python, scripts / "media_tools.py", "--ffmpeg", ffmpeg, "--ffprobe", ffprobe]
        run_stage(root, "synthetic-media", [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(DURATION), "-af", "volume=0.06", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", root / "media/synthetic.mp4"], completed)
        source_hash = hashlib.sha256((root / "media/synthetic.mp4").read_bytes()).hexdigest()
        run_stage(root, "manuscript", [python, scripts / "content_tools.py", "manuscript", root / "manuscript.json", "--out-dir", root / "manuscript"], completed)
        run_stage(root, "handoff", [python, scripts / "content_tools.py", "handoff", root / "manuscript.json", root / "shots.json", "--out", root / "wall-input.json"], completed)
        run_stage(root, "wall", [python, scripts / "material_wall.py", "build", root / "wall-input.json", "--output", root / "wall", "--copy-media"], completed)
        run_stage(root, "subtitles", [*media_cli, "subtitles", root / "subtitle-timing.json", "--output", root / "subtitle-layers"], completed)
        run_stage(root, "render", [*media_cli, "render", root / "edit.json", "--output", root / "delivery"], completed)
        run_stage(root, "qc", [*media_cli, "qc", root / "delivery/film.mp4", "--output", root / "evidence/qc.json"], completed)
        qc = json.loads((root / "evidence/qc.json").read_text(encoding="utf-8"))
        if not qc.get("result", {}).get("full_decode_passed"):
            raise DemoError("技术 QC 未确认完整解码")
        if source_hash != hashlib.sha256((root / "media/synthetic.mp4").read_bytes()).hexdigest():
            raise DemoError("演示源素材在处理过程中发生变化")
        # This producer owns and enumerates every file in the tiny synthetic project.
        # This flag states dependency enumeration, not approval of research content.
        files = [{"path": p.relative_to(root).as_posix(), "role": "synthetic-demo-dependency"} for p in sorted(root.rglob("*")) if p.is_file() and p != marker]
        files.append({"path": "archive-plan.json", "role": "archive-plan"})
        write_new(root / "archive-plan.json", {"dependency_review_complete": True, "files": files, "references": ["edit.json", "shots.json", "subtitle-timing.json"], "unresolved": [], "review_basis": "Explicitly enumerated files generated or copied by this self-contained fictional demo; no real project dependency claim."})
        run_stage(root, "archive-create", [python, scripts / "archive_tools.py", "create", root / "archive-plan.json", "--out", root / "archive"], completed)
        verified = run_stage(root, "archive-verify", [python, scripts / "archive_tools.py", "verify", root / "archive"], completed)
        verification = json.loads(verified.stdout)
        if not verification.get("hashes_verified"):
            raise DemoError("归档哈希校验失败")
        write_new(root / "evidence/archive-verification.json", verification)
        report = {"status": "success", "created_at": datetime.now(timezone.utc).isoformat(), "output": str(root), "duration_s": DURATION, "fictional": True, "audio": "synthetic sine tone; not narration or human voice", "completed_stages": completed, "technical_full_decode": True, "archive_hashes_verified": True, "source_unchanged": True, "scientific_acceptance": False, "player_acceptance": False, "human_acceptance": False, "wall_review_status": "pending", "font": args.font, "font_visual_review": "pending", "entry": str(root / "START_HERE.md"), "film": str(root / "delivery/film.mp4"), "serve_command": shlex.join([python, str(scripts / "material_wall.py"), "serve", str(root / "wall"), "--port", "8765"])}
        write_new(root / "demo-report.json", report)
        marker.unlink()
        return report
    except (Exception, KeyboardInterrupt) as exc:
        failure = {"status": "failed", "completed_stages": completed, "error": str(exc)[-3000:], "note": "Partial files are retained for diagnosis. This directory is not a successful demo; choose a new output directory for another run."}
        write_new(root / "demo-failed.json", failure)
        marker.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行独立虚构演示：合成 2.4 秒测试图与正弦音，经文稿→交接→素材墙→标题→成片→QC→归档。不会启动服务或调用付费工具。")
    parser.add_argument("--output", required=True, help="全新项目目录，不覆盖已有目录")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="已有 ffmpeg 可执行文件；需要 libass 与黑场/冻结检测过滤器")
    parser.add_argument("--ffprobe", default="ffprobe", help="已有 ffprobe 可执行文件")
    parser.add_argument("--font", default="sans-serif", help="本机字体家族名，建议指定支持中文的字体；默认 sans-serif")
    args = parser.parse_args(argv)
    try:
        report = demo(args)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"演示失败：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("演示已中断；若有输出目录，请查看 demo-failed.json。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
