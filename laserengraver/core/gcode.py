from __future__ import annotations

import math
import re
from dataclasses import dataclass
from html import escape
from typing import Iterable


COMMENT_PARENS_RE = re.compile(r"\([^)]*\)")
COMMENT_SEMICOLON_RE = re.compile(r";.*$")
WORD_RE = re.compile(r"([A-Z$])\s*(-?\d+(?:\.\d+)?)?", re.IGNORECASE)
G0_RE = re.compile(r"\bG0?0\b", re.IGNORECASE)
G1_RE = re.compile(r"\bG0?1\b", re.IGNORECASE)
G90_RE = re.compile(r"\bG90\b", re.IGNORECASE)
G91_RE = re.compile(r"\bG91\b", re.IGNORECASE)
M3_M4_RE = re.compile(r"\bM0?[34]\b", re.IGNORECASE)
M5_RE = re.compile(r"\bM0?5\b", re.IGNORECASE)


def strip_comments(line: str) -> str:
    line = COMMENT_PARENS_RE.sub("", line)
    line = COMMENT_SEMICOLON_RE.sub("", line)
    return line.strip()


def clean_gcode_line(line: str) -> str:
    return " ".join(strip_comments(line).upper().split())


def streamable_lines(gcode: str) -> list[str]:
    lines: list[str] = []
    for raw in gcode.splitlines():
        clean = clean_gcode_line(raw)
        if clean:
            lines.append(clean)
    return lines


def line_may_fire_laser(line: str) -> bool:
    clean = clean_gcode_line(line)
    if not clean:
        return False
    if re.search(r"\bM0?5\b", clean):
        return False
    if re.search(r"\bM0?[34]\b", clean):
        return True
    s_match = re.search(r"\bS\s*(-?\d+(?:\.\d+)?)\b", clean)
    if s_match:
        try:
            return float(s_match.group(1)) > 0
        except ValueError:
            return True
    return False


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def line_words(line: str) -> dict[str, str]:
    return dict((m.group(1).upper(), m.group(2)) for m in WORD_RE.finditer(line) if m.group(2))


def motion_code(line: str) -> str | None:
    if G0_RE.search(line):
        return "G0"
    if G1_RE.search(line):
        return "G1"
    return None


@dataclass
class GCodeStats:
    line_count: int
    motion_lines: int
    laser_lines: int
    min_x: float | None
    min_y: float | None
    max_x: float | None
    max_y: float | None
    max_power: int
    estimated_minutes: float

    @property
    def width_mm(self) -> float:
        if self.min_x is None or self.max_x is None:
            return 0.0
        return max(0.0, self.max_x - self.min_x)

    @property
    def height_mm(self) -> float:
        if self.min_y is None or self.max_y is None:
            return 0.0
        return max(0.0, self.max_y - self.min_y)

    def to_dict(self) -> dict:
        return {
            "line_count": self.line_count,
            "motion_lines": self.motion_lines,
            "laser_lines": self.laser_lines,
            "min_x": self.min_x,
            "min_y": self.min_y,
            "max_x": self.max_x,
            "max_y": self.max_y,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "max_power": self.max_power,
            "estimated_minutes": round(self.estimated_minutes, 2),
        }


def gcode_stats(gcode: str) -> GCodeStats:
    line_count = 0
    motion_lines = 0
    laser_lines = 0
    max_power = 0
    min_x = min_y = max_x = max_y = None
    x = y = 0.0
    feed = 1200.0
    distance = 0.0

    for line in streamable_lines(gcode):
        line_count += 1
        words = line_words(line)
        next_x = x
        next_y = y
        code = motion_code(line)
        has_motion = code is not None
        if "F" in words:
            try:
                feed = max(1.0, float(words["F"]))
            except ValueError:
                pass
        if "S" in words:
            try:
                max_power = max(max_power, int(float(words["S"])))
            except ValueError:
                pass
        if "X" in words:
            try:
                next_x = float(words["X"])
            except ValueError:
                pass
        if "Y" in words:
            try:
                next_y = float(words["Y"])
            except ValueError:
                pass
        if has_motion:
            motion_lines += 1
            step = math.hypot(next_x - x, next_y - y)
            if code == "G1":
                distance += step / feed
            for px, py in ((next_x, next_y),):
                min_x = px if min_x is None else min(min_x, px)
                max_x = px if max_x is None else max(max_x, px)
                min_y = py if min_y is None else min(min_y, py)
                max_y = py if max_y is None else max(max_y, py)
        if line_may_fire_laser(line):
            laser_lines += 1
        x, y = next_x, next_y

    return GCodeStats(
        line_count=line_count,
        motion_lines=motion_lines,
        laser_lines=laser_lines,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        max_power=max_power,
        estimated_minutes=distance,
    )


