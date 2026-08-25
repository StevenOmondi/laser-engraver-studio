# Laser Engraver Studio

Local Python laser engraver software for an LS ESP32 Pro V2.2 style GRBL/FluidNC controller and a LASER TREE LT-20W-A module.

The app auto-connects to the USB controller when available. Real laser output is blocked unless the controller is connected and the safety-ready check is confirmed for that action.

## Features

- Flask web app with Bootstrap sidebar UI
- USB serial streaming for GRBL-style controllers
- Auto-connect remembers the last successful USB controller
- LS ESP32 Pro V2.2 machine profile
- LT-20W-A laser profile with S0-S1000 PWM defaults
- Safety-ready checks, emergency stop, feed hold, resume, unlock, home, zero, and jog controls
- Live limit-switch state for X/Y/Z plus guarded homing and hard-limit setup
- Demo job generator for alignment, power/speed, grayscale, air-assist cut ladders, kerf strips, slots, circles, and vector line-art
- Text-to-raster and image-to-G-code generators
- Saved job list with dry-frame, run, download, preview, and delete actions
- Console for GRBL commands with laser-power guardrails

## Run

```powershell
cd laser_engraver_software
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Open `http://127.0.0.1:5111`.

## Test

```powershell
.\.venv\Scripts\python -m unittest discover
```

## Hardware Profile

Machine defaults:

- Board: LS ESP32 Pro V2.2
- Host protocol: GRBL / FluidNC compatible serial
- Baud: 115200
- Work area: 450 x 450 mm, editable in Settings
- PWM range: `S0` to `S1000`
- Setup commands: `$32=1`, `$30=1000`, `$31=0`, `G21`, `G90`, `M5`

Laser defaults:

- Module: LASER TREE LT-20W-A
- Wavelength: 450 nm
- Optical output: about 4 W
- Input: 12 V DC, about 1.6 A
- Control: 5 V PWM
- Focus: adjustable, about 20-35 mm

## Real Machine Checklist

- Confirm the board firmware understands GRBL-style commands before running a job.
- Confirm the LT-20W-A PWM/GND/V+ pin order before powering the module.
- Start with a dry frame, then low-power scrap material.
- Keep eyewear, ventilation, enclosure/shielding, clamped material, and fire watch in place.
- Use `M8`/`M9` only if your firmware and wiring map air assist to those commands.

## Demo Examples

The app can generate these from Designer:

- Dry alignment frame
- LT-20W-A power/speed grid
- LT-20W-A grayscale ramp
- Air-assist square cut
- Air-assist pass ladder
- Air-assist speed ladder
- Air-assist kerf strips
- Air-assist slot fit test
- Air-assist circle cut test
- Line-art badge

The same generated examples are also written to `demo_examples/` when the app starts.

## Sources Used For Defaults

- Makerbase MKS DLC32 family docs note GRBL-style PC control, 115200 baud tooling, and LaserGRBL/LightBurn compatibility: <https://github.com/makerbase-mks/MKS-DLC32>
- FluidNC's MKS LS ESP32 Pro hardware page identifies the board family as ESP32-S3 laser-gantry hardware with air assist and flame sensor support: <https://wiki.fluidnc.com/en/hardware/3rd-party/MKS_LS_ESP32_PRo>
- LASER TREE LT-20W-A product page lists 450 nm wavelength, 12 V input, 5 V PWM modulation, and XH2.54-3P input: <https://lasertree.com/products/4w-optical-output-power-adjustable-focal-450nm-laser-module>
