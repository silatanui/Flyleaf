const draft = document.querySelector("#draft");
const fileInput = document.querySelector("#file");
const fileName = document.querySelector("#file-name");
const wordCount = document.querySelector("#word-count");
const checkButton = document.querySelector("#check");
const modelState = document.querySelector("#model-state");
const reportBody = document.querySelector("#report-body");
const reportEmpty = document.querySelector("#report-empty");
const progress = document.querySelector("#progress");
const progressLabel = document.querySelector("#progress-label");
const progressPct = document.querySelector("#progress-pct");
const progressRing = document.querySelector("#progress-ring");

const samples = {
  human: `I missed the 6:40 daladala and ended up walking from Mwenge with a torn umbrella. The rain was not even serious, just that annoying spit that still soaks a notebook. My phone had 4 percent and of course the power bank was in the other bag, the one I left on the chair at home. By the time I got to class the quiz had started. I wrote my name too big and then stared at question two, the one about buffers, and my mind went completely blank except for the fact that my socks were wet. I still think the lecturer saw me come in. She did not say anything. She just tapped her watch once, which was worse.`,
  ai: `Artificial intelligence has transformed the way students approach academic writing. These systems can generate coherent essays, summarize complex materials, and provide structured arguments within seconds. However, the widespread availability of such tools raises important questions about academic integrity and original thought. Educators must balance the benefits of technological assistance with the need to preserve critical thinking skills. Institutions are therefore adopting detection methods and clearer policies to guide responsible use. Ultimately, the goal is not to reject innovation, but to ensure that submitted work reflects a student's own understanding and effort.`,
};

function words(value) {
  const found = value.trim().match(/\b[\w']+\b/g);
  return found ? found.length : 0;
}

function refreshCount() {
  const count = words(draft.value);
  wordCount.textContent = `${count} word${count === 1 ? "" : "s"}`;
}

function selectedPdf() {
  const file = fileInput.files[0];
  return Boolean(file && file.name.toLowerCase().endsWith(".pdf"));
}

async function waitUntilReady() {
  for (;;) {
    const response = await fetch("/api/status");
    const payload = await response.json();
    if (payload.status === "ready") {
      modelState.textContent = "Ready · English · free to use";
      checkButton.disabled = false;
      return;
    }
    if (payload.status === "error") {
      modelState.textContent = payload.error || "Flyleaf failed to load.";
      return;
    }
    modelState.textContent = "Flyleaf is getting ready...";
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

function showReport(result) {
  document.querySelector("#flagged").textContent = `${result.flagged_percent}%`;
  document.querySelector("#average").textContent = `${Math.round(result.ai_probability * 100)}%`;
  document.querySelector("#confidence").textContent = result.confidence;

  const warnings = document.querySelector("#warnings");
  warnings.replaceChildren();
  for (const warning of result.warnings) {
    const item = document.createElement("li");
    item.textContent = warning;
    warnings.appendChild(item);
  }

  const essay = document.querySelector("#essay");
  essay.replaceChildren();
  result.sentences.forEach((sentence, index) => {
    if (index > 0) essay.append(" ");
    const span = document.createElement("span");
    span.className = sentence.label;
    span.textContent = sentence.text;
    span.title = `AI likelihood ${Math.round(sentence.ai_probability * 100)}%`;
    essay.append(span);
  });
  reportEmpty.hidden = true;
  reportBody.hidden = false;
}

function paintProgress(value) {
  const shown = Math.max(0, Math.min(100, Math.round(value)));
  progressRing.style.setProperty("--p", String(shown));
  progressPct.textContent = `${shown}%`;
  progressLabel.textContent = shown >= 100 ? "Opening the review" : "Reviewing the draft";
}

async function analyze(body, isForm) {
  checkButton.disabled = true;
  progress.hidden = false;
  let shown = 4;
  let target = 8;
  let finished = false;
  paintProgress(shown);
  const timer = window.setInterval(() => {
    const ceiling = finished ? 100 : 92;
    target = Math.min(ceiling, Math.max(target, shown + 0.6));
    shown += (target - shown) * 0.12;
    paintProgress(shown);
  }, 80);

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: isForm ? undefined : { "Content-Type": "application/json" },
      body: isForm ? body : JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The check could not be started.");

    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      const jobResponse = await fetch(`/api/jobs/${payload.job_id}`);
      const job = await jobResponse.json();
      if (!jobResponse.ok) throw new Error(job.error || "The check was lost.");
      if (typeof job.percent === "number") target = Math.max(target, job.percent);
      if (job.status === "done") {
        finished = true;
        target = 100;
        await new Promise((resolve) => setTimeout(resolve, 450));
        if (job.result.review_url) {
          const opened = window.open(job.result.review_url, "_blank");
          if (!opened) window.location = job.result.review_url;
          return;
        }
        showReport(job.result);
        return;
      }
      if (job.status === "error") throw new Error(job.error || "The review could not be finished.");
    }
  } catch (error) {
    window.alert(error.message);
  } finally {
    window.clearInterval(timer);
    progress.hidden = true;
    if (modelState.textContent.startsWith("Ready")) checkButton.disabled = false;
  }
}

checkButton.addEventListener("click", () => {
  if (selectedPdf() || (fileInput.files.length > 0 && words(draft.value) < 20)) {
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    analyze(form, true);
    return;
  }
  analyze({ text: draft.value }, false);
});

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  fileName.textContent = file ? file.name : "";
  if (!file) return;
  if (file.name.toLowerCase().endsWith(".txt")) {
    draft.value = await file.text();
    refreshCount();
    return;
  }
  draft.value = "";
  wordCount.textContent = file.name.toLowerCase().endsWith(".pdf")
    ? "Opens a reviewed PDF"
    : "Score will use the uploaded file";
});

draft.addEventListener("input", () => {
  if (draft.value.trim()) {
    fileInput.value = "";
    fileName.textContent = "";
  }
  refreshCount();
});

document.querySelector("#sample-human").addEventListener("click", () => {
  fileInput.value = "";
  fileName.textContent = "";
  draft.value = samples.human;
  refreshCount();
});

document.querySelector("#sample-ai").addEventListener("click", () => {
  fileInput.value = "";
  fileName.textContent = "";
  draft.value = samples.ai;
  refreshCount();
});

draft.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !checkButton.disabled) {
    checkButton.click();
  }
});

refreshCount();
waitUntilReady();