def gcode_segments(gcode: str) -> list[dict]:
    segments: list[dict] = []
    x = y = 0.0
    absolute = True
    laser_enabled = False
    power = 0

    for line in streamable_lines(gcode):
        words = line_words(line)
        if G90_RE.search(line):
            absolute = True
        elif G91_RE.search(line):
            absolute = False
        if M5_RE.search(line):
            laser_enabled = False
            power = 0
        if "S" in words:
            try:
                power = max(0, int(float(words["S"])))
            except ValueError:
                pass
        if M3_M4_RE.search(line):
            laser_enabled = True

        code = motion_code(line)
        if code is None:
            continue

        next_x = x
        next_y = y
        if "X" in words:
            value = float(words["X"])
            next_x = value if absolute else x + value
        if "Y" in words:
            value = float(words["Y"])
            next_y = value if absolute else y + value

        if next_x != x or next_y != y:
            segments.append(
                {
                    "x1": x,
                    "y1": y,
                    "x2": next_x,
                    "y2": next_y,
                    "rapid": code == "G0",
                    "laser": code == "G1" and laser_enabled and power > 0,
                    "power": power,
                }
            )
        x, y = next_x, next_y

    return segments


def gcode_to_svg(gcode: str, title: str = "G-code preview", width: int = 900, height: int = 520, max_segments: int = 2200) -> str:
    segments = gcode_segments(gcode)
    if not segments:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">'
            '<rect width="100%" height="100%" rx="8" fill="#f8fafc"/>'
            f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" fill="#64748b" '
            'font-family="Arial, sans-serif" font-size="22">No XY toolpath</text></svg>'
        )

    sampled = False
    if len(segments) > max_segments:
        step = max(1, math.ceil(len(segments) / max_segments))
        segments = segments[::step]
        sampled = True

    xs = [value for segment in segments for value in (segment["x1"], segment["x2"])]
    ys = [value for segment in segments for value in (segment["y1"], segment["y2"])]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    job_width = max(1.0, max_x - min_x)
    job_height = max(1.0, max_y - min_y)
    pad = 34
    scale = min((width - pad * 2) / job_width, (height - pad * 2) / job_height)
    offset_x = (width - job_width * scale) / 2
    offset_y = (height - job_height * scale) / 2
    stroke_width = max(0.8, min(width, height) / 780)

    def sx(value: float) -> float:
        return offset_x + (value - min_x) * scale

    def sy(value: float) -> float:
        return offset_y + (max_y - value) * scale

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        '<rect width="100%" height="100%" rx="8" fill="#f8fafc"/>',
        '<g stroke-linecap="round" stroke-linejoin="round" fill="none">',
    ]
    for segment in segments:
        color = "#d92d20" if segment["laser"] else ("#94a3b8" if segment["rapid"] else "#2563eb")
        dash = ' stroke-dasharray="5 5"' if segment["rapid"] else ""
        opacity = 0.35 if segment["rapid"] else min(0.95, 0.35 + (segment["power"] / 1000))
        lines.append(
            f'<line x1="{sx(segment["x1"]):.2f}" y1="{sy(segment["y1"]):.2f}" '
            f'x2="{sx(segment["x2"]):.2f}" y2="{sy(segment["y2"]):.2f}" '
            f'stroke="{color}" stroke-width="{stroke_width:.2f}" opacity="{opacity:.2f}"{dash}/>'
        )
    lines.extend(
        [
            "</g>",
            f'<text x="14" y="24" fill="#334155" font-family="Arial, sans-serif" font-size="14">{escape(title)}</text>',
            f'<text x="14" y="{height - 14}" fill="#64748b" font-family="Arial, sans-serif" font-size="12">'
            f'{job_width:.1f} x {job_height:.1f} mm{" - sampled" if sampled else ""}</text>',
            "</svg>",
        ]
    )
    return "".join(lines)


