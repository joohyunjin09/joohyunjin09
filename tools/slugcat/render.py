"""Bake sampled rig geometry into self-contained, script-free SVG/SMIL tracks."""
from __future__ import annotations

from math import hypot, isfinite
import xml.etree.ElementTree as ET

from .contributions import Calendar
from .motion import (Animation, CELL, DURATION, FLOOR, GRID_X, GRID_Y, HEIGHT,
                     Pose, STRIDE, TAIL_RADII, WIDTH, mix)

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
PALETTES = {
    "light": {"cells": ("#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"),
              "line": "#c8d1ca", "text": "#637067", "outline": "#929e94", "shadow": "#9da89e"},
    "dark": {"cells": ("#1b232b", "#0e4429", "#006d32", "#26a641", "#39d353"),
             "line": "#344139", "text": "#8d9c91", "outline": "#c0cbbd", "shadow": "#050906"},
}


def element(parent: ET.Element, tag: str, **attrs: object) -> ET.Element:
    return ET.SubElement(parent, f"{{{NS}}}{tag}", {k.replace("_", "-"): str(v) for k, v in attrs.items()})


def number(value: float, precision: int = 2) -> str:
    if not isfinite(value):
        raise ValueError("Non-finite SVG coordinate")
    result = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    return "0" if result in {"", "-0"} else result


def numbers(values: tuple | list) -> str:
    return " ".join(number(value) for value in values)


def simplify(values: list[tuple[float, ...]], tolerance: float) -> list[int]:
    """Multidimensional RDP; retain time indices, with bounded coordinate error."""
    kept = {0, len(values) - 1}
    stack = [(0, len(values) - 1)]
    while stack:
        first, last = stack.pop()
        maximum, index = tolerance, -1
        if last <= first + 1:
            continue
        a, b = values[first], values[last]
        for i in range(first + 1, last):
            q = (i - first) / (last - first)
            error = max(abs(v - mix(x, y, q)) for v, x, y in zip(values[i], a, b))
            if error > maximum:
                maximum, index = error, i
        if index != -1:
            kept.add(index)
            stack.extend(((first, index), (index, last)))
    return sorted(kept)


def track(parent: ET.Element, attribute: str, values: list[tuple[float, ...]],
          formatter=numbers, tolerance: float = 0.12, transform: str | None = None,
          animated: bool = True) -> None:
    initial = formatter(values[0])
    parent.set(attribute, f"{transform}({initial})" if transform else initial)
    if not animated or all(value == values[0] for value in values):
        return
    indices = simplify(values, tolerance)
    attrs = {
        "attributeName": attribute, "dur": f"{number(DURATION)}s",
        "repeatCount": "indefinite", "calcMode": "linear",
        "keyTimes": ";".join(number(i / (len(values) - 1), 7) for i in indices),
        "values": ";".join(formatter(values[i]) for i in indices),
    }
    if transform:
        attrs["type"] = transform
    element(parent, "animateTransform" if transform else "animate", **attrs)


def path_format(commands: tuple[tuple[str, int], ...]):
    def format_path(values: tuple[float, ...]) -> str:
        result, at = [], 0
        for command, size in commands:
            result.append(command + numbers(values[at:at + size]))
            at += size
        if at != len(values):
            raise ValueError("SVG path topology mismatch")
        return " ".join(result)
    return format_path


def ribbon(points: tuple, radii: tuple) -> tuple[tuple, tuple[float, ...]]:
    upper, lower = [], []
    for i, (point, radius) in enumerate(zip(points, radii)):
        before, after = points[max(0, i - 1)], points[min(len(points) - 1, i + 1)]
        dx, dy = after[0] - before[0], after[1] - before[1]
        length = max(0.001, hypot(dx, dy))
        nx, ny = -dy / length, dx / length
        upper.append((point[0] + nx * radius, point[1] + ny * radius))
        lower.append((point[0] - nx * radius, point[1] - ny * radius))
    commands, values = [("M", 2)], list(upper[0])
    for edge in (upper, list(reversed(lower))):
        if edge is not upper:
            commands.append(("L", 2))
            values.extend(edge[0])
        for i in range(1, len(edge) - 1):
            end = edge[i + 1] if i == len(edge) - 2 else (
                (edge[i][0] + edge[i + 1][0]) / 2, (edge[i][1] + edge[i + 1][1]) / 2)
            commands.append(("Q", 4))
            values.extend((*edge[i], *end))
    commands.append(("Z", 0))
    return tuple(commands), tuple(values)


