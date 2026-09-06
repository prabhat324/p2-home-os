#!/usr/bin/env python3
"""BeSquare V6.1 knowledge-video guardrail.

Runs before the main render for explainer/feature projects. It intentionally
validates editorial intent and benchmark availability without trying to be an
editor itself. Podcasts are excluded by the caller.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_num(obj, names):
    for name in names:
        if name in obj:
            value = num(obj.get(name))
            if value is not None:
                return value
    return None


def event_times(event):
    start = first_num(event, ("start", "start_seconds", "time", "at", "in"))
    end = first_num(event, ("end", "end_seconds", "out"))
    duration = first_num(event, ("duration", "duration_seconds", "length"))
    if start is not None and end is None and duration is not None:
        end = start + duration
    if start is None:
        start = 0.0
    if end is not None:
        duration = max(0.0, end - start)
    return start, end, duration


def event_kind(event):
    return str(event.get("kind") or event.get("type") or event.get("effect") or "").strip().lower()


def has_source(event):
    source_keys = {
        "source", "source_url", "source_label", "citation", "evidence", "evidence_id",
        "claim_id", "research_id", "attribution", "document", "url"
    }
    if any(event.get(k) for k in source_keys):
        return True
    meta = event.get("metadata")
    return isinstance(meta, dict) and any(meta.get(k) for k in source_keys)


def extract_scale(event):
    vals = []
    for key in ("scale", "zoom", "zoom_scale", "from_scale", "to_scale", "start_scale", "end_scale"):
        v = num(event.get(key))
        if v is not None:
            vals.append(v)
    params = event.get("params")
    if isinstance(params, dict):
        for key in ("scale", "zoom", "from_scale", "to_scale", "start_scale", "end_scale"):
            v = num(params.get(key))
            if v is not None:
                vals.append(v)
    return vals


def asset_identity(event):
    for key in ("asset_path", "asset", "image", "video", "path", "source_path"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--timeline", type=Path, required=True)
    ap.add_argument("--standard", type=Path, required=True)
    ap.add_argument("--verification", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    manifest = load(args.manifest, {})
    timeline = load(args.timeline, {})
    standard = load(args.standard, {})
    verification = load(args.verification, {})
    failures = []
    warnings = []
    metrics = {}

    sid = standard.get("standard_id")
    if sid != "besquare-knowledge-v1":
        failures.append("Canonical BeSquare knowledge-video standard is missing or invalid")

    benchmark = standard.get("benchmark", {})
    expected_sha = benchmark.get("sha256")
    expected_size = int(benchmark.get("size_bytes") or 0)
    ref = Path(benchmark.get("reference_path") or "")
    if not ref.is_file():
        failures.append(f"V6.1 benchmark master is missing: {ref}")
    else:
        actual_size = ref.stat().st_size
        metrics["benchmark_size_bytes"] = actual_size
        if expected_size and actual_size != expected_size:
            failures.append(f"V6.1 benchmark size mismatch: {actual_size} != {expected_size}")
    if verification.get("standard_id") != sid or verification.get("benchmark_sha256") != expected_sha:
        failures.append("V6.1 benchmark checksum verification marker is missing/stale")
    if verification.get("benchmark_size_bytes") != expected_size:
        failures.append("V6.1 benchmark verification marker has the wrong size")

    mode = str(manifest.get("mode", "explainer")).lower()
    metrics["mode"] = mode
    if mode == "podcast":
        failures.append("Knowledge-video guardrail was called for podcast mode; route podcasts through podcast policy")

    # OpenMontage is asset-only. Catch explicit attempts to make it the main editor.
    om = manifest.get("openmontage")
    om_mode = ""
    if isinstance(om, dict):
        om_mode = str(om.get("mode") or om.get("role") or "").lower()
    elif isinstance(om, str):
        om_mode = om.lower()
    om_mode = str(manifest.get("openmontage_mode") or om_mode).lower()
    editor = str(manifest.get("editor") or manifest.get("editing_engine") or "").lower()
    prohibited_om = {"full", "full_edit", "full-editor", "full_editor", "timeline", "master", "autonomous"}
    if om_mode in prohibited_om or (editor == "openmontage" and om_mode != "asset_only"):
        failures.append("OpenMontage is asset-only in production and cannot be the primary/full-video editor")

    events = timeline.get("events", [])
    if not isinstance(events, list):
        failures.append("Timeline events are not a list")
        events = []
    metrics["event_count"] = len(events)

    duration = first_num(timeline, ("duration", "duration_seconds", "source_duration"))
    if duration is None:
        duration = first_num(manifest, ("duration", "duration_seconds"))

    zoom_starts = []
    zoom_count = 0
    sourced_count = 0
    graph_count = 0
    nonzoom_count = 0
    recent_assets = {}

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            warnings.append(f"Timeline event {index} is not an object")
            continue
        kind = event_kind(event)
        start, end, ev_duration = event_times(event)
        if end is not None and end < start:
            failures.append(f"Event {index} ends before it starts")
        if duration is not None and start > duration + 0.5:
            failures.append(f"Event {index} starts beyond source duration")

        if kind == "zoom" or "zoom" in kind:
            zoom_count += 1
            zoom_starts.append(start)
            scales = extract_scale(event)
            if scales:
                max_scale = max(scales)
                min_scale = min(scales)
                if max_scale > 1.22:
                    failures.append(f"Zoom event {index} exceeds 1.22x scale ({max_scale:.3f})")
                elif max_scale > float(standard.get("camera_motion", {}).get("default_max_zoom_scale", 1.15)):
                    warnings.append(f"Zoom event {index} exceeds V6.1 default zoom guidance ({max_scale:.3f}x)")
                if ev_duration is not None and ev_duration < 1.0 and abs(max_scale - min_scale) > 0.03:
                    failures.append(f"Zoom event {index} changes scale too abruptly ({ev_duration:.2f}s)")
            elif ev_duration is not None and ev_duration < 0.75:
                failures.append(f"Zoom event {index} is too abrupt ({ev_duration:.2f}s)")
        else:
            nonzoom_count += 1
            if has_source(event):
                sourced_count += 1

        if any(token in kind for token in ("graph", "chart", "data", "funding", "metric")):
            graph_count += 1
            if event.get("decorative") is True:
                failures.append(f"Graph/data event {index} is marked decorative")
            if not has_source(event):
                warnings.append(f"Graph/data event {index} has no explicit source metadata; verify source label before publish")
            if not any(event.get(k) for k in ("title", "label", "claim", "question", "headline")):
                warnings.append(f"Graph/data event {index} has no explicit explanatory title/claim")

        asset = asset_identity(event)
        if asset:
            prior = recent_assets.get(asset)
            if prior is not None and start - prior < 15.0 and start >= prior:
                warnings.append(f"Asset is reused within 15s at event {index}: {asset}")
            recent_assets[asset] = start

        # Catch obvious unsafe crop/transition declarations when planners expose them.
        crop = event.get("crop") or (event.get("params", {}).get("crop") if isinstance(event.get("params"), dict) else None)
        if crop and str(event.get("crop_policy") or "").lower() in {"face_crop", "tight_face_crop", "crop_text"}:
            failures.append(f"Event {index} declares a prohibited crop policy")
        transition = str(event.get("transition") or "").lower()
        if transition in {"flash", "strobe", "rapid_zoom", "whip_zoom"}:
            failures.append(f"Event {index} uses prohibited abrupt transition: {transition}")

    zoom_starts.sort()
    for a, b in zip(zoom_starts, zoom_starts[1:]):
        gap = b - a
        if gap < 2.0:
            failures.append(f"Back-to-back zoom starts are only {gap:.2f}s apart")
        elif gap < float(standard.get("camera_motion", {}).get("preferred_minimum_time_between_new_zoom_moves_seconds", 5.0)):
            warnings.append(f"Zoom starts are close together ({gap:.2f}s); compare against V6.1 pacing")

    if duration and duration > 120:
        minimum_meaningful = max(1, math.floor(duration / 120.0))
        if nonzoom_count < minimum_meaningful:
            warnings.append(
                f"Only {nonzoom_count} non-zoom visual events across {duration:.1f}s; "
                "review against V6.1 before accepting a talking-head-heavy cut"
            )

    metrics.update({
        "zoom_events": zoom_count,
        "nonzoom_visual_events": nonzoom_count,
        "explicitly_sourced_nonzoom_events": sourced_count,
        "graph_or_data_events": graph_count,
        "duration_seconds": duration,
        "standard_id": sid,
        "benchmark_reference": str(ref),
        "openmontage_mode": om_mode or None,
    })

    # Protected-term typo check across serialized planning metadata.
    blob = json.dumps({"manifest": manifest, "timeline": timeline}, ensure_ascii=False)
    for wrong in ("Visaga", "visaga", "Wasagga", "Wasga Beach", "B square", "P square"):
        if wrong in blob:
            failures.append(f"Protected-term typo detected in planning metadata: {wrong}")

    status = "PASS" if not failures else "FAIL"
    payload = {
        "status": status,
        "standard_id": sid,
        "benchmark_verified": not any("benchmark" in x.lower() for x in failures),
        "failures": failures,
        "warnings": warnings,
        "metrics": metrics,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
