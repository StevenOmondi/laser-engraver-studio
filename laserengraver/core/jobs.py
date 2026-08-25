from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .controller import BaseController
from .gcode import gcode_stats, streamable_lines


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "job"


JOB_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        raise FileNotFoundError(job_id)
    return job_id


@dataclass
class JobRecord:
    id: str
    name: str
    filename: str
    created_at: float
    source: str
    metadata: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "created_at": self.created_at,
            "created_label": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created_at)),
            "source": self.source,
            "metadata": self.metadata,
            "stats": self.stats,
        }


class JobStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, filename: str) -> Path:
        path = (self.root / filename).resolve()
        if self.root not in path.parents and path != self.root:
            raise FileNotFoundError(filename)
        return path

    def _meta_path(self, job_id: str) -> Path:
        return self._safe_path(f"{validate_job_id(job_id)}.json")

    def _gcode_path(self, job_id: str) -> Path:
        return self._safe_path(f"{validate_job_id(job_id)}.gcode")

    def save_job(self, name: str, gcode: str, source: str, metadata: dict | None = None) -> JobRecord:
        safe_name = name.strip() or "Untitled job"
        job_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(safe_name)}-{uuid.uuid4().hex[:6]}"
        filename = f"{job_id}.gcode"
        created_at = time.time()
        stats = gcode_stats(gcode).to_dict()
        record = JobRecord(
            id=job_id,
            name=safe_name,
            filename=filename,
            created_at=created_at,
            source=source,
            metadata=metadata or {},
            stats=stats,
        )
        self._gcode_path(job_id).write_text(gcode, encoding="utf-8")
        self._meta_path(job_id).write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
        return record

    def list_jobs(self) -> list[JobRecord]:
        records: list[JobRecord] = []
        for meta in sorted(self.root.glob("*.json"), reverse=True):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                records.append(
                    JobRecord(
                        id=data["id"],
                        name=data["name"],
                        filename=data["filename"],
                        created_at=data["created_at"],
                        source=data.get("source", "unknown"),
                        metadata=data.get("metadata", {}),
                        stats=data.get("stats", {}),
                    )
                )
            except Exception:
                continue
        return records

    def get_job(self, job_id: str) -> tuple[JobRecord, str]:
        meta_path = self._meta_path(job_id)
        gcode_path = self._gcode_path(job_id)
        if not meta_path.exists() or not gcode_path.exists():
            raise FileNotFoundError(job_id)
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        record = JobRecord(
            id=data["id"],
            name=data["name"],
            filename=data["filename"],
            created_at=data["created_at"],
            source=data.get("source", "unknown"),
            metadata=data.get("metadata", {}),
            stats=data.get("stats", {}),
        )
        return record, gcode_path.read_text(encoding="utf-8")

    def gcode_file(self, job_id: str) -> Path:
        path = self._gcode_path(job_id)
        if not path.exists():
            raise FileNotFoundError(job_id)
        return path

    def delete_job(self, job_id: str) -> None:
        for path in (self._meta_path(job_id), self._gcode_path(job_id)):
            if path.exists():
                path.unlink()


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self.active_job: dict | None = None
        self.status_text = "idle"
        self.progress = 0
        self.total = 0
        self.error: str | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None

    def is_busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(
        self,
        record: JobRecord,
        gcode: str,
        controller: BaseController,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        with self._lock:
            if self.is_busy():
                raise RuntimeError("A job is already running.")
            lines = streamable_lines(gcode)
            if not lines:
                raise RuntimeError("The job has no streamable G-code.")
            self._stop.clear()
            self._pause.set()
            self.active_job = record.to_dict()
            self.status_text = "running"
            self.progress = 0
            self.total = len(lines)
            self.error = None
            self.started_at = time.time()
            self.finished_at = None
            self._thread = threading.Thread(
                target=self._run,
                args=(lines, controller, on_complete),
                daemon=True,
            )
            self._thread.start()

    def _run(self, lines: list[str], controller: BaseController, on_complete: Callable[[], None] | None) -> None:
        try:
            for index, line in enumerate(lines, start=1):
                if self._stop.is_set():
                    self.status_text = "stopped"
                    break
                self._pause.wait()
                response = controller.send_line(line)
                if response.lower().startswith(("error", "alarm")):
                    raise RuntimeError(response)
                with self._lock:
                    self.progress = index
            else:
                self.status_text = "complete"
        except Exception as exc:
            self.error = str(exc)
            self.status_text = "error"
            try:
                controller.send_line("M5", timeout=2)
                controller.send_line("M9", timeout=2)
            except Exception:
                pass
        finally:
            try:
                controller.send_line("M5", timeout=2)
                controller.send_line("M9", timeout=2)
            except Exception:
                pass
            self.finished_at = time.time()
            if on_complete:
                on_complete()

    def pause(self, controller: BaseController) -> None:
        if not self.is_busy():
            return
        self._pause.clear()
        self.status_text = "paused"
        controller.feed_hold()

    def resume(self, controller: BaseController) -> None:
        if not self.is_busy():
            return
        self._pause.set()
        self.status_text = "running"
        controller.cycle_start()

    def stop(self, controller: BaseController) -> None:
        if not self.is_busy():
            if self.status_text in {"running", "paused", "stopping"}:
                self.status_text = "stopped"
            return
        self._stop.set()
        self._pause.set()
        self.status_text = "stopping"
        try:
            controller.send_line("M5", timeout=2)
            controller.send_line("M9", timeout=2)
            controller.soft_reset()
        except Exception:
            pass

    def snapshot(self) -> dict:
        with self._lock:
            pct = 0 if self.total == 0 else int((self.progress / self.total) * 100)
            elapsed = None
            if self.started_at:
                end = self.finished_at or time.time()
                elapsed = round(end - self.started_at, 1)
            return {
                "busy": self.is_busy(),
                "active_job": self.active_job,
                "status": self.status_text,
                "progress": self.progress,
                "total": self.total,
                "percent": pct,
                "error": self.error,
                "elapsed_seconds": elapsed,
            }
