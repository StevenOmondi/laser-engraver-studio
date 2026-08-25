const state = {
  status: null,
  toast: null,
  armModal: null,
};

function page() {
  return document.body.dataset.page;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const init = {
    headers: {},
    ...options,
  };
  if (init.body && !(init.body instanceof FormData)) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  const response = await fetch(path, init);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : {};
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || response.statusText || "Request failed");
  }
  return payload;
}

function showToast(message) {
  const el = document.getElementById("app-toast");
  const messageEl = document.getElementById("toast-message");
  if (!el || !messageEl) return;
  messageEl.textContent = message;
  state.toast ||= new bootstrap.Toast(el, { delay: 3200 });
  state.toast.show();
}

function setPill(id, text, mode) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("ok", "warn", "danger");
  if (mode) el.classList.add(mode);
  const span = el.querySelector("span");
  if (span) span.textContent = text;
}

function formatPos(pos) {
  if (!pos) return "X0.000 Y0.000 Z0.000";
  return `X${Number(pos.x).toFixed(3)} Y${Number(pos.y).toFixed(3)} Z${Number(pos.z).toFixed(3)}`;
}

async function refreshStatus() {
  try {
    const payload = await api("/api/status");
    state.status = payload;
    const ctrl = payload.controller;
    const safe = payload.safety;
    const run = payload.runner;
    setPill(
      "connection-pill",
      ctrl.connected ? `${ctrl.mode}: ${ctrl.state}` : "Disconnected",
      ctrl.connected ? "ok" : "danger",
    );
    setPill(
      "safety-pill",
      safe.armed ? `Armed ${Math.ceil(safe.remaining_seconds / 60)}m` : "Disarmed",
      safe.armed ? "danger" : "warn",
    );
    setPill(
      "job-pill",
      run.busy ? `${run.status} ${run.percent}%` : run.status || "Idle",
      run.busy ? "ok" : "",
    );
    const controllerState = document.getElementById("controller-state");
    if (controllerState) controllerState.textContent = ctrl.connected ? `${ctrl.mode} on ${ctrl.port}` : "Disconnected";
    const machinePosition = document.getElementById("machine-position");
    if (machinePosition) machinePosition.textContent = formatPos(ctrl.mpos);
    const safetyState = document.getElementById("safety-state");
    if (safetyState) safetyState.textContent = safe.armed ? `Armed for ${safe.remaining_seconds}s` : "Disarmed";
    const jobName = document.getElementById("active-job-name");
    if (jobName) jobName.textContent = run.active_job ? run.active_job.name : "No job loaded";
    const progressBar = document.getElementById("job-progress-bar");
    if (progressBar) {
      progressBar.style.width = `${run.percent}%`;
      progressBar.textContent = `${run.percent}%`;
    }
    updateLimitDisplay(ctrl.limit_switches || {});
    const log = document.getElementById("console-log");
    if (log) {
      log.textContent = payload.log.join("\n");
      log.scrollTop = log.scrollHeight;
    }
    const logCount = document.getElementById("log-count");
    if (logCount) logCount.textContent = `${payload.log.length} lines`;
  } catch (error) {
    setPill("connection-pill", "Offline", "danger");
  }
}

function updateLimitDisplay(switches) {
  const active = [];
  ["x", "y", "z"].forEach((axis) => {
    const chip = document.getElementById(`limit-${axis}`);
    if (!chip) return;
    const isActive = Boolean(switches[axis]);
    chip.classList.toggle("active", isActive);
    chip.textContent = `${axis.toUpperCase()} ${isActive ? "ON" : "off"}`;
    if (isActive) active.push(axis.toUpperCase());
  });
  const label = document.getElementById("limits-state");
  if (label) label.textContent = active.length ? `${active.join(", ")} active` : "No active switches";
}

async function loadPorts() {
  const select = document.getElementById("serial-port");
  if (!select) return;
  select.innerHTML = `<option value="">Simulator only</option>`;
  try {
    const payload = await api("/api/ports");
    payload.ports.forEach((port) => {
      const option = document.createElement("option");
      option.value = port.device;
      option.textContent = `${port.device} - ${port.description}`;
      select.appendChild(option);
    });
  } catch (error) {
    showToast(error.message);
  }
}