BODY_COMMANDS = (("M", 2), ("Q", 4), ("Q", 4), ("Q", 4), ("Q", 4), ("Q", 4), ("Z", 0))
LIMB_COMMANDS = (("M", 2), ("Q", 4), ("Q", 4))
ARM_COMMANDS = (("M", 2), ("Q", 4))
HEAD_PATH = ("M-10 3 Q-11.8-1-9.3-5.7 L-9.1-13.8 Q-9.1-17.6-6.6-16.6 "
             "Q-3.3-15-2.1-7.6 Q0.4-8.3 3-7.3 L5.2-15.3 Q6.2-18 8-15.8 "
             "Q11.4-11.8 10-4.2 Q12.5-0.1 10.7 4.2 Q9.8 8.7 4.2 9.5 "
             "Q-2.1 10.8-6.8 7.7 Q-10.1 5.5-10 3 Z")


def body(pose: Pose) -> tuple[float, ...]:
    hx, hy = pose.hips
    cx, cy = pose.chest
    dx, dy = cx - hx, cy - hy
    length = max(1, hypot(dx, dy))
    ux, uy = dx / length, dy / length
    rx, ry = -uy, ux
    width = 1 + pose.breath * 0.009 + pose.compression * 0.012

    def at(x: float, y: float, right: float, up: float) -> tuple[float, float]:
        return x + rx * right * width + ux * up, y + ry * right * width + uy * up

    top = at(cx, cy, 0, 5.4)
    points = (top, at(cx, cy, -7.6, 6), at(cx, cy, -7.7, -1),
              at(hx, hy, -10, 4), at(hx, hy, -8.5, -2),
              at(hx, hy, -6.2, -8.1), at(hx, hy, 0, -8.2),
              at(hx, hy, 10, -8), at(hx, hy, 9, 0),
              at(cx, cy, 9.3, 5.8), top)
    return tuple(value for point in points for value in point)


def leg(pose: Pose, side: int) -> tuple[float, ...]:
    hip = (pose.hips[0] + side * 3 - 1.5, pose.hips[1] + 2)
    foot = pose.feet[side]
    toe = (foot[0] + pose.facing * 3.3, foot[1] - 0.3)
    return (*hip, *pose.knees[side], *foot, foot[0] + pose.facing * 1.2, foot[1] + 0.5, *toe)


def arm(pose: Pose, side: int) -> tuple[float, ...]:
    shoulder = (pose.chest[0] + (-5 if side == 0 else 5), pose.chest[1] + 2)
    return (*shoulder, *pose.elbows[side], *pose.hands[side])


