const $ = (id) => document.getElementById(id);
const expectations = {
  healthy:
    "Expect: receipt first, then one release pulse and confirmed completion.",
  duplicate:
    "Expect: the device suppresses the repeated command. Two deliveries produce one pulse.",
  lost_ack:
    "Expect: the locker opens, the service becomes uncertain, then a journal query confirms completion.",
  disconnected:
    "Expect: uncertainty and zero pulses while offline. Reconnect the device to recover.",
};
const labels = {
  healthy: "Healthy delivery",
  duplicate: "Duplicate command",
  lost_ack: "Lost acknowledgment",
  disconnected: "Disconnected device",
};
let scenario = "healthy",
  current = null,
  snapshot = null,
  busy = false;
let savedRun = null;
try {
  savedRun = localStorage.getItem("recovery-run");
} catch {
  /* Storage may be disabled. */
}
const descriptions = {
  QUEUED: "Request is durable. No device completion evidence exists yet.",
  ACCEPTED:
    "The device received the command. Receipt is not physical completion.",
  UNCERTAIN:
    "The response is missing. Query the journal before deciding whether to resend.",
  COMPLETED:
    "A completed controller journal entry confirms the simulated release.",
  NEEDS_ATTENTION:
    "Automatic recovery paused. Restore the link or investigate, then resume journal queries.",
};
async function api(path, body) {
  const response = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}
function error(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}
function chooseRun(id) {
  current = id;
  snapshot = null;
  $("export").disabled = true;
  $("service-state").textContent = "Loading evidence";
  $("service-state").className = "";
  $("interpretation").textContent = "Waiting for this experiment's evidence.";
  $("command-id").textContent = id ? `command / ${id}` : "Submitting a new request";
  for (const name of ["sends", "checks", "pulses"]) $(name).textContent = "—";
  $("physical-state").textContent = "Unknown";
  $("link-state").textContent = "Loading device evidence";
  $("locker").classList.remove("open");
  $("reconnect").hidden = true;
  $("resume").hidden = true;
  $("timeline").replaceChildren();
  try {
    if (id) localStorage.setItem("recovery-run", id);
  } catch {
    /* Optional history only. */
  }
}
for (const button of document.querySelectorAll(".scenario")) {
  button.addEventListener("click", () => {
    scenario = button.dataset.scenario;
    for (const candidate of document.querySelectorAll(".scenario")) {
      const selected = candidate === button;
      candidate.classList.toggle("selected", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    }
    $("expectation").textContent = expectations[scenario];
  });
}
async function history() {
  const runs = await api("/api/runs");
  $("history").replaceChildren(
    ...runs.map((r) => {
      const option = document.createElement("option");
      option.value = r.id;
      option.textContent = `${labels[r.scenario]} · ${r.id.slice(0, 8)}`;
      return option;
    }),
  );
  if (current) $("history").value = current;
  return runs;
}
$("history").addEventListener("change", async () => {
  chooseRun($("history").value);
  await refresh();
});
$("run").addEventListener("click", async () => {
  if (busy) return;
  const previous = current;
  chooseRun(null);
  busy = true;
  $("run").disabled = true;
  error("");
  try {
    const id = crypto.randomUUID();
    await api("/api/runs", { id, scenario });
    chooseRun(id);
    await history();
    await refresh();
  } catch (e) {
    error(e.message);
    if (previous) { chooseRun(previous); await refresh(); }
  } finally {
    busy = false;
    $("run").disabled = false;
  }
});
for (const action of ["reconnect", "resume"]) {
  $(action).addEventListener("click", async () => {
    $(action).disabled = true;
    error("");
    try {
      await api(`/api/runs/${current}/${action}`, {});
      await refresh();
    } catch (e) {
      error(e.message);
    } finally {
      $(action).disabled = false;
    }
  });
}
function render(value) {
  snapshot = value;
  $("service-state").textContent = value.state.replaceAll("_", " ");
  $("service-state").className =
    value.state === "COMPLETED"
      ? "completed"
      : ["UNCERTAIN", "NEEDS_ATTENTION"].includes(value.state)
        ? "uncertain"
        : "";
  $("interpretation").textContent = descriptions[value.state];
  $("sends").textContent = value.sends;
  $("checks").textContent = value.checks;
  $("command-id").textContent = `command / ${value.id}`;
  const device = value.device;
  $("physical-state").textContent = !device
    ? "Unknown"
    : device.pulses
      ? "Open"
      : "Closed";
  $("locker").classList.toggle("open", Boolean(device?.pulses));
  $("link-state").textContent = !device
    ? "Simulator unavailable"
    : device.online === null
      ? "Awaiting first delivery"
      : device.online
        ? "Link online"
        : "Link disconnected";
  $("pulses").textContent = device?.pulses ?? "—";
  $("reconnect").hidden = !(device && device.online === false);
  $("resume").hidden = value.state !== "NEEDS_ATTENTION";
  $("export").hidden = false;
  $("export").disabled = false;
  const elements = value.events.map((e) => {
    const item = document.createElement("li");
    item.className = "timeline-event";
    item.dataset.kind = e.kind;
    item.classList.toggle(
      "fault",
      /DROPPED|UNCERTAIN|BLOCKED|EXHAUSTED/.test(e.kind),
    );
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = `+${(e.at - value.created).toFixed(2)}s`;
    const source = document.createElement("span");
    source.className = "source";
    source.textContent = e.source;
    const content = document.createElement("div");
    const kind = document.createElement("strong");
    kind.textContent = e.kind.replaceAll("_", " ");
    const detail = document.createElement("p");
    detail.textContent = e.detail;
    content.append(kind, detail);
    item.append(time, source, content);
    return item;
  });
  $("timeline").replaceChildren(...elements);
}
async function refresh() {
  const id = current;
  if (!id) return;
  try {
    const value = await api(`/api/runs/${id}`);
    if (id === current) render(value);
  } catch (e) {
    error(`Cannot refresh evidence: ${e.message}`);
  }
}
$("export").addEventListener("click", () => {
  if (!snapshot || snapshot.id !== current) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `recovery-${snapshot.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
(async () => {
  try {
    const runs = await history();
    const found = runs.find((r) => r.id === savedRun) || runs[0];
    if (found) {
      chooseRun(found.id);
      $("history").value = current;
      await refresh();
    }
  } catch (e) {
    error(`Service unavailable: ${e.message}`);
  }
  // Wait for each response before scheduling another poll.
  async function poll() {
    await refresh();
    setTimeout(poll, 200);
  }
  setTimeout(poll, 200);
})();