function bindGlobalActions() {
  state.armModal = new bootstrap.Modal(document.getElementById("armModal"));

  document.querySelectorAll("[data-api-post]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(button.dataset.apiPost, { method: "POST" });
        showToast("Done");
        await refreshStatus();
      } catch (error) {
        showToast(error.message);
      }
    });
  });

  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await sendCommand(button.dataset.command);
      } catch (error) {
        showToast(error.message);
      }
    });
  });

  document.querySelectorAll("[data-job-control]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/job-control/${button.dataset.jobControl}`, { method: "POST" });
        await refreshStatus();
      } catch (error) {
        showToast(error.message);
      }
    });
  });

  const armForm = document.getElementById("arm-form");
  if (armForm) {
    armForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(armForm);
      const checklist = {};
      ["eye_protection", "ventilation", "fire_watch", "material", "enclosure"].forEach((key) => {
        checklist[key] = data.get(key) === "on";
      });
      try {
        await api("/api/arm", {
          method: "POST",
          body: { checklist, minutes: Number(data.get("minutes") || 8) },
        });
        state.armModal.hide();
        armForm.reset();
        showToast("Laser armed");
        await refreshStatus();
      } catch (error) {
        showToast(error.message);
      }
    });
  }
}

async function sendCommand(command) {
  const payload = await api("/api/command", { method: "POST", body: { command } });
  showToast(payload.response || "Command sent");
  await refreshStatus();
}

function bindDashboard() {
  const connectForm = document.getElementById("connect-form");
  if (connectForm) {
    connectForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(connectForm);
      try {
        await api("/api/connect", {
          method: "POST",
          body: {
            mode: data.get("mode"),
            port: document.getElementById("serial-port").value,
            baud: document.getElementById("baud").value,
          },
        });
        showToast("Connected");
        await refreshStatus();
      } catch (error) {
        showToast(error.message);
      }
    });
  }

  document.getElementById("refresh-ports")?.addEventListener("click", loadPorts);
  document.getElementById("focus-pulse")?.addEventListener("click", async () => {
    try {
      await api("/api/laser/pulse", { method: "POST", body: { power: 8, duration: 0.12 } });
      showToast("Focus pulse sent");
      await refreshStatus();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("enable-limits")?.addEventListener("click", async () => {
    try {
      const payload = await api("/api/limits/apply", {
        method: "POST",
        body: { homing: true, hard_limits: true, soft_limits: false },
      });
      const message = payload.warnings?.length ? payload.warnings.join(" ") : "Homing and hard limits enabled";
      showToast(message);
      const note = document.getElementById("limits-note");
      if (note) note.textContent = message;
      await refreshStatus();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.querySelectorAll(".jog").forEach((button) => {
    button.addEventListener("click", async () => {
      const step = Number(document.getElementById("jog-step").value || 10);
      const feed = Number(document.getElementById("jog-feed").value || 1800);
      const rawX = Number(button.dataset.x || 0);
      const rawY = Number(button.dataset.y || 0);
      try {
        await api("/api/jog", {
          method: "POST",
          body: { x: Math.sign(rawX) * step, y: Math.sign(rawY) * step, feed },
        });
        await refreshStatus();
      } catch (error) {
        showToast(error.message);
      }
    });
  });

  loadPorts();
}

async function loadExamples() {
  const target = document.getElementById("examples-list");
  if (!target) return;
  try {
    const payload = await api("/api/examples");
    target.innerHTML = payload.examples
      .map(
        (example) => `
          <article class="example-card">
            <span class="badge">${escapeHtml(example.material)}</span>
            <h3>${escapeHtml(example.name)}</h3>
            <p>${escapeHtml(example.description)}</p>
            <button class="btn btn-primary mt-auto" data-create-example="${escapeHtml(example.key)}">
              <i class="bi bi-plus-circle"></i> Create Job
            </button>
          </article>
        `,
      )
      .join("");
    target.querySelectorAll("[data-create-example]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await api(`/api/examples/${button.dataset.createExample}/create`, { method: "POST" });
          showToast("Demo job created");
        } catch (error) {
          showToast(error.message);
        }
      });
    });
  } catch (error) {
    showToast(error.message);
  }
}

function bindDesigner() {
  loadExamples();

  document.getElementById("text-generator")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/generate/text", { method: "POST", body: new FormData(event.currentTarget) });
      showToast("Text job created");
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("image-generator")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/generate/image", { method: "POST", body: new FormData(event.currentTarget) });
      showToast("Image job created");
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("manual-job-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/jobs", { method: "POST", body: new FormData(event.currentTarget) });
      showToast("Manual job saved");
    } catch (error) {
      showToast(error.message);
    }
  });
}