def draw_pet(parent: ET.Element, frames: tuple[Pose, ...], palette: dict,
             animated: bool, name: str) -> None:
    shadow = element(parent, "g", opacity="0.24")
    track(shadow, "transform", [(p.root[0], FLOOR + 1.6) for p in frames], transform="translate", animated=animated)
    ellipse = element(shadow, "ellipse", cy="0", ry="2", fill=palette["shadow"])
    track(ellipse, "rx", [(max(7, 16 - p.elevation * 0.21),) for p in frames], animated=animated)
    track(shadow, "opacity", [(max(0.06, 0.24 - p.elevation * 0.005),) for p in frames], tolerance=0.004, animated=animated)
    pet = element(parent, "g", id=name, stroke_linecap="round", stroke_linejoin="round")
    track(pet, "transform", [p.root for p in frames], transform="translate", animated=animated)

    tail_data = [ribbon(p.tail, TAIL_RADII) for p in frames]
    tail = element(pet, "path", fill="#e8ecdf", stroke=palette["outline"], stroke_width="0.55")
    track(tail, "d", [data[1] for data in tail_data], path_format(tail_data[0][0]), animated=animated)
    for side in range(2):
        limb = element(pet, "path", fill="none", stroke="#d5ddcf" if side == 0 else "#f2f4e9",
                       stroke_width="5.2" if side == 0 else "5.7")
        track(limb, "d", [leg(p, side) for p in frames], path_format(LIMB_COMMANDS), animated=animated)
    far_arm = element(pet, "path", fill="none", stroke="#d0daca", stroke_width="3.7")
    track(far_arm, "d", [arm(p, 0) for p in frames], path_format(ARM_COMMANDS), animated=animated)
    torso = element(pet, "path", fill="#f2f4e9", stroke=palette["outline"], stroke_width="0.55")
    track(torso, "d", [body(p) for p in frames], path_format(BODY_COMMANDS), animated=animated)
    near_arm = element(pet, "path", fill="none", stroke=palette["outline"], stroke_width="4.7")
    track(near_arm, "d", [arm(p, 1) for p in frames], path_format(ARM_COMMANDS), animated=animated)
    hand_fill = element(pet, "path", fill="none", stroke="#fafbf1", stroke_width="3.6")
    track(hand_fill, "d", [arm(p, 1) for p in frames], path_format(ARM_COMMANDS), animated=animated)

    head_position = element(pet, "g")
    track(head_position, "transform", [p.head for p in frames], transform="translate", tolerance=0.09, animated=animated)
    head_rotation = element(head_position, "g")
    track(head_rotation, "transform", [(p.angle,) for p in frames], transform="rotate", tolerance=0.14, animated=animated)
    element(head_rotation, "path", d=HEAD_PATH, fill="#fafbf1", stroke=palette["outline"], stroke_width="0.6")
    # A quiet lower-cheek shade, no borrowed atlas, pink ears or cartoon mouth.
    element(head_rotation, "path", d="M-8 5.3 Q-2 9.1 6.8 6.9 Q3.5 10.2-2.5 9 Q-6.3 8.2-8 5.3Z",
            fill="#e2e8d9", opacity="0.65")
    face = element(head_rotation, "g")
    track(face, "transform", [(p.gaze[0] * 3.1, 1.9 + p.gaze[1] * 1.15) for p in frames],
          transform="translate", tolerance=0.06, animated=animated)
    lids = element(face, "g", fill="#172019")
    track(lids, "transform", [(1 - abs(p.gaze[0]) * 0.08, p.blink) for p in frames],
          transform="scale", tolerance=0.013, animated=animated)
    element(lids, "ellipse", cx="-3.5", cy="0", rx="1.5", ry="2.65")
    element(lids, "ellipse", cx="3.6", cy="0", rx="1.65", ry="2.85")


