/* Render paired observations. No simulated timings or client-side benchmark. */
(() => {
  const el = (id) => document.getElementById(id);
  let report, lastChartWidth;
  const ns = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, text) {
    const node = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs))
      node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function options(id, values) {
    el(id).replaceChildren(
      ...values.map((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent =
          id === "workload-repetition" ? Number(value) + 1 : value;
        return option;
      }),
    );
  }
  function render() {
    const workload = el("workload-kind").value,
      seed = Number(el("workload-seed").value),
      repetition = Number(el("workload-repetition").value);
    const pair = [1, 4].map((workers) =>
      report.trials.find(
        (t) =>
          !t.warmup &&
          t.workload === workload &&
          t.seed === seed &&
          t.repetition === repetition &&
          t.workers === workers,
      ),
    );
    if (pair.some((t) => !t))
      throw new Error("Paired observations unavailable");
    const chart = el("workload-chart");
    chart.replaceChildren();
    const width = Math.max(270, chart.clientWidth);
    lastChartWidth = chart.clientWidth;
    chart.setAttribute("viewBox", `0 0 ${width} 300`);
    const count = report.configuration.operations_per_batch;
    const times = pair.flatMap((t) =>
      t.operations
        .map((o) => o.completion_seconds)
        .filter((v) => typeof v === "number"),
    );
    const max = Math.ceil(Math.max(...times, 0.1) * 5) / 5;
    const x = (time) => 40 + (time / max) * (width - 65),
      y = (value) => 254 - (value / count) * 218;
    for (let tick = 0; tick <= 4; tick++) {
      const value = (count * tick) / 4;
      chart.append(
        svg("line", {
          x1: 40,
          x2: width - 25,
          y1: y(value),
          y2: y(value),
          stroke: "#dce0d3",
        }),
        svg("text", { x: 28, y: y(value) + 4, "text-anchor": "end" }, value),
      );
      const seconds = (max * tick) / 4;
      chart.append(
        svg(
          "text",
          { x: x(seconds), y: 282, "text-anchor": "middle" },
          seconds.toFixed(2) + "s",
        ),
      );
    }
    for (const [index, trial] of pair.entries()) {
      const completed = trial.operations
        .filter((o) => o.classification === "completed")
        .sort((a, b) => a.completion_seconds - b.completion_seconds);
      let path = `M${x(0)},${y(0)}`;
      completed.forEach((o, i) => {
        path += `H${x(o.completion_seconds)}V${y(i + 1)}`;
      });
      path += `H${x(max)}`;
      chart.append(
        svg("path", {
          d: path,
          fill: "none",
          stroke: index ? "#35634e" : "#a6421d",
          "stroke-width": 2.5,
          "stroke-linejoin": "round",
          "stroke-dasharray": index ? "none" : "7 4",
        }),
      );
    }
    const ms = (value) =>
      typeof value === "number" ? value.toFixed(3) + " s" : "Not completed";
    const cells = [
      [
        "BATCH COMPLETION",
        `${ms(pair[0].batch_seconds)} / ${ms(pair[1].batch_seconds)}`,
        "1 worker / 4 workers",
      ],
      [
        "UNAFFECTED OPERATIONS · MEDIAN",
        `${ms(pair[0].unaffected_median_seconds)} / ${ms(pair[1].unaffected_median_seconds)}`,
        "1 worker / 4 workers",
      ],
      [
        "CORRECT COMPLETIONS",
        pair
          .map(
            (t) =>
              t.operations.filter((o) => o.classification === "completed")
                .length +
              " / " +
              count,
          )
          .join(" · "),
        "Each completion checked against device evidence",
      ],
    ];
    el("measurement-strip").replaceChildren(
      ...cells.map(([label, value, note]) => {
        const div = document.createElement("div"),
          span = document.createElement("span"),
          strong = document.createElement("strong"),
          small = document.createElement("small");
        span.textContent = label;
        strong.textContent = value;
        small.textContent = note;
        div.append(span, strong, small);
        return div;
      }),
    );
    el("plot-caption").textContent =
      `Seed ${seed}, repetition ${repetition + 1}. ${count} queued operations per implementation; ${workload === "mixed" ? "four operations per external fault profile, including four unaffected operations" : "all operations free of injected network faults"}. Both traces use identical operation IDs and fault assignments. Timing starts when the staged queue becomes eligible.`;
    chart.setAttribute(
      "aria-label",
      `Actual ${workload} workload, seed ${seed}, repetition ${repetition + 1}. Batch completion: one worker ${ms(pair[0].batch_seconds)}; four workers ${ms(pair[1].batch_seconds)}. See numeric results below.`,
    );
  }
  for (const id of ["workload-kind", "workload-seed", "workload-repetition"])
    el(id).addEventListener("change", () => {
      if (report) render();
    });
  el("inspect-outlier").addEventListener("click", () => {
    if (!report) return;
    el("workload-kind").value = "mixed";
    el("workload-seed").value = "7";
    el("workload-repetition").value = "2";
    render();
    el("workload-chart").scrollIntoView({ block: "center" });
  });
  new ResizeObserver(() => {
    if (report && el("workload-chart").clientWidth !== lastChartWidth) render();
  }).observe(el("workload-chart"));
  (async () => {
    try {
      const response = await fetch("workload.json");
      if (!response.ok)
        throw new Error("Workload evidence could not be loaded.");
      report = await response.json();
      options("workload-seed", report.configuration.seeds);
      options(
        "workload-repetition",
        Array.from(
          { length: report.configuration.timing_repetitions },
          (_, i) => i,
        ),
      );
      render();
      el("workload-source").textContent =
        `Measured ${report.recorded_at_utc.slice(0, 10)} · ${report.configuration.seeds.length} independent mixed-workload seeds × ${report.configuration.timing_repetitions} timing repetitions per worker count. Warmups excluded from this view. Source ${report.tested_commit.slice(0, 12)}. One machine and a finite controlled workload; these observations do not establish production latency or fleet capacity.`;
    } catch (error) {
      el("workload-source").textContent =
        error.message +
        " The reproducible experiment and raw results are linked below.";
      el("workload-source").setAttribute("role", "alert");
    }
  })();
})();