class GCodeBuilder:
    def __init__(self, title: str, pwm_max: int = 1000):
        self.title = title
        self.pwm_max = pwm_max
        self.lines: list[str] = [
            f"; {title}",
            "; Generated by Codex Laser Engraver",
            "G21",
            "G90",
            "G94",
            "M5",
        ]

    def comment(self, text: str) -> None:
        self.lines.append(f"; {text}")

    def add(self, line: str) -> None:
        self.lines.append(line)

    def rapid(self, x: float | None = None, y: float | None = None, z: float | None = None, feed: int | None = None) -> None:
        parts = ["G0"]
        if x is not None:
            parts.append(f"X{x:.3f}")
        if y is not None:
            parts.append(f"Y{y:.3f}")
        if z is not None:
            parts.append(f"Z{z:.3f}")
        if feed is not None:
            parts.append(f"F{feed}")
        self.lines.append(" ".join(parts))

    def cut(self, x: float | None = None, y: float | None = None, feed: int = 1200, power: int | None = None) -> None:
        parts = ["G1"]
        if x is not None:
            parts.append(f"X{x:.3f}")
        if y is not None:
            parts.append(f"Y{y:.3f}")
        parts.append(f"F{feed}")
        if power is not None:
            parts.append(f"S{int(clamp(power, 0, self.pwm_max))}")
        self.lines.append(" ".join(parts))

    def laser_on(self, power: int, dynamic: bool = True) -> None:
        code = "M4" if dynamic else "M3"
        self.lines.append(f"{code} S{int(clamp(power, 0, self.pwm_max))}")

    def laser_off(self) -> None:
        self.lines.append("M5")

    def air_on(self) -> None:
        self.lines.append("M8")

    def air_off(self) -> None:
        self.lines.append("M9")

    def finish(self) -> str:
        self.lines.extend(["M5", "M9", "G0 X0 Y0", "; End"])
        return "\n".join(self.lines) + "\n"


def frame_gcode(gcode: str, margin_mm: float = 2.0, feed: int = 3000) -> str:
    stats = gcode_stats(gcode)
    if stats.min_x is None or stats.min_y is None or stats.max_x is None or stats.max_y is None:
        raise ValueError("Job has no XY motion to frame.")
    x0 = max(0.0, stats.min_x - margin_mm)
    y0 = max(0.0, stats.min_y - margin_mm)
    x1 = stats.max_x + margin_mm
    y1 = stats.max_y + margin_mm
    b = GCodeBuilder("Dry frame preview")
    b.comment("Laser disabled for boundary preview")
    b.laser_off()
    b.rapid(x0, y0, feed=feed)
    b.rapid(x1, y0, feed=feed)
    b.rapid(x1, y1, feed=feed)
    b.rapid(x0, y1, feed=feed)
    b.rapid(x0, y0, feed=feed)
    b.laser_off()
    return b.finish()


def rectangle_fill(
    b: GCodeBuilder,
    x: float,
    y: float,
    width: float,
    height: float,
    line_spacing: float,
    feed: int,
    power: int,
) -> None:
    rows = max(1, int(height / max(0.05, line_spacing)))
    for row in range(rows + 1):
        yy = y + min(height, row * line_spacing)
        if row % 2 == 0:
            start_x, end_x = x, x + width
        else:
            start_x, end_x = x + width, x
        b.rapid(start_x, yy)
        b.laser_on(power)
        b.cut(end_x, yy, feed=feed, power=power)
        b.laser_off()


def polyline(
    b: GCodeBuilder,
    points: Iterable[tuple[float, float]],
    feed: int,
    power: int,
    close: bool = False,
) -> None:
    pts = list(points)
    if not pts:
        return
    b.rapid(pts[0][0], pts[0][1])
    b.laser_on(power)
    for px, py in pts[1:]:
        b.cut(px, py, feed=feed, power=power)
    if close:
        b.cut(pts[0][0], pts[0][1], feed=feed, power=power)
    b.laser_off()