def render(calendar: Calendar, animation: Animation, theme: str = "light",
           animated: bool = True, frame: int = 0) -> str:
    if theme not in PALETTES:
        raise ValueError("Unknown theme")
    palette = PALETTES[theme]
    root = ET.Element(f"{{{NS}}}svg", {
        "width": str(WIDTH), "height": str(HEIGHT), "viewBox": f"0 0 {WIDTH} {HEIGHT}",
        "role": "img", "aria-labelledby": "title description"
    })
    element(root, "title", id="title").text = "A white slugcat taking a walk between commits"
    mode = "GitHub contribution snapshot" if calendar.source != "layout" else "Layout only; not contribution activity"
    element(root, "desc", id="description").text = (
        f"One white slugcat breathes, blinks, walks, inspects a cell, hops and turns. "
        f"Offline procedural simulation baked into a {number(DURATION)} second loop. "
        f"{mode}, as of {calendar.as_of}. This is a separate README scene, not the native GitHub graph. "
        "No scripts, external fonts, original game sprites or game runtime are included."
    )
    if animated:
        element(root, "style").text = ".still{display:none}@media(prefers-reduced-motion:reduce){.motion{display:none}.still{display:inline}}"
    # No enclosing background: the scene blends into the actual profile surface.
    element(root, "path", d=f"M{GRID_X} {FLOOR + 2.8}H{GRID_X + 52 * STRIDE + CELL}",
            stroke=palette["line"], stroke_width="0.8", fill="none")
    grid = element(root, "g", id="contribution-terrain")
    for day in calendar.days:
        column, row = calendar.position(day)
        rect = element(grid, "rect", x=number(GRID_X + column * STRIDE),
                       y=number(GRID_Y + row * STRIDE), width=number(CELL), height=number(CELL),
                       rx="2", fill=palette["cells"][day.level])
        element(rect, "title").text = (f"{day.date}: {day.count} contributions" if calendar.source != "layout"
                                      else f"{day.date}: layout cell, no activity data")
    label = element(root, "text", x=number(GRID_X), y="234", fill=palette["text"],
                    font_family="ui-monospace, SFMono-Regular, Consolas, monospace", font_size="9")
    label.text = (f"{calendar.total:,} contributions / 365 days" if calendar.source == "github" else
                  f"Cached GitHub snapshot / {calendar.total:,} contributions" if calendar.source == "cache" else
                  "Layout preview / GitHub data not loaded")
    stamp = element(root, "text", x=number(GRID_X + 52 * STRIDE + CELL), y="234",
                    fill=palette["text"], text_anchor="end", font_family="ui-monospace, SFMono-Regular, Consolas, monospace", font_size="9")
    stamp.text = str(calendar.as_of)
    frames = animation.frames if animated else (animation.frames[frame],)
    moving = element(root, "g", **({"class": "motion"} if animated else {}))
    column, row = calendar.position(animation.plan.interest)
    focus = element(moving, "rect", x=number(GRID_X + column * STRIDE - 1.5),
                    y=number(GRID_Y + row * STRIDE - 1.5), width="14", height="14", rx="3",
                    fill="none", stroke=palette["cells"][3] if calendar.source != "layout" else palette["line"],
                    stroke_width="1")
    track(focus, "opacity", [(p.attention * 0.75,) for p in frames], tolerance=0.015, animated=animated)
    draw_pet(moving, frames, palette, animated, "slugcat")
    if animated:
        still = element(root, "g", **{"class": "still"})
        draw_pet(still, (animation.frames[0],), palette, False, "slugcat-still")
    svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    validate_svg(svg)
    return svg


def validate_svg(svg: str) -> None:
    if len(svg.encode()) > 900_000:
        raise ValueError("SVG exceeds the 900 KB README budget")
    root = ET.fromstring(svg)
    forbidden = {"script", "foreignObject", "image", "iframe", "audio", "video"}
    ids = set()
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in forbidden:
            raise ValueError(f"Forbidden SVG element: {tag}")
        for key, value in node.attrib.items():
            if key.lower().startswith("on") or "href" in key.lower():
                raise ValueError("SVG must not execute scripts or load other resources")
            if key == "id":
                if value in ids:
                    raise ValueError("Duplicate SVG id")
                ids.add(value)
        if tag in {"animate", "animateTransform"}:
            values, times = node.attrib["values"].split(";"), node.attrib["keyTimes"].split(";")
            if values[0] != values[-1] or len(values) != len(times):
                raise ValueError("Animation track has a discontinuous loop or mismatched times")
            numeric_times = [float(value) for value in times]
            if numeric_times[0] != 0 or numeric_times[-1] != 1 or any(a >= b for a, b in zip(numeric_times, numeric_times[1:])):
                raise ValueError("Invalid SVG keyTimes")
