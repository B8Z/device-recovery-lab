const $ = (id) => document.getElementById(id);
let data,
  trace,
  frame = 0,
  timer,
  paused = false;
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
    "The controller’s completion record resolves the uncertainty. The observed action count is still one.",
  NEEDS_ATTENTION:
    "Automatic recovery has paused. The live lab requires reconnection or an explicit resume.",
  NEEDS_INSPECTION:
    "Both crash points leave IN_DOUBT. That record cannot establish whether the device acted, so the service requires inspection.",
};
function stop() {
  clearInterval(timer);
  timer = null;
  paused = false;
  $("play").textContent = "Play capture";
  $("resolve").disabled = !trace;
  $("resolve").firstChild.textContent = trace?.scenario.startsWith("crash_")
    ? "See why it stops "
    : "Replay the sequence ";
}
function pause() {
  clearInterval(timer);
  timer = null;
  paused = true;
  $("play").textContent = "Resume capture";
  $("resolve").firstChild.textContent = "Resume sequence ";
}
// Describe newly retained evidence, not invented intermediate device states.
const eventLabels = [
  ["PHYSICAL_OUTCOME_UNRESOLVED", "Inspection required"],
  ["RECONCILED", "Outcome reconciled"],
  ["COMPLETION_CONFIRMED", "Completion confirmed"],
  ["ACK_DROPPED", "Reply lost"],
  ["JOURNAL_ABSENT", "No device record"],
  ["LINK_RECONNECTED", "Link restored"],
  ["DELIVERY_BLOCKED", "Delivery blocked"],
  ["DUPLICATE_SUPPRESSED", "Duplicate suppressed"],
  ["CONTROLLER_RESTARTED", "Controller restarted"],
  ["PHYSICAL_ACTION_PERFORMED", "Device acted"],
  ["RECEIPT_ACKNOWLEDGED", "Receipt acknowledged"],
  ["COMPLETION_REPORTED", "Completion reported"],
  ["COMPLETION_QUERY", "Completion queried"],
  ["RECONCILIATION_QUERY", "Journal queried"],
  ["COMMAND_RECEIVED", "Command received"],
  ["REQUEST_PERSISTED", "Request saved"],
];
function sequenceLabel(index) {
  // Later snapshots can insert events earlier in timestamp order.
  const previous = new Set(
    index
      ? trace.frames[index - 1].snapshot.events.map((event) =>
          JSON.stringify(event),
        )
      : [],
  );
  const newEvents = new Set(
    trace.frames[index].snapshot.events
      .filter((event) => !previous.has(JSON.stringify(event)))
      .map((event) => event.kind),
  );
  return (
    eventLabels.find(([kind]) => newEvents.has(kind))?.[1] ||
    trace.frames[index].snapshot.state.replaceAll("_", " ")
  );
}
function buildSequence() {
  $("sequence").replaceChildren(
    ...trace.frames.map((captured, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.frame = index;
      const number = document.createElement("span");
      number.className = "sequence-number";
      number.textContent = String(index + 1).padStart(2, "0");
      const title = document.createElement("strong");
      title.textContent = sequenceLabel(index);
      const time = document.createElement("small");
      time.textContent = `+${captured.observed_seconds.toFixed(2)} s`;
      button.append(number, title, time);
      button.addEventListener("click", () => {
        stop();
        frame = index;
        render();
      });
      return button;
    }),
  );
}
function render() {
  const captured = trace.frames[frame],
    v = captured.snapshot;
  $("frame").value = frame;
  $("position").textContent =
    `${frame + 1}/${trace.frames.length} · +${captured.observed_seconds.toFixed(2)}s`;
  $("sequence-position").textContent =
    `Snapshot ${frame + 1} of ${trace.frames.length}`;
  for (const button of $("sequence").children) {
    const index = Number(button.dataset.frame);
    button.setAttribute("aria-pressed", String(index === frame));
    button.classList.toggle("observed", index < frame);
    if (index === frame) {
      const sequence = $("sequence"),
        left = button.offsetLeft;
      if (left < sequence.scrollLeft) sequence.scrollLeft = left;
      else if (
        left + button.offsetWidth >
        sequence.scrollLeft + sequence.clientWidth
      )
        sequence.scrollLeft = left + button.offsetWidth - sequence.clientWidth;
    }
  }
  $("state").textContent = v.state.replaceAll("_", " ");
  document.querySelector(".experiment-console").dataset.state = v.state;
  $("decision-title").textContent = {
    QUEUED: "Preserve the intent first.",
    ACCEPTED: "Received isn’t completed.",
    UNCERTAIN: "Check before repeating.",
    COMPLETED: "Confirmed. No second action.",
    NEEDS_ATTENTION: "Pause automatic recovery.",
    NEEDS_INSPECTION: "The service must stop.",
  }[v.state];
  $("intent-evidence").textContent = "Command identity stored before dispatch";
  $("intent-mark").textContent = "✓";
  $("query-evidence").textContent = v.checks
    ? `${v.checks} journal ${v.checks === 1 ? "query" : "queries"} recorded`
    : "No journal query recorded yet";
  $("query-mark").textContent = v.checks ? "↗" : "—";
  $("decision-evidence").textContent = {
    QUEUED: "Awaiting device evidence",
    ACCEPTED: "Receipt alone cannot prove completion",
    UNCERTAIN: "Completion has not been established",
    COMPLETED: "Controller completion evidence received",
    NEEDS_ATTENTION: "Investigation or explicit resume required",
    NEEDS_INSPECTION: "Independent inspection required",
  }[v.state];
  $("decision-mark").textContent =
    v.state === "COMPLETED" ? "✓" : v.state === "NEEDS_INSPECTION" ? "!" : "—";
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
  $("state").style.color =
    v.state === "COMPLETED" ? "var(--confirmed)" : "var(--accent)";
  $("status-marker").style.background =
    v.state === "COMPLETED" ? "var(--confirmed)" : "var(--accent)";
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
    : "Replay the sequence ";
  const [first, second, description] = cases[scenario];
  $("case-title").textContent = `${first} ${second}`;
  $("hero-description").textContent = description;
  $("scenario-picker").value = scenario;
  $("scenario-picker").disabled = false;
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
  buildSequence();
  render();
}
$("resolve").addEventListener("click", () => {
  if (!trace) return;
  if (timer) {
    pause();
    return;
  }
  // Start at the first retained observation, including receipt before action.
  if (!paused) frame = 0;
  paused = false;
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
    if (frame === trace.frames.length - 1) stop();
  }, 1400);
});
$("scenario-picker").addEventListener("change", (event) => {
  if (data) choose(event.target.value);
});
function showScene() {
  $("case-title").focus({ preventScroll: true });
  document
    .querySelector(".experiment-console")
    .scrollIntoView({ block: "start" });
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
    pause();
    return;
  }
  if (!paused) frame = 0;
  paused = false;
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
    if (frame === trace.frames.length - 1) stop();
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
  if (document.hidden && timer) pause();
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
