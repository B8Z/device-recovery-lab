const $ = (id) => document.getElementById(id);
let data,
  trace,
  frame = 0,
  timer;
const explanations = {
  QUEUED:
    "The service has a durable intent. It does not yet have evidence of device completion.",
  ACCEPTED:
    "The device received the command. A receipt does not establish that the action completed.",
  UNCERTAIN:
    "The outcome is uncertain. The service checks the journal before deciding whether to send again.",
  COMPLETED:
    "The service has completion evidence from the controller journal. The simulated pulse count is one.",
  NEEDS_ATTENTION:
    "Automatic recovery has paused. The live lab requires reconnection or an explicit resume.",
  NEEDS_INSPECTION:
    "The controller restarted with intent but no completion record. This same evidence can mean zero or one physical actions. The service stops; retrying cannot resolve the missing fact.",
};
function stop() {
  clearInterval(timer);
  timer = null;
  $("play").textContent = "Play capture";
}
function render() {
  const captured = trace.frames[frame],
    v = captured.snapshot;
  $("frame").value = frame;
  $("position").textContent =
    `${frame + 1}/${trace.frames.length} · +${captured.observed_seconds.toFixed(2)}s`;
  $("state").textContent = v.state.replaceAll("_", " ");
  $("physical").textContent = !v.device
    ? "Unknown"
    : v.device.pulses
      ? "Open"
      : "Closed";
  $("online").textContent =
    v.device?.online === false
      ? "Link disconnected"
      : v.device?.online === true
        ? "Link online"
        : "Awaiting first delivery";
  $("sends").textContent = v.sends;
  $("checks").textContent = v.checks;
  $("pulses").textContent = v.device?.pulses ?? "—";
  $("apparatus").classList.toggle("is-open", Boolean(v.device?.pulses));
  $("apparatus").classList.toggle("is-unknown", !v.device);
  $("apparatus").classList.toggle("is-offline", v.device?.online === false);
  $("run-label").textContent = v.id.slice(0, 8).toUpperCase();
  $("journal-state").textContent = {
    QUEUED: "NOT YET OBSERVED",
    ACCEPTED: "RECEIVED",
    UNCERTAIN: "RESPONSE UNAVAILABLE",
    COMPLETED: "COMPLETED",
    NEEDS_INSPECTION: "IN_DOUBT",
    NEEDS_ATTENTION: "NO FINAL EVIDENCE",
  }[v.state];
  $("state").style.color = v.state === "COMPLETED" ? "#d2f0b7" : "#f3bd8b";
  $("status-marker").style.background =
    v.state === "COMPLETED" ? "#d2f0b7" : "#f3bd8b";
  $("event-count").textContent =
    `${v.events.length} OBSERVATIONS / ELAPSED · SOURCE · EVIDENCE`;
  $("explanation").textContent = explanations[v.state];
  $("previous").disabled = frame === 0;
  $("next").disabled = frame === trace.frames.length - 1;
  $("events").replaceChildren(
    ...v.events.map((event) => {
      const li = document.createElement("li");
      li.dataset.kind = event.kind;
      li.classList.toggle(
        "fault",
        /DROPPED|UNCERTAIN|BLOCKED|UNRESOLVED|RESTARTED/.test(event.kind),
      );
      const time = document.createElement("span");
      time.textContent = `+${(event.at - v.created).toFixed(2)}s`;
      const source = document.createElement("span");
      source.textContent = event.source;
      const content = document.createElement("div"),
        kind = document.createElement("strong"),
        detail = document.createElement("p");
      kind.textContent = event.kind.replaceAll("_", " ");
      detail.textContent = event.detail;
      content.append(kind, detail);
      li.append(time, source, content);
      return li;
    }),
  );
}
function choose(scenario) {
  stop();
  trace = data.traces.find((t) => t.scenario === scenario);
  frame =
    scenario === "lost_ack"
      ? trace.frames.findIndex(
          (f) =>
            f.snapshot.state === "UNCERTAIN" && f.snapshot.device?.pulses === 1,
        )
      : 0;
  if (scenario.startsWith("crash_")) frame = trace.frames.length - 1;
  if (frame < 0) frame = 0;
  $("frame").max = trace.frames.length - 1;
  for (const b of document.querySelectorAll("[data-scenario][aria-pressed]"))
    b.setAttribute("aria-pressed", String(b.dataset.scenario === scenario));
  render();
}
$("frame").addEventListener("input", () => {
  if (!trace) return;
  stop();
  frame = Number($("frame").value);
  render();
});
for (const [id, direction] of [
  ["previous", -1],
  ["next", 1],
])
  $(id).addEventListener("click", () => {
    if (!trace) return;
    stop();
    frame = Math.max(0, Math.min(trace.frames.length - 1, frame + direction));
    render();
  });
$("play").addEventListener("click", () => {
  if (!trace) return;
  if (timer) {
    stop();
    return;
  }
  frame = 0;
  render();
  $("play").textContent = "Pause capture";
  // Explicit playback uses one snapshot per 700 ms; this is navigation speed,
  // not a recreation of elapsed time. Timestamps retain actual observations.
  timer = setInterval(() => {
    if (frame >= trace.frames.length - 1) {
      stop();
      return;
    }
    frame++;
    render();
  }, 700);
});
for (const b of document.querySelectorAll("[data-scenario]"))
  b.addEventListener("click", () => {
    if (data) {
      choose(b.dataset.scenario);
      if (b.closest(".boundary"))
        $("experiment").scrollIntoView({ block: "start" });
    }
  });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stop();
});
(async () => {
  try {
    const response = await fetch("traces.json");
    if (!response.ok) throw new Error("Captured evidence could not be loaded.");
    data = await response.json();
    for (const scenario of ["crash_before", "crash_after"]) {
      const capture = data.traces.find((t) => t.scenario === scenario);
      const v = capture.frames.at(-1).snapshot;
      document.querySelector(`[data-pulses="${scenario}"]`).textContent =
        v.device.pulses;
      document.querySelector(`[data-journal="${scenario}"]`).textContent =
        v.device.state;
    }
    const requested = location.hash.slice(1);
    choose(
      data.traces.some((t) => t.scenario === requested)
        ? requested
        : "lost_ack",
    );
    $("provenance").textContent =
      `Captured ${data.captured_at_utc.slice(0, 10)} · source commit ${data.tested_commit} · Python ${data.python}. One demonstration per scenario. Playback advances a snapshot every 700 ms; displayed timestamps retain the observed timing.`;
  } catch (error) {
    $("error").hidden = false;
    $("error").textContent = error.message;
  }
})();
