const $ = (id) => document.getElementById(id);
let data,
  trace,
  frame = 0,
  timer;
const cases = {
  lost_ack: [
    "The door opened.",
    "The reply didn’t.",
    "A missing reply doesn’t tell me whether the device acted. I built a recovery service that checks durable device evidence before deciding whether to resend.",
  ],
  duplicate: [
    "Two deliveries.",
    "One physical action.",
    "Retrying a message should not repeat a completed action. I keep the same command identity and let the controller return its existing execution record.",
  ],
  disconnected: [
    "The link is down.",
    "The intent survives.",
    "I persist the request before contacting the device. Once communication returns, the service checks the controller journal before deciding whether to send again.",
  ],
  crash_before: [
    "The record stops.",
    "Did the device act?",
    "A controller can die after recording intent but before acting. I preserve that uncertainty because the restarted journal cannot establish the physical outcome.",
  ],
  crash_after: [
    "The action happened.",
    "The record didn’t.",
    "Here the controller dies after the pulse and before recording completion. The same unfinished journal can also mean no action happened, so I require inspection.",
  ],
  healthy: [
    "A command arrives.",
    "Completion follows.",
    "I keep receipt and completion separate. The service first learns that the controller accepted the command, then waits for evidence that the physical action finished.",
  ],
};
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
  $("resolve").disabled = !trace;
  $("resolve").firstChild.textContent = trace?.scenario.startsWith("crash_")
    ? "See why it stops "
    : "Watch recovery ";
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
  $("apparatus").classList.toggle("is-confirmed", v.state === "COMPLETED");
  $("apparatus").classList.toggle("is-uncertain", v.state === "UNCERTAIN");
  $("return-path-label").textContent = {
    QUEUED: "NOT YET SENT",
    ACCEPTED: "RECEIPT ACK",
    UNCERTAIN: "REPLY UNAVAILABLE",
    COMPLETED: "COMPLETION PROOF",
    NEEDS_INSPECTION: "IN_DOUBT",
    NEEDS_ATTENTION: "NO FINAL EVIDENCE",
  }[v.state];
  $("service-brief").textContent = {
    QUEUED: "Intent recorded",
    ACCEPTED: "Receipt only",
    UNCERTAIN: "No confirmation",
    COMPLETED: "Completion confirmed",
    NEEDS_INSPECTION: "Inspection required",
    NEEDS_ATTENTION: "Recovery paused",
  }[v.state];
  const result = {
    QUEUED: "Not dispatched",
    ACCEPTED: "Receipt only",
    UNCERTAIN: "Unconfirmed",
    COMPLETED: "Confirmed",
    NEEDS_INSPECTION: "Inspection required",
    NEEDS_ATTENTION: "Recovery paused",
  }[v.state];
  $("guided-result").textContent =
    `${result}${v.device ? ` · ${v.device.pulses} action${v.device.pulses === 1 ? "" : "s"}` : ""}`;
  $("guided-result").classList.toggle("confirmed", v.state === "COMPLETED");
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
  $("resolve").firstChild.textContent = scenario.startsWith("crash_")
    ? "See why it stops "
    : "Watch recovery ";
  const [first, second, description] = cases[scenario];
  const line = document.createElement("span");
  line.textContent = second;
  $("hero-title").replaceChildren(document.createTextNode(first), line);
  $("hero-description").textContent = description;
  document.querySelector(".case-number").textContent =
    `/ ${["lost_ack", "duplicate", "disconnected", "crash_before", "crash_after", "healthy"].indexOf(scenario) + 1}`;
  frame =
    scenario === "lost_ack"
      ? trace.frames.findIndex(
          (f) =>
            f.snapshot.state === "UNCERTAIN" && f.snapshot.device?.pulses === 1,
        )
      : 0;
  if (scenario.startsWith("crash_")) frame = trace.frames.length - 1;
  if (frame < 0) frame = 0;
  $("resolve").disabled = false;
  $("frame").max = trace.frames.length - 1;
  for (const b of document.querySelectorAll("[data-scenario][aria-pressed]"))
    b.setAttribute("aria-pressed", String(b.dataset.scenario === scenario));
  render();
}
$("resolve").addEventListener("click", () => {
  if (!trace) return;
  if (timer) {
    stop();
    return;
  }
  // The guided opening starts with the ambiguity, then shows captured recovery.
  // Other cases replay from their first retained observation.
  frame =
    trace.scenario === "lost_ack"
      ? trace.frames.findIndex(
          (f) =>
            f.snapshot.state === "UNCERTAIN" && f.snapshot.device?.pulses === 1,
        )
      : 0;
  if (frame < 0) frame = 0;
  render();
  $("resolve").firstChild.textContent = "Pause replay ";
  $("play").textContent = "Pause capture";
  timer = setInterval(() => {
    if (frame >= trace.frames.length - 1) {
      stop();
      return;
    }
    frame++;
    render();
  }, 1400);
});
function showScene() {
  $("hero-title").focus({ preventScroll: true });
  $("experiment").scrollIntoView({ block: "start" });
}
$("back-to-scene").addEventListener("click", showScene);
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
  $("resolve").firstChild.textContent = "Pause replay ";
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
      showScene();
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
      `Captured ${data.captured_at_utc.slice(0, 10)} · source commit ${data.tested_commit} · Python ${data.python}. One demonstration per scenario. Guided recovery advances retained snapshots every 1,400 ms; explorer playback uses 700 ms. These are navigation speeds, not elapsed process time. Displayed timestamps retain the observed timing.`;
  } catch (error) {
    $("error").hidden = false;
    $("error").textContent = error.message;
  }
})();
