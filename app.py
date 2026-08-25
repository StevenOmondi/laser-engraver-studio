from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from laserengraver.core.controller import GrblSerialController, SimulatorController, available_ports
from laserengraver.core.examples import list_demo_jobs
from laserengraver.core.gcode import frame_gcode, gcode_to_svg, line_may_fire_laser
from laserengraver.core.image_to_gcode import image_from_upload, image_to_scanline_gcode, text_to_image
from laserengraver.core.jobs import JobRecord, JobRunner, JobStore
from laserengraver.core.profiles import DEFAULT_PROFILE, LS_ESP32_PRO_V22, LT_20W_A
from laserengraver.core.safety import SafetyLatch


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
DEMO_DIR = BASE_DIR / "demo_examples"
SETTINGS_PATH = DATA_DIR / "settings.json"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

store = JobStore(JOBS_DIR)
runner = JobRunner()
safety = SafetyLatch()
controller = SimulatorController()


def default_settings() -> dict:
    return {
        "machine": LS_ESP32_PRO_V22.to_dict(),
        "laser": LT_20W_A.to_dict(),
        "defaults": {
            "engrave_feed": 1600,
            "cut_feed": 240,
            "raster_width_mm": 65,
            "raster_power": LT_20W_A.default_engrave_power,
            "binary_threshold": 170,
        },
    }


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return default_settings()
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return default_settings()
    merged = default_settings()
    for section, values in loaded.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def save_settings(settings: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


settings = load_settings()


def ensure_demo_files() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    for demo in list_demo_jobs():
        path = DEMO_DIR / f"{demo.key}.gcode"
        if not path.exists():
            path.write_text(demo.gcode, encoding="utf-8")


ensure_demo_files()


def ok(**payload):
    return jsonify({"ok": True, **payload})


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "message": message}), status


def require_connected():
    if not controller.connected:
        raise RuntimeError("Connect to the simulator or controller first.")


def require_idle():
    if runner.is_busy():
        raise RuntimeError("A job is already running.")


def active_limit_axes() -> list[str]:
    status = controller.status().to_dict()
    switches = status.get("limit_switches", {})
    return [axis.upper() for axis in ("x", "y", "z") if switches.get(axis)]


def require_no_active_limits() -> None:
    axes = active_limit_axes()
    if axes:
        raise RuntimeError(
            "Active limit switch detected on "
            + ", ".join(axes)
            + ". Move off the switch, check wiring/invert settings, then unlock before running a job."
        )


