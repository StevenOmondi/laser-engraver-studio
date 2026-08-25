from __future__ import annotations

import math
from dataclasses import dataclass

from .gcode import GCodeBuilder, polyline, rectangle_fill
from .profiles import LS_ESP32_PRO_V22, LT_20W_A, LaserProfile, MachineProfile


@dataclass
class DemoJob:
    key: str
    name: str
    description: str
    material: str
    gcode: str

    def metadata(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "material": self.material,
        }


def alignment_frame(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LS ESP32 Pro + LT-20W-A alignment frame", machine.pwm_max)
    b.comment("Dry motion frame. No laser power is emitted.")
    b.laser_off()
    w, h = 80.0, 50.0
    x0, y0 = 10.0, 10.0
    b.rapid(x0, y0)
    b.rapid(x0 + w, y0, feed=2500)
    b.rapid(x0 + w, y0 + h, feed=2500)
    b.rapid(x0, y0 + h, feed=2500)
    b.rapid(x0, y0, feed=2500)
    return DemoJob(
        key="alignment_frame",
        name="Dry alignment frame",
        description="Motion-only 80 x 50 mm boundary for checking origin, travel, and clamping.",
        material="Any material, laser disabled",
        gcode=b.finish(),
    )


def power_speed_grid(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A power and speed grid", machine.pwm_max)
    b.comment("Conservative engraving sampler for light wood/cardboard.")
    powers = [80, 140, 220, 320, 430]
    feeds = [600, 1000, 1600, 2400]
    cell = 8.0
    gap = 3.0
    x0, y0 = 12.0, 12.0
    for row, feed in enumerate(feeds):
        for col, power in enumerate(powers):
            x = x0 + col * (cell + gap)
            y = y0 + row * (cell + gap)
            b.comment(f"Cell row feed {feed} mm/min, power S{power}")
            rectangle_fill(b, x, y, cell, cell, 0.55, feed, power)
    return DemoJob(
        key="power_speed_grid",
        name="LT-20W-A power/speed grid",
        description="Small burn-test grid using S80-S430 and 600-2400 mm/min.",
        material="Basswood, cardboard, scrap test stock",
        gcode=b.finish(),
    )


def grayscale_ramp(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A grayscale ramp", machine.pwm_max)
    b.comment("Eight tone blocks for checking grayscale response.")
    x0, y0 = 10.0, 10.0
    width, height = 9.0, 25.0
    for i, power in enumerate([40, 80, 130, 190, 260, 340, 430, 540]):
        x = x0 + i * (width + 2.0)
        rectangle_fill(b, x, y0, width, height, 0.45, 1800, power)
    return DemoJob(
        key="grayscale_ramp",
        name="LT-20W-A grayscale ramp",
        description="Eight filled columns that step from very light to dark engraving power.",
        material="Anodized aluminum card, painted metal, or test wood",
        gcode=b.finish(),
    )


def air_assist_cut_demo(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LS ESP32 Pro air-assist cut demo", machine.pwm_max)
    b.comment("Uses M8/M9 around a conservative multi-pass test square.")
    x0, y0, size = 15.0, 15.0, 22.0
    passes = 3
    b.air_on()
    for pass_number in range(passes):
        b.comment(f"Pass {pass_number + 1} of {passes}")
        polyline(
            b,
            [
                (x0, y0),
                (x0 + size, y0),
                (x0 + size, y0 + size),
                (x0, y0 + size),
            ],
            feed=240,
            power=min(laser.default_cut_power, machine.pwm_max),
            close=True,
        )
    b.air_off()
    return DemoJob(
        key="air_assist_cut_demo",
        name="Air-assist square cut",
        description="Three-pass 22 mm square using M8/M9 air assist commands.",
        material="Thin cardboard or 1 mm basswood scrap",
        gcode=b.finish(),
    )


def _cut_passes(
    b: GCodeBuilder,
    points: list[tuple[float, float]],
    feed: int,
    power: int,
    passes: int,
    close: bool = True,
) -> None:
    for pass_number in range(passes):
        b.comment(f"Cut pass {pass_number + 1} of {passes}")
        polyline(b, points, feed=feed, power=power, close=close)


def _circle_points(cx: float, cy: float, radius: float, segments: int = 44) -> list[tuple[float, float]]:
    return [
        (
            cx + math.cos((math.tau * index) / segments) * radius,
            cy + math.sin((math.tau * index) / segments) * radius,
        )
        for index in range(segments)
    ]


def air_assist_pass_ladder(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A air-assist pass ladder", machine.pwm_max)
    b.comment("Five small squares with increasing pass counts for cut-through testing.")
    power = min(laser.default_cut_power, machine.pwm_max)
    feed = 260
    size = 10.0
    b.air_on()
    for index, passes in enumerate([1, 2, 3, 4, 5]):
        x = 10.0 + index * 15.0
        y = 12.0
        b.comment(f"Square {index + 1}: {passes} pass(es), F{feed}, S{power}")
        _cut_passes(
            b,
            [(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
            feed=feed,
            power=power,
            passes=passes,
        )
    b.air_off()
    return DemoJob(
        key="air_assist_pass_ladder",
        name="Air-assist pass ladder",
        description="Five 10 mm squares from 1 to 5 passes to find cut-through depth.",
        material="Cardboard, paperboard, 1-2 mm basswood scrap",
        gcode=b.finish(),
    )


def air_assist_speed_ladder(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A air-assist speed ladder", machine.pwm_max)
    b.comment("Five identical squares at different cutting speeds.")
    power = min(laser.default_cut_power, machine.pwm_max)
    feeds = [160, 220, 300, 420, 600]
    size = 9.0
    b.air_on()
    for index, feed in enumerate(feeds):
        x = 10.0 + index * 14.0
        y = 12.0
        b.comment(f"Square {index + 1}: F{feed}, S{power}, 2 passes")
        _cut_passes(
            b,
            [(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
            feed=feed,
            power=power,
            passes=2,
        )
    b.air_off()
    return DemoJob(
        key="air_assist_speed_ladder",
        name="Air-assist speed ladder",
        description="Five 9 mm squares at 160-600 mm/min with two passes.",
        material="Thin plywood, chipboard, dark acrylic test scrap",
        gcode=b.finish(),
    )


def air_assist_kerf_test(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A air-assist kerf strip test", machine.pwm_max)
    b.comment("Nested strips for measuring kerf and fit after cutting.")
    power = min(laser.default_cut_power, machine.pwm_max)
    feed = 240
    b.air_on()
    for index, width in enumerate([4.0, 5.0, 6.0, 7.0, 8.0]):
        x = 10.0 + index * 13.0
        y = 10.0
        height = 34.0
        b.comment(f"Kerf strip {index + 1}: {width:.1f} x {height:.1f} mm")
        _cut_passes(
            b,
            [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
            feed=feed,
            power=power,
            passes=2,
        )
    b.air_off()
    return DemoJob(
        key="air_assist_kerf_test",
        name="Air-assist kerf strips",
        description="Five narrow strips for checking kerf, char, and part release.",
        material="Basswood or cardboard test stock",
        gcode=b.finish(),
    )


def air_assist_slot_fit_test(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A air-assist slot fit test", machine.pwm_max)
    b.comment("Four slot-width rectangles for friction-fit tuning.")
    power = min(laser.default_cut_power, machine.pwm_max)
    feed = 230
    slot_height = 18.0
    b.air_on()
    for index, width in enumerate([2.6, 2.8, 3.0, 3.2]):
        x = 12.0 + index * 16.0
        y = 12.0
        b.comment(f"Slot {index + 1}: {width:.1f} mm wide")
        _cut_passes(
            b,
            [(x, y), (x + width, y), (x + width, y + slot_height), (x, y + slot_height)],
            feed=feed,
            power=power,
            passes=2,
        )
    b.air_off()
    return DemoJob(
        key="air_assist_slot_fit_test",
        name="Air-assist slot fit test",
        description="Four 18 mm slots from 2.6-3.2 mm for press-fit tuning.",
        material="Material matching the intended project thickness",
        gcode=b.finish(),
    )


def air_assist_circle_cut_test(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A air-assist circle cut test", machine.pwm_max)
    b.comment("Three circular cutouts for testing cornering, char, and release.")
    power = min(laser.default_cut_power, machine.pwm_max)
    feed = 260
    b.air_on()
    for cx, cy, radius in [(18.0, 20.0, 4.0), (36.0, 20.0, 6.0), (58.0, 20.0, 8.0)]:
        b.comment(f"Circle radius {radius:.1f} mm, 2 passes")
        _cut_passes(b, _circle_points(cx, cy, radius), feed=feed, power=power, passes=2)
    b.air_off()
    return DemoJob(
        key="air_assist_circle_cut_test",
        name="Air-assist circle cut test",
        description="Three round cutouts to inspect curve quality and cut-through.",
        material="Cardboard, basswood, or thin plywood scrap",
        gcode=b.finish(),
    )


def line_art_badge(machine: MachineProfile = LS_ESP32_PRO_V22, laser: LaserProfile = LT_20W_A) -> DemoJob:
    b = GCodeBuilder("LT-20W-A line-art badge", machine.pwm_max)
    b.comment("Simple vector badge for confirming motion, PWM, and line quality.")
    power = 260
    feed = 1800
    polyline(b, [(12, 30), (30, 10), (58, 10), (76, 30), (58, 50), (30, 50)], feed, power, close=True)
    polyline(b, [(24, 30), (36, 20), (52, 20), (64, 30), (52, 40), (36, 40)], feed, power, close=True)
    polyline(b, [(36, 30), (52, 30)], feed, power)
    polyline(b, [(44, 22), (44, 38)], feed, power)
    return DemoJob(
        key="line_art_badge",
        name="Line-art badge",
        description="Small vector badge with low-power continuous lines.",
        material="Cardboard, basswood, coated test tile",
        gcode=b.finish(),
    )


def list_demo_jobs() -> list[DemoJob]:
    return [
        alignment_frame(),
        power_speed_grid(),
        grayscale_ramp(),
        air_assist_cut_demo(),
        air_assist_pass_ladder(),
        air_assist_speed_ladder(),
        air_assist_kerf_test(),
        air_assist_slot_fit_test(),
        air_assist_circle_cut_test(),
        line_art_badge(),
    ]
