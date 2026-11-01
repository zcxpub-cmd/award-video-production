#!/usr/bin/env python3
"""Conservative, offline planning checks for science achievement films (stdlib)."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

VERSION = "1.0"
UF_DATALESS = getattr(stat, "UF_DATALESS", 0x40000000)
MEDIA = {
    "video": {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".mxf"},
    "audio": {".wav", ".mp3", ".m4a", ".aac", ".aiff", ".aif", ".flac", ".ogg"},
    "image": {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".bmp", ".exr"},
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def dataless(info):
    """macOS File Provider / iCloud flag; unavailable flags imply unknown, not proof."""
    return bool(getattr(info, "st_flags", 0) & UF_DATALESS)


def cloud_name(path):
    return path.name.endswith(".icloud")


def media_kind(path):
    name = path.name[:-7] if cloud_name(path) else path.name
    suffix = Path(name).suffix.lower()
    return next((kind for kind, extensions in MEDIA.items() if suffix in extensions), None)


def local_path(base, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a nonempty local path is required")
    if "://" in value:
        raise ValueError("URLs are not accepted; checks never access the network")
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def safe_stat(path):
    """Reject final symlinks and placeholders; allow explicit parent aliases (/tmp)."""
    absolute = Path(os.path.abspath(path))
    if absolute.is_symlink():
        raise ValueError(f"symlink content is not followed: {absolute}")
    for part in reversed([absolute, *absolute.parents]):
        info = part.lstat()
        if dataless(info) or cloud_name(part):
            raise ValueError(f"offline placeholder content is not opened: {part}")
    canonical = absolute.parent.resolve(strict=True) / absolute.name
    for part in reversed([canonical, *canonical.parents]):
        info = part.lstat()
        if dataless(info) or cloud_name(part):
            raise ValueError(f"offline placeholder content is not opened: {part}")
    return info


def dump_json(path, value, *, exclusive=False, forbidden=()):
    path = Path(path).expanduser()
    if path.suffix.lower() != ".json":
        raise ValueError("output must use a .json extension")
    resolved = path.resolve()
    if any(resolved == Path(other).resolve() for other in forbidden):
        raise ValueError("output would overwrite a project or referenced source file")
    if path.is_symlink():
        raise ValueError("output symlink is not allowed")
    # The caller chooses the sole output path. No source directories are created.
    safe_stat(path.parent.resolve(strict=True))
    with path.open("x" if exclusive else "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def init_project(args):
    target = Path(args.out).expanduser()
    if target.is_symlink():
        raise ValueError("output directory cannot be a symlink")
    target.mkdir(parents=True, exist_ok=True)
    safe_stat(target)
    chapters = []
    for index in range(1, args.chapters + 1):
        cid = f"C{index:02d}"
        chapters.append({
            "id": cid, "title": "", "units": [], "protected_terms": [],
            "speak_title": True, "speak_units": True, "protect_title_as_phrase": True,
            "narration": [{
                "id": f"{cid}-S{si:02d}", "role": role, "narration_display": "",
                "narration_tts": "", "voice_duration_s": None,
                "voice_duration_basis": "unmeasured", "voice_path": None,
                "playback_rate": 1.0, "tts_segments": [], "subtitle_cues": [],
            } for si, role in enumerate(("title", "units"), start=1)],
            "transition_duration_s": None, "transition_overlap_s": None,
            "picture_extension_s": None, "wait_s": None, "picture_plan": [],
        })
    project = {
        "schema_version": VERSION, "title": "", "fps": args.fps,
        "max_seconds": args.max_seconds,
        "runtime": {
            "definition": "sequential_nonoverlapping_blocks",
            "opening_s": None, "intro_music_standalone_s": None,
            "ending_s": None, "global_wait_s": None,
        },
        "chapters": chapters, "approved": [], "revision_queue": [],
        "notes": [
            "Unknown durations remain null; enter an explicit 0 for an absent block.",
            "Background music under narration adds no runtime; standalone intro music does.",
            "transition_overlap_s is narration/transition overlap, counted only once.",
            "For screen-only titles/units set speak_title/speak_units false and omit those spoken entries; do not create silent TTS.",
        ],
    }
    path = target / "project.json"
    dump_json(path, project, exclusive=True)
    print(str(path))
    return 0


def inventory(args):
    root = Path(args.source).expanduser()
    root_info = root.lstat()
    records, issues = [], []
    executable = shutil.which("ffprobe") if args.probe else None

    def visit(path, info):
        if stat.S_ISLNK(info.st_mode):
            issues.append({"path": str(path), "status": "symlink_skipped"})
            return
        placeholder = dataless(info) or cloud_name(path)
        if stat.S_ISDIR(info.st_mode):
            if placeholder:
                issues.append({"path": str(path), "status": "placeholder", "directory": True})
                return
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        child = Path(entry.path)
                        try:
                            visit(child, entry.stat(follow_symlinks=False))
                        except OSError as exc:
                            issues.append({"path": str(child), "status": "read_error", "error": str(exc)})
            except OSError as exc:
                issues.append({"path": str(path), "status": "read_error", "error": str(exc)})
            return
        kind = media_kind(path)
        if not kind or not stat.S_ISREG(info.st_mode):
            return
        record = {
            "path": str(path.absolute()), "kind": kind, "size_bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "status": "placeholder" if placeholder else "decode_unverified",
            "availability": "placeholder" if placeholder else "metadata_only",
            "decode_verified": False,
            "flags_supported": hasattr(info, "st_flags"),
            "dataless_flag": dataless(info),
        }
        if args.probe and not placeholder:
            if executable is None:
                record["probe_error"] = "ffprobe_unavailable"
            else:
                try:
                    safe_stat(path)  # Recheck immediately before an optional content read.
                    result = subprocess.run(
                        [executable, "-v", "error", "-show_entries",
                         "format=duration,format_name:stream=index,codec_type,codec_name,width,height,sample_rate,duration",
                         "-of", "json", str(path.absolute())],
                        capture_output=True, text=True, timeout=args.timeout, check=False,
                    )
                    parsed = json.loads(result.stdout) if result.returncode == 0 else {}
                    if result.returncode != 0 or not parsed.get("streams"):
                        record.update(status="read_error", availability="unverified",
                                      probe_error=(result.stderr or "no media streams")[:1200])
                    else:
                        record.update(status="probe_ok", availability="available", probe=parsed)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    record.update(status="read_error", availability="unverified", probe_error=str(exc)[:1200])
        records.append(record)

    # Ancestors may themselves be placeholders or symlinks; never follow them.
    safe_stat(root.parent.resolve(strict=True))
    visit(root, root_info)
    records.sort(key=lambda item: item["path"])
    report = {
        "schema_version": VERSION, "generated_at": stamp(), "source": str(root.absolute()),
        "mode": "ffprobe_metadata" if args.probe else "filesystem_metadata_only",
        "ffprobe_available": bool(executable) if args.probe else None,
        "limits": [
            "Filesystem metadata alone does not prove media availability or decoding.",
            "probe_ok / available means ffprobe read stream metadata, not full decode or playback acceptance.",
            "No file hashes are computed. Symlinks and detected offline placeholders are not opened.",
            "Cloud providers without a detectable placeholder flag may still hydrate when --probe is explicitly used.",
        ],
        "counts": dict(Counter(item["status"] for item in records)),
        "files": records, "issues": issues,
    }
    dump_json(args.out, report, forbidden=[root, *(item["path"] for item in records)])
    print(json.dumps({"files": len(records), "counts": report["counts"], "issues": len(issues)}, ensure_ascii=False))
    return 0


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_project(args):
    project_path = Path(args.project).expanduser().absolute()
    safe_stat(project_path)
    with project_path.open(encoding="utf-8") as handle:
        project = json.load(handle)
    if not isinstance(project, dict):
        raise ValueError("project JSON must be an object")
    findings, forbidden = [], [project_path]
    base = project_path.parent

    def finding(level, code, location, message):
        findings.append({"level": level, "code": code, "location": location, "message": message})

    def duration(value, location):
        if not is_number(value) or value < 0:
            finding("error", "duration_unknown_or_invalid", location, "Requires a finite measured/explicit duration >= 0; null is not zero.")
            return None
        return float(value)

    def required_text(value, location):
        if not isinstance(value, str) or not value.strip():
            finding("error", "missing_text", location, "Nonempty text is required.")
            return False
        return True

    def array(value, location):
        if not isinstance(value, list):
            finding("error", "invalid_array", location, "Expected an array.")
            return []
        return value

    def boundaries(segments, text, location):
        """Only explicit contiguous character ranges constitute segmentation evidence."""
        segments = array(segments, location)
        if not segments:
            finding("review", "segmentation_unprovided", location, "Actual segmentation is absent; protected-term splitting remains unverified.")
            return []
        previous, result, valid = 0, [], True
        for i, segment in enumerate(segments):
            loc = f"{location}[{i}]"
            if not isinstance(segment, dict):
                finding("error", "invalid_segment", loc, "Expected a character-range object.")
                valid = False
                continue
            start, end = segment.get("start"), segment.get("end")
            if (type(start) is not int or type(end) is not int or start != previous
                    or end <= start or end > len(text)):
                finding("error", "invalid_segment_range", loc, "Ranges must partition text without gaps/overlaps; offsets use Python Unicode characters.")
                valid = False
                continue
            if "text" in segment and segment["text"] != text[start:end]:
                finding("error", "segment_text_mismatch", loc, "Segment text differs from the declared character range.")
                valid = False
            previous = end
            if end < len(text):
                result.append(end)
        if previous != len(text):
            finding("error", "segment_incomplete", location, "Ranges do not cover the complete text.")
            valid = False
        return result if valid else []

    if project.get("schema_version") != VERSION:
        finding("error", "schema_version", "schema_version", f"Supported schema is {VERSION}.")
    required_text(project.get("title"), "title")
    if not is_number(project.get("fps")) or project["fps"] <= 0:
        finding("error", "fps_invalid", "fps", "fps must be positive.")
    maximum = duration(project.get("max_seconds"), "max_seconds")
    if maximum == 0:
        finding("error", "runtime_limit_invalid", "max_seconds", "max_seconds must be positive.")
    runtime = project.get("runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}
    if runtime.get("definition") != "sequential_nonoverlapping_blocks":
        finding("error", "runtime_definition", "runtime.definition", "Use sequential_nonoverlapping_blocks and account for every nonoverlapping block exactly once.")
    blocks = {key: duration(runtime.get(key), f"runtime.{key}") for key in
              ("opening_s", "intro_music_standalone_s", "ending_s", "global_wait_s")}
    chapter_totals, all_ids, intervals = [], set(), []
    chapters = array(project.get("chapters"), "chapters")
    if not chapters:
        finding("error", "no_chapters", "chapters", "At least one chapter is required.")
    for ci, chapter in enumerate(chapters):
        cloc = f"chapters[{ci}]"
        if not isinstance(chapter, dict):
            finding("error", "invalid_chapter", cloc, "Expected an object.")
            chapter_totals.append(None)
            continue
        cid = chapter.get("id")
        if not required_text(cid, f"{cloc}.id") or cid in all_ids:
            finding("error", "id_invalid_or_duplicate", cloc, "Chapter and sentence IDs must be unique.")
        elif isinstance(cid, str):
            all_ids.add(cid)
        required_text(chapter.get("title"), f"{cloc}.title")
        switches = {}
        for key, default in (("speak_title", True), ("speak_units", False), ("protect_title_as_phrase", True)):
            switches[key] = chapter.get(key, default)
            if type(switches[key]) is not bool:
                finding("error", "invalid_boolean", f"{cloc}.{key}", "Use an explicit JSON true or false.")
                switches[key] = default
        speak_title, speak_units = switches["speak_title"], switches["speak_units"]
        protect_title = switches["protect_title_as_phrase"]
        if not protect_title:
            finding("review", "title_phrase_protection_overridden", cloc, "Whole-title phrase protection is explicitly disabled; protected_terms still apply and the declared pause needs listening review.")
        units = array(chapter.get("units"), f"{cloc}.units")
        if not units or any(not isinstance(unit, str) or not unit.strip() for unit in units):
            finding("error", "units_missing_or_invalid", f"{cloc}.units", "Provide official unit names as nonempty strings.")
        finding("review", "official_text_review", cloc, "Title, unit attribution, scientific meaning, and official source accuracy require human verification.")
        terms = array(chapter.get("protected_terms", []), f"{cloc}.protected_terms")
        if any(not isinstance(term, str) or not term for term in terms):
            finding("error", "protected_terms_invalid", cloc, "Protected terms must be nonempty exact strings.")
        terms = [term for term in terms if isinstance(term, str) and term]
        texts = {"display": [], "tts": []}
        cuts = {"display": [], "tts": []}
        seen_sentence_ids, voices, title_count, units_count = set(), [], 0, 0
        narration_declared = isinstance(chapter.get("narration"), list)
        narration = array(chapter.get("narration"), f"{cloc}.narration")
        for si, sentence in enumerate(narration):
            sloc = f"{cloc}.narration[{si}]"
            if not isinstance(sentence, dict):
                finding("error", "invalid_sentence", sloc, "Expected an object.")
                voices.append(None)
                continue
            sid = sentence.get("id")
            if not required_text(sid, f"{sloc}.id") or sid in all_ids:
                finding("error", "id_invalid_or_duplicate", sloc, "Chapter and sentence IDs must be unique.")
            elif isinstance(sid, str):
                seen_sentence_ids.add(sid)
                all_ids.add(sid)
            display, tts = sentence.get("narration_display"), sentence.get("narration_tts")
            required_text(display, f"{sloc}.narration_display")
            required_text(tts, f"{sloc}.narration_tts")
            display = display if isinstance(display, str) else ""
            tts = tts if isinstance(tts, str) else ""
            if sentence.get("role") == "title":
                title_count += 1
                if display != chapter.get("title"):
                    finding("error", "title_display_mismatch", sloc, "Title narration display must exactly equal the chapter title.")
            elif sentence.get("role") == "units":
                units_count += 1
            value = duration(sentence.get("voice_duration_s"), f"{sloc}.voice_duration_s")
            if value == 0:
                finding("error", "voice_duration_nonpositive", sloc, "A spoken narration entry requires measured duration > 0. Omit screen-only titles/units instead of inventing silent or zero-second TTS.")
                value = None
            if sentence.get("voice_duration_basis") not in ("measured_audio", "measured_timeline"):
                finding("error", "voice_unmeasured", sloc, "Only measured_audio / measured_timeline durations enter the runtime total.")
                value = None
            if not is_number(sentence.get("playback_rate")) or sentence["playback_rate"] != 1:
                finding("error", "speed_change_forbidden", sloc, "Narration playback_rate must equal 1; revise text instead of accelerating speech.")
            voices.append(value)
            if sentence.get("voice_path"):
                try:
                    path = local_path(base, sentence["voice_path"])
                    forbidden.append(path)
                    safe_stat(path)
                except (OSError, ValueError) as exc:
                    finding("error", "voice_source_unavailable", sloc, str(exc))
            else:
                finding("review", "voice_measurement_evidence_missing", sloc, "Measured duration is a declared value; no local voice_path supplied for independent audit.")
            for channel, text, field in (("display", display, "subtitle_cues"), ("tts", tts, "tts_segments")):
                offset = sum(len(item) for item in texts[channel])
                if texts[channel]:
                    cuts[channel].append(offset)  # A declared sentence boundary is real segmentation evidence.
                cuts[channel].extend(offset + cut for cut in boundaries(sentence.get(field, []), text, f"{sloc}.{field}"))
                texts[channel].append(text)
        if speak_title and title_count != 1 or not speak_title and title_count > 1:
            finding("error", "title_sentence_count", cloc, "speak_title=true requires exactly one role=title sentence; screen-only titles need none.")
        if speak_units and units_count == 0:
            finding("error", "units_sentence_missing", cloc, "speak_units=true requires at least one role=units spoken sentence.")
        if not speak_title and title_count or not speak_units and units_count:
            finding("review", "speech_setting_conflict", cloc, "Spoken title/units entries remain despite a false speech switch. Their actual measured durations are still counted; reconcile the plan explicitly.")
        if protect_title and (speak_title or title_count) and isinstance(chapter.get("title"), str) and chapter["title"]:
            terms = list(dict.fromkeys([chapter["title"], *terms]))
        for term in terms:
            for channel in ("display", "tts"):
                combined = "".join(texts[channel])
                start, occurrences = 0, []
                while True:
                    at = combined.find(term, start)
                    if at < 0:
                        break
                    occurrences.append((at, at + len(term)))
                    start = at + 1
                if not occurrences:
                    finding("review", "protected_term_not_located", cloc, f"{term!r} not found exactly in {channel}; wording variants need human review, not automatic split inference.")
                for start, end in occurrences:
                    if any(start < cut < end for cut in cuts[channel]):
                        finding("error", "protected_term_split", cloc, f"{term!r} crosses an explicit {channel} sentence/segment boundary at character range [{start}, {end}).")
        transition = duration(chapter.get("transition_duration_s"), f"{cloc}.transition_duration_s")
        overlap = duration(chapter.get("transition_overlap_s"), f"{cloc}.transition_overlap_s")
        extension = duration(chapter.get("picture_extension_s"), f"{cloc}.picture_extension_s")
        wait = duration(chapter.get("wait_s"), f"{cloc}.wait_s")
        voice_total = sum(voices) if narration_declared and all(value is not None for value in voices) else None
        if overlap is not None and (transition is not None and overlap > transition or voice_total is not None and overlap > voice_total):
            finding("error", "overlap_exceeds_blocks", cloc, "Overlap cannot exceed either transition or measured narration duration.")
            overlap = None
        parts = (voice_total, transition, overlap, extension, wait)
        chapter_totals.append(voice_total + transition - overlap + extension + wait if all(value is not None for value in parts) else None)
        covered = set()
        shots = array(chapter.get("picture_plan"), f"{cloc}.picture_plan")
        if not shots:
            finding("error", "picture_plan_missing", cloc, "A picture plan is required.")
        for pi, shot in enumerate(shots):
            ploc = f"{cloc}.picture_plan[{pi}]"
            if not isinstance(shot, dict):
                finding("error", "invalid_shot", ploc, "Expected an object.")
                continue
            refs = array(shot.get("sentence_ids", []), f"{ploc}.sentence_ids")
            valid_refs = all(isinstance(ref, str) and ref in seen_sentence_ids for ref in refs)
            if not valid_refs:
                finding("error", "unknown_sentence_reference", ploc, "Every sentence_ids entry must refer to this chapter's narration.")
            else:
                covered.update(refs)
            bridge = shot.get("kind") == "bridge" and isinstance(shot.get("purpose"), str) and shot["purpose"].strip()
            if not refs and not bridge:
                finding("error", "shot_binding_missing", ploc, "Bind the shot to sentence_ids, or set kind=bridge and provide a concrete purpose.")
            source = None
            try:
                source = local_path(base, shot.get("source"))
                forbidden.append(source)
                info = safe_stat(source)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("source is not a regular local file")
            except (OSError, ValueError) as exc:
                finding("error", "picture_source_unavailable", ploc, str(exc))
            start, end = duration(shot.get("in_s"), f"{ploc}.in_s"), duration(shot.get("out_s"), f"{ploc}.out_s")
            if start is not None and end is not None:
                if end <= start:
                    finding("error", "source_range_invalid", ploc, "out_s must exceed in_s; stills use explicit presentation interval 0..duration.")
                elif source is not None:
                    intervals.append((str(source.resolve()), start, end, ploc))
            finding("review", "shot_semantics_unverified", ploc, "Sentence reference is structural evidence only; visual relevance, source rights, full apparatus identity, and playback require human review.")
        if seen_sentence_ids - covered:
            finding("error", "sentence_without_picture", cloc, f"Unbound narration IDs: {', '.join(sorted(seen_sentence_ids - covered))}")
    for i, (source, start, end, location) in enumerate(intervals):
        for other_source, other_start, other_end, other_location in intervals[:i]:
            if source == other_source and max(start, other_start) < min(end, other_end) - 1e-9:
                finding("review", "source_interval_reused", location, f"Overlaps {other_location} on the same source; confirm repetition is intentional.")
    approved = array(project.get("approved", []), "approved")
    approved_ids = set()
    if not approved:
        finding("review", "approved_snapshot_absent", "approved", "No frozen component snapshot supplied; preservation is unverified.")
    for ai, component in enumerate(approved):
        loc = f"approved[{ai}]"
        if not isinstance(component, dict):
            finding("error", "invalid_approved_component", loc, "Expected an object.")
            continue
        component_id = component.get("id")
        if not required_text(component_id, f"{loc}.id") or component_id in approved_ids:
            finding("error", "approved_id_invalid", loc, "Frozen component IDs must be unique.")
        elif isinstance(component_id, str):
            approved_ids.add(component_id)
        try:
            path = local_path(base, component.get("path"))
            forbidden.append(path)
        except ValueError as exc:
            finding("error", "snapshot_unavailable", loc, str(exc))
            continue
        digest = component.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            finding("error", "snapshot_hash_invalid", loc, "Provide the actual approved file's lowercase SHA-256 snapshot.")
            continue
        try:
            before = safe_stat(path)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("approved component is not a regular local file")
            actual = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    actual.update(chunk)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                finding("error", "snapshot_changed_during_read", loc, "File changed during hashing; rerun after writers stop.")
            elif actual.hexdigest() != digest:
                finding("error", "frozen_component_changed", loc, "Current file SHA-256 differs from the approved snapshot; a revision request does not waive this check.")
        except (OSError, ValueError) as exc:
            finding("error", "snapshot_unavailable", loc, str(exc))
    for ri, revision in enumerate(array(project.get("revision_queue", []), "revision_queue")):
        loc = f"revision_queue[{ri}]"
        if (not isinstance(revision, dict) or not isinstance(revision.get("component_id"), str)
                or revision.get("component_id") not in (approved_ids | all_ids | {"OPENING", "ENDING"})):
            finding("error", "revision_component_unknown", loc, "Revision must reference an existing chapter/sentence, OPENING/ENDING, or an approved component ID.")
        else:
            required_text(revision.get("reason"), f"{loc}.reason")
            finding("review", "revision_pending", loc, "A queued revision does not unlock frozen files. Apply current instructions and existing authorization without requesting already-granted approval again; this checker never edits components.")
    all_durations = [*blocks.values(), *chapter_totals]
    total = sum(all_durations) if all(value is not None for value in all_durations) else None
    if total is not None and maximum is not None and total > maximum:
        finding("error", "runtime_exceeded", "runtime", f"Declared measured runtime {total:.3f}s exceeds {maximum:.3f}s; shorten narration or remove material, never auto-speed narration.")
    levels = Counter(item["level"] for item in findings)
    report = {
        "schema_version": VERSION, "generated_at": stamp(), "project": str(project_path),
        "status": "fail" if levels["error"] else "needs_review" if levels["review"] else "machine_checks_pass",
        "machine_checks_pass": not bool(levels["error"]), "human_acceptance": "not_verified",
        "runtime": {"total_s": total, "limit_s": maximum, "complete": total is not None,
                    "fixed_blocks_s": blocks, "chapters_s": chapter_totals,
                    "basis": "declared_measured_voice_durations_plus_explicit_nonoverlapping_blocks"},
        "counts": dict(levels), "findings": findings,
        "limits": ["No render, playback, semantic/official-source acceptance, or speech-duration remeasurement is performed.",
                   "All mutable media are read-only; only the requested report is written.",
                   "Only explicitly listed approved components are hashed; snapshot provenance is a human responsibility."],
    }
    dump_json(args.out, report, forbidden=forbidden)
    print(json.dumps({"status": report["status"], "runtime_s": total, "counts": dict(levels)}, ensure_ascii=False))
    return 2 if levels["error"] else 0


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a planning template; never overwrite project.json")
    init.add_argument("out")
    init.add_argument("--chapters", type=positive_int, required=True)
    init.add_argument("--max-seconds", type=positive_float, default=600)
    init.add_argument("--fps", type=positive_float, default=25)
    init.set_defaults(run=init_project)
    inv = sub.add_parser("inventory", help="Metadata-only inventory; explicit --probe optionally reads media")
    inv.add_argument("source")
    inv.add_argument("--out", required=True)
    inv.add_argument("--probe", action="store_true")
    inv.add_argument("--timeout", type=positive_float, default=15)
    inv.set_defaults(run=inventory)
    check = sub.add_parser("check", help="Read-only machine checks; writes only the requested JSON report")
    check.add_argument("project")
    check.add_argument("--out", required=True)
    check.set_defaults(run=check_project)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (OSError, ValueError, TypeError) as exc:
        print(f"filmkit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