def request_number(name: str, default: float, low: float, high: float) -> float:
    source = request.form if request.form else (request.get_json(silent=True) or {})
    try:
        value = float(source.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def request_bool(name: str, default: bool = False) -> bool:
    source = request.form if request.form else (request.get_json(silent=True) or {})
    value = source.get(name, default)
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


@app.context_processor
def inject_globals():
    return {
        "settings": settings,
        "machine": settings["machine"],
        "laser": settings["laser"],
    }


@app.get("/")
def dashboard():
    return render_template("dashboard.html", active_page="dashboard")


@app.get("/designer")
def designer():
    return render_template("designer.html", active_page="designer")


@app.get("/jobs")
def jobs_page():
    return render_template("jobs.html", active_page="jobs")


@app.get("/console")
def console_page():
    return render_template("console.html", active_page="console")


@app.get("/settings")
def settings_page():
    return render_template("settings.html", active_page="settings")


@app.get("/api/status")
def api_status():
    return ok(
        controller=controller.status().to_dict(),
        runner=runner.snapshot(),
        safety=safety.snapshot(),
        log=controller.log_tail(),
    )


@app.get("/api/ports")
def api_ports():
    return ok(ports=available_ports())


@app.post("/api/connect")
def api_connect():
    global controller
    try:
        require_idle()
        data = request.get_json(force=True)
        mode = data.get("mode", "simulator")
        baud = int(data.get("baud") or settings["machine"]["default_baud"])
        next_controller = GrblSerialController() if mode == "serial" else SimulatorController()
        if controller.connected:
            controller.disconnect()
        next_controller.connect(data.get("port"), baud)
        controller = next_controller
        safety.disarm()
        return ok(controller=controller.status().to_dict())
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/disconnect")
def api_disconnect():
    try:
        require_idle()
        controller.disconnect()
        safety.disarm()
        return ok()
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/arm")
def api_arm():
    try:
        require_connected()
        data = request.get_json(force=True)
        safety.arm(data.get("checklist", {}), int(data.get("minutes", 8)))
        return ok(safety=safety.snapshot())
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/disarm")
def api_disarm():
    safety.disarm()
    try:
        if controller.connected:
            controller.send_line("M5", timeout=2)
            controller.send_line("M9", timeout=2)
    except Exception:
        pass
    return ok(safety=safety.snapshot())


@app.post("/api/setup/apply")
def api_apply_setup():
    try:
        require_connected()
        require_idle()
        responses = []
        for command in settings["machine"]["setup_commands"]:
            responses.append({"command": command, "response": controller.send_line(command)})
        return ok(responses=responses)
    except Exception as exc:
        return fail(str(exc))


@app.get("/api/limits")
def api_limits():
    return ok(
        active_axes=active_limit_axes(),
        controller=controller.status().to_dict(),
        notes=[
            "$21 enables hard limits.",
            "$22 enables homing.",
            "$20 enables soft limits after homing is configured.",
            "$5 inverts limit pins and is not changed automatically.",
        ],
    )


@app.post("/api/limits/apply")
def api_apply_limits():
    try:
        require_connected()
        require_idle()
        data = request.get_json(silent=True) or {}
        enable_homing = data.get("homing", True)
        enable_hard_limits = data.get("hard_limits", True)
        enable_soft_limits = data.get("soft_limits", False)
        force = data.get("force", False)
        active_axes = active_limit_axes()
        responses = []
        skipped = []
        warnings = []

        if enable_homing:
            responses.append({"command": "$22=1", "response": controller.send_line("$22=1")})

        if enable_hard_limits:
            if active_axes and not force:
                skipped.append("$21=1")
                warnings.append(
                    f"Hard limits were not enabled because active switch(es) were detected: {', '.join(active_axes)}."
                )
            else:
                responses.append({"command": "$21=1", "response": controller.send_line("$21=1")})

        if enable_soft_limits:
            if not enable_homing:
                skipped.append("$20=1")
                warnings.append("Soft limits need homing enabled first.")
            else:
                responses.append({"command": "$20=1", "response": controller.send_line("$20=1")})

        return ok(
            active_axes=active_axes,
            responses=responses,
            skipped=skipped,
            warnings=warnings,
            controller=controller.status().to_dict(),
        )
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/command")
def api_command():
    try:
        require_connected()
        require_idle()
        data = request.get_json(force=True)
        command = str(data.get("command", "")).strip()
        if not command:
            return fail("Command is empty.")
        if line_may_fire_laser(command):
            require_no_active_limits()
            if not safety.is_armed():
                return fail("Laser-power commands require the safety latch to be armed.", 403)
        response = controller.send_line(command)
        return ok(response=response)
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/jog")
def api_jog():
    try:
        require_connected()
        require_idle()
        data = request.get_json(force=True)
        feed = int(max(50, min(settings["machine"]["max_feed_mm_min"], int(data.get("feed", settings["machine"]["default_jog_feed_mm_min"])))))
        parts = ["$J=G91"]
        for axis in ("x", "y", "z"):
            try:
                value = float(data.get(axis, 0))
            except (TypeError, ValueError):
                value = 0
            if value:
                parts.append(f"{axis.upper()}{value:.3f}")
        parts.append(f"F{feed}")
        if len(parts) == 2:
            return fail("Jog distance is empty.")
        response = controller.send_line(" ".join(parts))
        return ok(response=response)
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/laser/pulse")
def api_laser_pulse():
    try:
        require_connected()
        require_idle()
        require_no_active_limits()
        if not safety.is_armed():
            return fail("Arm the safety latch before any laser pulse.", 403)
        power = int(request_number("power", settings["laser"]["focus_power"], 1, min(25, settings["machine"]["pwm_max"])))
        duration = request_number("duration", 0.12, 0.03, 0.25)
        responses = [
            controller.send_line(f"M3 S{power}", timeout=2),
            controller.send_line(f"G4 P{duration:.2f}", timeout=2),
            controller.send_line("M5", timeout=2),
        ]
        return ok(responses=responses)
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/estop")
def api_estop():
    safety.disarm()
    try:
        if controller.connected:
            runner.stop(controller)
            controller.send_line("M5", timeout=2)
            controller.send_line("M9", timeout=2)
            controller.soft_reset()
    except Exception:
        pass
    return ok(message="Emergency stop sent.")


@app.post("/api/job-control/<action>")
def api_job_control(action: str):
    try:
        require_connected()
        if action == "pause":
            runner.pause(controller)
        elif action == "resume":
            runner.resume(controller)
        elif action == "stop":
            safety.disarm()
            runner.stop(controller)
        else:
            return fail("Unknown job control.")
        return ok(runner=runner.snapshot())
    except Exception as exc:
        return fail(str(exc))


@app.get("/api/examples")
def api_examples():
    return ok(examples=[demo.metadata() for demo in list_demo_jobs()])


@app.post("/api/examples/<key>/create")
def api_create_example(key: str):
    try:
        for demo in list_demo_jobs():
            if demo.key == key:
                record = store.save_job(demo.name, demo.gcode, "demo", demo.metadata())
                return ok(job=record.to_dict())
        return fail("Demo example was not found.", 404)
    except Exception as exc:
        return fail(str(exc))


@app.get("/api/jobs")
def api_jobs():
    return ok(jobs=[job.to_dict() for job in store.list_jobs()])


@app.post("/api/jobs")
def api_create_job():
    try:
        if request.is_json:
            data = request.get_json(force=True)
            name = data.get("name", "Manual G-code")
            gcode = data.get("gcode", "")
        else:
            name = request.form.get("name", "Manual G-code")
            gcode = request.form.get("gcode", "")
        if not gcode.strip():
            return fail("G-code is empty.")
        record = store.save_job(name, gcode, "manual")
        return ok(job=record.to_dict())
    except Exception as exc:
        return fail(str(exc))


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    try:
        record, gcode = store.get_job(job_id)
        return ok(job=record.to_dict(), gcode=gcode)
    except FileNotFoundError:
        return fail("Job was not found.", 404)
    except Exception as exc:
        return fail(str(exc))


@app.get("/api/jobs/<job_id>/download")
def api_job_download(job_id: str):
    try:
        record, _ = store.get_job(job_id)
        return send_file(store.gcode_file(job_id), as_attachment=True, download_name=record.filename)
    except FileNotFoundError:
        return fail("Job was not found.", 404)


@app.get("/api/jobs/<job_id>/preview.svg")
def api_job_preview(job_id: str):
    try:
        record, gcode = store.get_job(job_id)
        svg = gcode_to_svg(gcode, record.name)
        return Response(svg, mimetype="image/svg+xml")
    except FileNotFoundError:
        return fail("Job was not found.", 404)
    except Exception as exc:
        return fail(str(exc))


@app.delete("/api/jobs/<job_id>")
def api_job_delete(job_id: str):
    try:
        require_idle()
        store.delete_job(job_id)
        return ok()
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/jobs/<job_id>/run")
def api_job_run(job_id: str):
    try:
        require_connected()
        require_idle()
        require_no_active_limits()
        if not safety.is_armed():
            return fail("Arm the safety latch before running a laser job.", 403)
        record, gcode = store.get_job(job_id)
        runner.start(record, gcode, controller, on_complete=safety.disarm)
        return ok(runner=runner.snapshot())
    except FileNotFoundError:
        return fail("Job was not found.", 404)
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/jobs/<job_id>/frame")
def api_job_frame(job_id: str):
    try:
        require_connected()
        require_idle()
        require_no_active_limits()
        record, gcode = store.get_job(job_id)
        dry_frame = frame_gcode(gcode)
        frame_record = JobRecord(
            id=f"{record.id}-frame",
            name=f"Frame: {record.name}",
            filename="dry-frame.gcode",
            created_at=record.created_at,
            source="frame",
            metadata={"parent": record.id},
            stats=record.stats,
        )
        runner.start(frame_record, dry_frame, controller)
        return ok(runner=runner.snapshot())
    except FileNotFoundError:
        return fail("Job was not found.", 404)
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/generate/text")
def api_generate_text():
    try:
        source = request.form if request.form else request.get_json(force=True)
        text = str(source.get("text", "Jambo Laser")).strip()
        if len(text) > 160:
            return fail("Text is too long.")
        width = request_number("width_mm", settings["defaults"]["raster_width_mm"], 5, 200)
        power = int(request_number("power", settings["defaults"]["raster_power"], 1, settings["machine"]["pwm_max"]))
        feed = int(request_number("feed", settings["defaults"]["engrave_feed"], 50, settings["machine"]["max_feed_mm_min"]))
        threshold = None if request_bool("grayscale") else int(request_number("threshold", settings["defaults"]["binary_threshold"], 1, 254))
        image = text_to_image(text, int(request_number("font_size", 48, 12, 140)))
        gcode = image_to_scanline_gcode(
            image,
            f"Text engraving - {text[:40]}",
            width_mm=width,
            feed=feed,
            max_power=power,
            pwm_max=settings["machine"]["pwm_max"],
            threshold=threshold,
        )
        record = store.save_job(f"Text - {text[:40]}", gcode, "text", {"text": text})
        return ok(job=record.to_dict())
    except Exception as exc:
        return fail(str(exc))


@app.post("/api/generate/image")
def api_generate_image():
    try:
        upload = request.files.get("image")
        if not upload:
            return fail("Choose an image file.")
        width = request_number("width_mm", settings["defaults"]["raster_width_mm"], 5, 200)
        power = int(request_number("power", settings["defaults"]["raster_power"], 1, settings["machine"]["pwm_max"]))
        feed = int(request_number("feed", settings["defaults"]["engrave_feed"], 50, settings["machine"]["max_feed_mm_min"]))
        threshold = None if request_bool("grayscale") else int(request_number("threshold", settings["defaults"]["binary_threshold"], 1, 254))
        invert = request_bool("invert")
        image = image_from_upload(upload.read())
        gcode = image_to_scanline_gcode(
            image,
            f"Raster image - {upload.filename}",
            width_mm=width,
            feed=feed,
            max_power=power,
            pwm_max=settings["machine"]["pwm_max"],
            threshold=threshold,
            invert=invert,
        )
        record = store.save_job(f"Image - {Path(upload.filename).stem}", gcode, "image", {"filename": upload.filename})
        return ok(job=record.to_dict())
    except Exception as exc:
        return fail(str(exc))


@app.get("/api/settings")
def api_get_settings():
    return ok(settings=settings)


@app.post("/api/settings")
def api_save_settings():
    global settings
    try:
        data = request.get_json(force=True)
        next_settings = load_settings()
        for section in ("machine", "laser", "defaults"):
            if section in data and isinstance(data[section], dict):
                next_settings[section].update(data[section])
        next_settings["machine"]["pwm_max"] = int(max(1, min(5000, next_settings["machine"]["pwm_max"])))
        next_settings["machine"]["max_feed_mm_min"] = int(max(100, min(30000, next_settings["machine"]["max_feed_mm_min"])))
        next_settings["defaults"]["raster_power"] = int(max(1, min(next_settings["machine"]["pwm_max"], next_settings["defaults"]["raster_power"])))
        save_settings(next_settings)
        settings = next_settings
        return ok(settings=settings)
    except Exception as exc:
        return fail(str(exc))


if __name__ == "__main__":
    controller.connect()
    port = int(os.environ.get("LASER_STUDIO_PORT", "5111"))
    app.run(host="127.0.0.1", port=port, debug=False)
