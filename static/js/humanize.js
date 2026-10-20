const draft = document.querySelector("#draft");
const wordCount = document.querySelector("#word-count");
const button = document.querySelector("#humanize");
const sample = document.querySelector("#sample");
const modelState = document.querySelector("#model-state");
const empty = document.querySelector("#result-empty");
const body = document.querySelector("#result-body");
const rewrite = document.querySelector("#rewrite");
const copy = document.querySelector("#copy");
const progress = document.querySelector("#progress");
const progressLabel = document.querySelector("#progress-label");
const progressPct = document.querySelector("#progress-pct");
const progressRing = document.querySelector("#progress-ring");

const sampleText = `It is important to note that the digital transformation of commerce has fundamentally reshaped consumer expectations. Furthermore, organizations must leverage innovative solutions in order to facilitate seamless experiences. Moreover, this paradigm shift underscores the critical need for a robust and comprehensive approach. In conclusion, stakeholders should utilize cutting-edge methodologies to optimize outcomes and drive meaningful engagement.`;

function words(value) {
  const found = value.trim().match(/\b[\w']+\b/g);
  return found ? found.length : 0;
}

function refreshCount() {
  const count = words(draft.value);
  wordCount.textContent = `${count} word${count === 1 ? "" : "s"}`;
}

function paintProgress(value) {
  const shown = Math.max(0, Math.min(100, Math.round(value)));
  progressRing.style.setProperty("--p", String(shown));
  progressPct.textContent = `${shown}%`;
  progressLabel.textContent = shown >= 100 ? "Rewrite ready" : "Rewriting the draft";
}

async function waitUntilReady() {
  button.disabled = words(draft.value) < 8;
  for (;;) {
    const response = await fetch("/api/humanize/status");
    const payload = await response.json();
    if (payload.status === "ready") {
      modelState.textContent = "Ready · English · free to use";
      button.disabled = words(draft.value) < 8;
      return;
    }
    if (payload.status === "error") {
      modelState.textContent = payload.error || "The humanizer failed to load.";
      await new Promise((resolve) => setTimeout(resolve, 2000));
      continue;
    }
    modelState.textContent = "Flyleaf is getting the humanizer ready...";
    button.disabled = words(draft.value) < 8;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

draft.addEventListener("input", refreshCount);
sample.addEventListener("click", () => {
  draft.value = sampleText;
  refreshCount();
});

copy.addEventListener("click", async () => {
  await navigator.clipboard.writeText(rewrite.textContent || "");
  copy.textContent = "Copied";
  window.setTimeout(() => {
    copy.textContent = "Copy";
  }, 1200);
});

button.addEventListener("click", async () => {
  button.disabled = true;
  progress.hidden = false;
  let shown = 6;
  let target = 6;
  let finished = false;
  paintProgress(shown);
  const timer = window.setInterval(() => {
    const ceiling = finished ? 100 : 92;
    target = Math.min(ceiling, Math.max(target, shown + 0.6));
    if (target > shown) shown += (target - shown) * 0.12;
    else if (finished && shown < 100) shown += Math.max(0.4, (100 - shown) * 0.2);
    paintProgress(shown);
  }, 80);

  try {
    const response = await fetch("/api/humanize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: draft.value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The rewrite could not be started.");

    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      const jobResponse = await fetch(`/api/jobs/${payload.job_id}`);
      const job = await jobResponse.json();
      if (!jobResponse.ok) throw new Error(job.error || "The rewrite was lost.");
      if (typeof job.percent === "number") target = Math.max(target, job.percent);
      if (job.status === "done") {
        finished = true;
        target = 100;
        rewrite.textContent = job.result.text;
        const percent = (value) => (value == null ? "-" : `${value}%`);
        document.querySelector("#before").textContent = percent(job.result.before_percent);
        document.querySelector("#after").textContent = percent(job.result.after_percent);
        document.querySelector("#before-flagged").textContent = `Flagged ${percent(job.result.before_flagged)}`;
        document.querySelector("#after-flagged").textContent = `Flagged ${percent(job.result.after_flagged)}`;
        empty.hidden = true;
        body.hidden = false;
        await new Promise((resolve) => setTimeout(resolve, 350));
        return;
      }
      if (job.status === "error") throw new Error(job.error || "The rewrite could not be finished.");
    }
  } catch (error) {
    window.alert(error.message);
  } finally {
    window.clearInterval(timer);
    progress.hidden = true;
    if (modelState.textContent.startsWith("Ready")) button.disabled = false;
  }
});

refreshCount();
waitUntilReady();
