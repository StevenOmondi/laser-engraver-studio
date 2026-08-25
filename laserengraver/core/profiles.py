from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MachineProfile:
    key: str
    name: str
    firmware_family: str
    default_baud: int
    work_width_mm: float
    work_height_mm: float
    pwm_min: int
    pwm_max: int
    max_feed_mm_min: int
    default_jog_feed_mm_min: int
    setup_commands: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["setup_commands"] = list(self.setup_commands)
        data["notes"] = list(self.notes)
        return data


@dataclass(frozen=True)
class LaserProfile:
    key: str
    name: str
    wavelength_nm: int
    optical_power_w: float
    electrical_input: str
    pwm_control: str
    focus: str
    input_port: str
    default_engrave_power: int
    default_cut_power: int
    focus_power: int
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["notes"] = list(self.notes)
        return data


LS_ESP32_PRO_V22 = MachineProfile(
    key="ls_esp32_pro_v22",
    name="LS ESP32 Pro V2.2",
    firmware_family="GRBL / FluidNC compatible",
    default_baud=115200,
    work_width_mm=450.0,
    work_height_mm=450.0,
    pwm_min=0,
    pwm_max=1000,
    max_feed_mm_min=6000,
    default_jog_feed_mm_min=1800,
    setup_commands=(
        "$32=1",
        "$30=1000",
        "$31=0",
        "G21",
        "G90",
        "M5",
    ),
    notes=(
        "Uses a GRBL-style serial stream at 115200 baud by default.",
        "Laser mode should be enabled with $32=1 before engraving.",
        "PWM max is normalized to S1000 in this application.",
    ),
)


LT_20W_A = LaserProfile(
    key="lt_20w_a",
    name="LASER TREE LT-20W-A",
    wavelength_nm=450,
    optical_power_w=4.0,
    electrical_input="12V DC, about 1.6A",
    pwm_control="5V PWM modulation",
    focus="Adjustable focus, about 20-35mm",
    input_port="XH2.54-3P",
    default_engrave_power=220,
    default_cut_power=760,
    focus_power=8,
    notes=(
        "This is a visible blue diode laser. Reflections can still injure eyes.",
        "Use air assist for cutting and keep the lens clean.",
        "Start with low test power on every new material.",
    ),
)

