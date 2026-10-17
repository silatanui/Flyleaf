const draft = document.querySelector("#draft");
const fileInput = document.querySelector("#file");
const fileName = document.querySelector("#file-name");
const wordCount = document.querySelector("#word-count");
const checkButton = document.querySelector("#check");
const humanizeButton = document.querySelector("#humanize");
const modelState = document.querySelector("#model-state");
const reportBody = document.querySelector("#report-body");
const rewriteBody = document.querySelector("#rewrite-body");
const reportEmpty = document.querySelector("#report-empty");
const progress = document.querySelector("#progress");
const progressLabel = document.querySelector("#progress-label");
const progressPct = document.querySelector("#progress-pct");
const progressRing = document.querySelector("#progress-ring");

const samples = {
  human: `I missed the 6:40 daladala and ended up walking from Mwenge with a torn umbrella. The rain was not even serious, just that annoying spit that still soaks a notebook. My phone had 4 percent and of course the power bank was in the other bag, the one I left on the chair at home. By the time I got to class the quiz had started. I wrote my name too big and then stared at question two, the one about buffers, and my mind went completely blank except for the fact that my socks were wet. I still think the lecturer saw me come in. She did not say anything. She just tapped her watch once, which was worse.`,
  ai: `Artificial intelligence has transformed the way students approach academic writing. These systems can generate coherent essays, summarize complex materials, and provide structured arguments within seconds. However, the widespread availability of such tools raises important questions about academic integrity and original thought. Educators must balance the benefits of technological assistance with the need to preserve critical thinking skills. Institutions are therefore adopting detection methods and clearer policies to guide responsible use. Ultimately, the goal is not to reject innovation, but to ensure that submitted work reflects a student's own understanding and effort.`,
};

let detectorReady = false;
let humanizerReady = false;

function appRoot() {
  const script = document.querySelector("script[src*='app.js']");
  const src = script ? script.getAttribute("src") || "" : "";
  const marker = "/static/js/app.js";
  const index = src.indexOf(marker);
  return index > 0 ? src.slice(0, index) : "";
}

const root = appRoot();

