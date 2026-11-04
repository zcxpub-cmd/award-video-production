#!/usr/bin/env python3
"""Expose local, read-only project and media checks to agent hosts over JSON."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPTS = Path(__file__).resolve().parent
TOOLS = {
    "inventory": ("filmkit.py", "--out", "source",
                  "Inventory local media by file metadata."),
    "check": ("filmkit.py", "--out", "project",
              "Validate a local project file and report findings."),
    "probe": ("media_tools.py", "--output", "input",
              "Inspect a local media file with ffprobe."),
}


def catalog():
    return [
        {
            "name": name,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": {field: {"type": "string", "minLength": 1}},
                "required": [field],
                "additionalProperties": False,
            },
        }
        for name, (_, _, field, description) in TOOLS.items()
    ]


def invoke(name, arguments):
    script, option, field, _ = TOOLS[name]
    if not isinstance(arguments, dict) or set(arguments) != {field}:
        raise ValueError(f"Expected exactly one field: {field}")
    path = arguments[field]
    if not isinstance(path, str) or not path.strip() or "\0" in path or "://" in path:
        raise ValueError(f"{field} must be a nonempty local path")

    with tempfile.TemporaryDirectory(prefix="film-agent-") as folder:
        output = Path(folder) / "report.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), name, option, str(output), "--", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, check=False,
        )
        report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
    response = {"ok": result.returncode == 0, "exit_code": result.returncode, "report": report}
    if result.returncode and result.stderr.strip():
        response["error"] = result.stderr.strip()
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Print the available tools and input schemas")
    call = commands.add_parser("invoke", help="Read one JSON argument object from stdin")
    call.add_argument("tool", choices=TOOLS)
    launch = commands.add_parser("launch", help="Start the workspace and open the Yingxu homepage")
    launch.add_argument("directory", help="Existing material wall directory")
    launch.add_argument("--port", type=int, default=8765)
    launch.add_argument("--no-open", action="store_true", help="Print the homepage URL without opening a browser")
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps({"tools": catalog()}, ensure_ascii=False))
        return 0

    if args.command == "launch":
        from material_wall import main as wall_main

        command = ["serve", args.directory, "--port", str(args.port)]
        if not args.no_open:
            command.append("--open")
        return wall_main(command)

    try:
        response = invoke(args.tool, json.load(sys.stdin))
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        response = {"ok": False, "exit_code": 1, "report": None, "error": str(exc)}
    print(json.dumps(response, ensure_ascii=False))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
