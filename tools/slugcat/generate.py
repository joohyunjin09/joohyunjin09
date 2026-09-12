"""Run from the repository root: python -m tools.slugcat.generate [--fetch]."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from .contributions import atomic_write, load_calendar, valid_user
from .motion import DURATION, PHYSICS_HZ, TAIL_LENGTHS, simulate
from .render import render


def generate(user: str, output: Path, as_of: date, fetch: bool = False, fps: int = 24,
             cache: Path | None = None) -> dict:
    cache = cache or output / "contributions.json"
    calendar, notice = load_calendar(user, as_of, cache, fetch)
    if notice:
        print(f"WARNING: {notice}", file=sys.stderr)
    animation = simulate(calendar, fps)
    # Build and validate ALL variants before changing any published file.
    documents = {}
    for theme in ("light", "dark"):
        documents[f"slugcat-{theme}.svg"] = render(calendar, animation, theme)
        documents[f"slugcat-{theme}-static.svg"] = render(calendar, animation, theme, False)
    manifest = {
        "version": 1, "user": user, "character": "white", "character_count": 1,
        "source": calendar.source, "as_of": str(calendar.as_of),
        "total_contributions": calendar.total if calendar.source != "layout" else None,
        "seed": calendar.seed, "duration_seconds": DURATION, "physics_hz": PHYSICS_HZ,
        "sample_fps": fps, "samples": len(animation.frames), "tail_segments": len(TAIL_LENGTHS),
        "loop_error_before_endpoint_snap_px": round(animation.seam_error, 8),
        "warmup_cycles": animation.warmup_cycles,
        "interest_date": str(animation.plan.interest.date),
        "states": [{"state": beat.state, "start_seconds": round(beat.start, 3),
                    "duration_seconds": round(beat.duration, 3)} for beat in animation.plan.beats],
        "files": {name: {"bytes": len(text.encode()), "sha256": hashlib.sha256(text.encode()).hexdigest()}
                  for name, text in documents.items()},
    }
    for name, text in documents.items():
        atomic_write(output / name, text)
    if calendar.source == "github":
        atomic_write(cache, calendar.serialize())
    atomic_write(output / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Generated {len(documents)} SVGs: {calendar.source}, {calendar.as_of}, "
          f"{DURATION:.1f}s, {fps} fps samples, seam {animation.seam_error:.6f}px")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", type=valid_user, default="joohyunjin09")
    parser.add_argument("--output", type=Path, default=Path("assets/slugcat"))
    parser.add_argument("--cache", type=Path, help="Optional validated input/output calendar cache")
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    parser.add_argument("--fetch", action="store_true", help="Read GitHub GraphQL using GH_TOKEN or GITHUB_TOKEN")
    parser.add_argument("--fps", type=int, choices=(12, 20, 24, 30, 40, 60), default=24)
    args = parser.parse_args()
    try:
        generate(args.user, args.output, args.date, args.fetch, args.fps, args.cache)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