function appPath(path) {
  if (!path) return root || "/";
  if (/^https?:\/\//i.test(path)) return path;
  if (root && (path === root || path.startsWith(`${root}/`))) return path;
  if (path.startsWith("/")) return `${root}${path}`;
  return `${root}/${path}`;
}

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

function readingOf(flagged, uncertain) {
  const ai = Math.max(0, Math.round(Number(flagged) || 0));
  const mid = Math.max(0, Math.round(Number(uncertain) || 0));
  const suspicious = Math.min(100, ai + mid);
  return { ai, uncertain: mid, suspicious, human: Math.max(0, 100 - suspicious) };
}

function speedColor(value) {
  const t = Math.max(0, Math.min(100, Number(value) || 0)) / 100;
  const mix = (from, to, amount) => from.map((channel, index) => Math.round(channel + (to[index] - channel) * amount));
  const green = [31, 157, 90];
  const amber = [214, 148, 18];
  const red = [201, 52, 46];
  const rgb = t < 0.5 ? mix(green, amber, t / 0.5) : mix(amber, red, (t - 0.5) / 0.5);
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

function gaugePoint(cx, cy, radius, angle) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

function gaugeArc(cx, cy, radius, start, end) {
  const delta = Math.abs(end - start);
  if (delta < 0.02) return "";
  const [x0, y0] = gaugePoint(cx, cy, radius, start);
  const [x1, y1] = gaugePoint(cx, cy, radius, end);
  const large = delta > Math.PI ? 1 : 0;
  return `M ${x0} ${y0} A ${radius} ${radius} 0 ${large} 1 ${x1} ${y1}`;
}

function explainReading(reading) {
  const { ai, uncertain, suspicious } = reading;
  let detail = "The draft was read as human-like.";
  if (suspicious > 0 && uncertain === 0) detail = `${ai}% was classified as AI-like.`;
  if (suspicious > 0 && ai === 0) detail = `None of it was classified as clearly AI-like. ${uncertain}% was inconclusive.`;
  if (ai > 0 && uncertain > 0) detail = `${ai}% was classified as AI-like, while ${uncertain}% was inconclusive.`;
  return `${suspicious}% AI-like or suspicious content. ${detail} The result is an estimate and does not establish whether the text was written by AI.`;
}

let gaugeSerial = 0;

function drawGauge(host, reading, caption) {
  const cx = 240;
  const cy = 168;
  const radius = 112;
  const width = 28;
  const value = Math.max(0, Math.min(100, reading.suspicious));
  const color = speedColor(value);
  const start = Math.PI;
  const end = Math.PI + Math.PI * (value / 100);
  const track = gaugeArc(cx, cy, radius, start, start + Math.PI);
  const fill = gaugeArc(cx, cy, radius, start, end);
  const gradientId = `speed-${++gaugeSerial}`;
  const [leftX] = gaugePoint(cx, cy, radius, Math.PI);
  const [rightX] = gaugePoint(cx, cy, radius, 0);
  const ticks = [0, 25, 50, 75, 100].map((mark) => {
    const angle = Math.PI + Math.PI * (mark / 100);
    const [x0, y0] = gaugePoint(cx, cy, radius + width / 2 + 4, angle);
    const [x1, y1] = gaugePoint(cx, cy, radius + width / 2 + 12, angle);
    return `<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" stroke="#8b97a3" stroke-width="1.5"></line>`;
  }).join("");
  const [sx, sy] = gaugePoint(cx, cy, 18, end);
  const [nx, ny] = gaugePoint(cx, cy, radius - width / 2 - 8, end);
  host.innerHTML = `<svg viewBox="0 0 480 300" role="img" aria-label="${value}% AI-like or suspicious">
    <defs>
      <linearGradient id="${gradientId}" x1="${leftX}" y1="${cy}" x2="${rightX}" y2="${cy}" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#1f9d57"></stop>
        <stop offset="28%" stop-color="#8fbe2f"></stop>
        <stop offset="52%" stop-color="#e2a30a"></stop>
        <stop offset="76%" stop-color="#e15c22"></stop>
        <stop offset="100%" stop-color="#d6453d"></stop>
      </linearGradient>
    </defs>
    <path d="${track}" fill="none" stroke="#e6edf3" stroke-width="${width}" stroke-linecap="butt"></path>
    ${fill ? `<path d="${fill}" fill="none" stroke="url(#${gradientId})" stroke-width="${width}" stroke-linecap="butt"></path>` : ""}
    ${ticks}
    <line x1="${sx}" y1="${sy}" x2="${nx}" y2="${ny}" stroke="#172033" stroke-width="2.5"></line>
    <circle cx="${cx}" cy="${cy}" r="6" fill="#172033"></circle>
    <text x="${cx}" y="${cy + 42}" text-anchor="middle" font-family="Outfit, sans-serif" font-size="46" font-weight="650" fill="${color}">${value}</text>
    <text x="${cx}" y="${cy + 62}" text-anchor="middle" font-family="Outfit, sans-serif" font-size="13" fill="#5c6b7a">${caption}</text>
    <text x="${cx - radius}" y="${cy + 22}" text-anchor="middle" font-family="Outfit, sans-serif" font-size="13" fill="#5c6b7a">0</text>
    <text x="${cx + radius}" y="${cy + 22}" text-anchor="middle" font-family="Outfit, sans-serif" font-size="13" fill="#5c6b7a">100</text>
    <text x="120" y="268" text-anchor="middle" font-family="Outfit, sans-serif" font-size="22" font-weight="650" fill="#172033">${reading.human}%</text>
    <text x="120" y="288" text-anchor="middle" font-family="Outfit, sans-serif" font-size="12" fill="#5c6b7a">Human-like</text>
    <text x="360" y="268" text-anchor="middle" font-family="Outfit, sans-serif" font-size="22" font-weight="650" fill="${color}">${value}%</text>
    <text x="360" y="288" text-anchor="middle" font-family="Outfit, sans-serif" font-size="12" fill="#5c6b7a">AI-like or suspicious</text>
  </svg>`;
}

function showReport(result) {
  const reading = readingOf(result.flagged_percent, result.uncertain_percent);
  drawGauge(document.querySelector("#donut"), reading, "suspicious");
  document.querySelector("#donut-blurb").textContent = `${explainReading(reading)} Confidence is ${result.confidence}.`;
  document.querySelector("#confidence-line").textContent = "";

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
  rewriteBody.hidden = true;
  reportEmpty.hidden = true;
  reportBody.hidden = false;
  reportBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showRewrite(result) {
  const before = readingOf(result.before_flagged, result.before_uncertain);
  const after = readingOf(result.after_flagged, result.after_uncertain);
  drawGauge(document.querySelector("#before-donut"), before, "before");
  drawGauge(document.querySelector("#after-donut"), after, "after");
  document.querySelector("#pair-blurb").textContent = `Before: ${explainReading(before)} After: ${explainReading(after)}`;
  document.querySelector("#rewrite").textContent = result.text;
  reportBody.hidden = true;
  reportEmpty.hidden = true;
  rewriteBody.hidden = false;
  rewriteBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function paintProgress(value, label) {
  const shown = Math.max(0, Math.min(100, Math.round(value)));
  progressRing.style.setProperty("--p", String(shown));
  progressPct.textContent = `${shown}%`;
  progressLabel.textContent = label;
}

function buttonsAvailable() {
  checkButton.disabled = !detectorReady;
  humanizeButton.disabled = !humanizerReady;
}

async function pollReady() {
  const [detectorResponse, humanResponse] = await Promise.all([
    fetch(appPath("/api/status")),
    fetch(appPath("/api/humanize/status")),
  ]);
  const detector = await detectorResponse.json();
  const human = await humanResponse.json();
  detectorReady = detector.status === "ready";
  humanizerReady = human.status === "ready";
  if (detector.status === "error") {
    modelState.textContent = detector.error || "Flyleaf failed to load.";
  } else if (human.status === "error" && detectorReady) {
    modelState.textContent = "Check for AI is ready. The humanizer failed to load.";
  } else if (detectorReady && humanizerReady) {
    modelState.textContent = "Ready · English · free to use";
  } else {
    modelState.textContent = "Flyleaf is getting ready...";
  }
  buttonsAvailable();
  return detectorReady && humanizerReady;
}

async function waitUntilReady() {
  for (;;) {
    try {
      const settled = await pollReady();
      if (settled) return;
    } catch (error) {
      modelState.textContent = "Flyleaf could not reach the checker.";
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

async function runJob(url, body, isForm, workingLabel, doneLabel, onDone) {
  checkButton.disabled = true;
  humanizeButton.disabled = true;
  progress.hidden = false;
  let shown = 4;
  let target = 8;
  let finished = false;
  paintProgress(shown, workingLabel);
  const timer = window.setInterval(() => {
    const ceiling = finished ? 100 : 92;
    target = Math.min(ceiling, Math.max(target, shown + 0.6));
    shown += (target - shown) * 0.12;
    paintProgress(shown, finished ? doneLabel : workingLabel);
  }, 80);

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: isForm ? undefined : { "Content-Type": "application/json" },
      body: isForm ? body : JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The request could not be started.");

    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      const jobResponse = await fetch(appPath(`/api/jobs/${payload.job_id}`));
      const job = await jobResponse.json();
      if (!jobResponse.ok) throw new Error(job.error || "The job was lost.");
      if (typeof job.percent === "number") target = Math.max(target, job.percent);
      if (job.status === "done") {
        finished = true;
        target = 100;
        await new Promise((resolve) => setTimeout(resolve, 350));
        onDone(job.result);
        return;
      }
      if (job.status === "error") throw new Error(job.error || "The job could not be finished.");
    }
  } catch (error) {
    window.alert(error.message);
  } finally {
    window.clearInterval(timer);
    progress.hidden = true;
    buttonsAvailable();
  }
}

checkButton.addEventListener("click", () => {
  if (selectedPdf() || (fileInput.files.length > 0 && words(draft.value) < 20)) {
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    runJob(appPath("/api/analyze"), form, true, "Reviewing the draft", "Opening the review", (result) => {
      if (result.review_url) {
        const opened = window.open(appPath(result.review_url), "_blank");
        if (!opened) window.location = appPath(result.review_url);
        return;
      }
      showReport(result);
    });
    return;
  }
  runJob(appPath("/api/analyze"), { text: draft.value }, false, "Reviewing the draft", "Opening the review", showReport);
});

humanizeButton.addEventListener("click", () => {
  if (words(draft.value) < 8) {
    window.alert("Paste a paragraph to humanize.");
    return;
  }
  runJob(appPath("/api/humanize"), { text: draft.value }, false, "Rewriting the draft", "Rewrite ready", showRewrite);
});

document.querySelector("#copy").addEventListener("click", async () => {
  const copy = document.querySelector("#copy");
  await navigator.clipboard.writeText(document.querySelector("#rewrite").textContent || "");
  copy.textContent = "Copied";
  window.setTimeout(() => {
    copy.textContent = "Copy";
  }, 1200);
});

document.querySelector("#check-rewrite").addEventListener("click", () => {
  const text = document.querySelector("#rewrite").textContent || "";
  if (words(text) < 8) return;
  draft.value = text;
  fileInput.value = "";
  showChosenFile(null);
  refreshCount();
  checkButton.click();
});

const upload = document.querySelector("#upload");
const uploadTitle = document.querySelector("#upload-title");
const fileHint = "A PDF opens as a marked report you can download.";

function showChosenFile(file) {
  if (!file) {
    upload.classList.remove("has-file");
    uploadTitle.textContent = "Upload a PDF, Word file, or .txt";
    fileName.textContent = fileHint;
    return;
  }
  upload.classList.add("has-file");
  uploadTitle.textContent = file.name;
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".pdf")) fileName.textContent = "This PDF will open as a marked report.";
  else if (lower.endsWith(".txt")) fileName.textContent = "The text is in the box above. You can still edit it.";
  else fileName.textContent = "Check for AI will score this file.";
}

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  showChosenFile(file);
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

["dragenter", "dragover"].forEach((name) => {
  upload.addEventListener(name, (event) => {
    event.preventDefault();
    upload.classList.add("drag");
  });
});
["dragleave", "drop"].forEach((name) => {
  upload.addEventListener(name, (event) => {
    event.preventDefault();
    upload.classList.remove("drag");
  });
});
upload.addEventListener("drop", (event) => {
  const dropped = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
  if (!dropped) return;
  const transfer = new DataTransfer();
  transfer.items.add(dropped);
  fileInput.files = transfer.files;
  fileInput.dispatchEvent(new Event("change"));
});

draft.addEventListener("input", () => {
  if (draft.value.trim()) {
    fileInput.value = "";
    showChosenFile(null);
  }
  refreshCount();
});

document.querySelector("#sample-human").addEventListener("click", () => {
  fileInput.value = "";
  showChosenFile(null);
  draft.value = samples.human;
  refreshCount();
});

document.querySelector("#sample-ai").addEventListener("click", () => {
  fileInput.value = "";
  showChosenFile(null);
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