async function loadJobs() {
  const target = document.getElementById("jobs-list");
  if (!target) return;
  try {
    const payload = await api("/api/jobs");
    document.getElementById("jobs-count").textContent = `${payload.jobs.length} jobs`;
    if (!payload.jobs.length) {
      target.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No jobs yet</td></tr>`;
      return;
    }
    target.innerHTML = payload.jobs
      .map((job) => {
        const stats = job.stats || {};
        const bounds = `${Number(stats.width_mm || 0).toFixed(1)} x ${Number(stats.height_mm || 0).toFixed(1)} mm`;
        return `
          <tr>
            <td><button class="btn btn-link p-0 text-start" data-preview="${escapeHtml(job.id)}">${escapeHtml(job.name)}</button></td>
            <td>${escapeHtml(job.source)}</td>
            <td>${bounds}</td>
            <td>S${escapeHtml(stats.max_power || 0)}</td>
            <td>${escapeHtml(job.created_label)}</td>
            <td>
              <div class="job-action-row">
                <button class="btn btn-sm btn-outline-secondary" data-frame="${escapeHtml(job.id)}"><i class="bi bi-bounding-box"></i></button>
                <button class="btn btn-sm btn-danger" data-run="${escapeHtml(job.id)}"><i class="bi bi-play-fill"></i></button>
                <a class="btn btn-sm btn-outline-secondary" href="/api/jobs/${encodeURIComponent(job.id)}/download"><i class="bi bi-download"></i></a>
                <button class="btn btn-sm btn-outline-danger" data-delete="${escapeHtml(job.id)}"><i class="bi bi-trash"></i></button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");
    target.querySelectorAll("[data-preview]").forEach((button) => button.addEventListener("click", () => previewJob(button.dataset.preview)));
    target.querySelectorAll("[data-frame]").forEach((button) => button.addEventListener("click", () => frameJob(button.dataset.frame)));
    target.querySelectorAll("[data-run]").forEach((button) => button.addEventListener("click", () => runJob(button.dataset.run)));
    target.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => deleteJob(button.dataset.delete)));
  } catch (error) {
    showToast(error.message);
  }
}

async function previewJob(id) {
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(id)}`);
    document.getElementById("preview-title").textContent = payload.job.name;
    document.getElementById("gcode-preview").textContent = payload.gcode;
    const image = document.getElementById("toolpath-preview");
    if (image) {
      image.src = `/api/jobs/${encodeURIComponent(id)}/preview.svg?t=${Date.now()}`;
      image.alt = `Toolpath preview for ${payload.job.name}`;
    }
  } catch (error) {
    showToast(error.message);
  }
}

async function frameJob(id) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/frame`, { method: "POST" });
    showToast("Dry frame started");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
}

async function runJob(id) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/run`, { method: "POST" });
    showToast("Job started");
    await refreshStatus();
  } catch (error) {
    await refreshStatus();
    showToast(error.message);
  }
}

async function deleteJob(id) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
    await loadJobs();
    showToast("Job deleted");
  } catch (error) {
    showToast(error.message);
  }
}

function bindJobs() {
  document.getElementById("refresh-jobs")?.addEventListener("click", loadJobs);
  loadJobs();
}

function bindConsole() {
  const form = document.getElementById("console-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("console-command");
    try {
      await sendCommand(input.value);
    } catch (error) {
      showToast(error.message);
    }
  });
}

function bindSettings() {
  document.getElementById("settings-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload = {};
    for (const [name, raw] of data.entries()) {
      const [section, key] = name.split(".");
      payload[section] ||= {};
      const numeric = Number(raw);
      payload[section][key] = raw !== "" && Number.isFinite(numeric) ? numeric : raw;
    }
    try {
      await api("/api/settings", { method: "POST", body: payload });
      showToast("Settings saved");
    } catch (error) {
      showToast(error.message);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindGlobalActions();
  if (page() === "dashboard") bindDashboard();
  if (page() === "designer") bindDesigner();
  if (page() === "jobs") bindJobs();
  if (page() === "console") bindConsole();
  if (page() === "settings") bindSettings();
  refreshStatus();
  setInterval(refreshStatus, 1200);
});
