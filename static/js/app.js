const draft = document.querySelector("#draft");
const fileInput = document.querySelector("#file");
const uploadLabel = document.querySelector("#upload-label");
const wordCount = document.querySelector("#word-count");
const checkButton = document.querySelector("#run-check");
const humanizeButton = document.querySelector("#humanize");
const offerHumanize = document.querySelector("#offer-humanize");
const HIGH_AI = 50;
const modelState = document.querySelector("#model-state");
const reportBody = document.querySelector("#report-body");
const rewriteBody = document.querySelector("#rewrite-body");
const reportEmpty = document.querySelector("#report-empty");
const progress = document.querySelector("#progress");
const progressLabel = document.querySelector("#progress-label");
const progressPct = document.querySelector("#progress-pct");
const progressBar = document.querySelector("#progress-bar");
const progressTrack = document.querySelector("#progress-track");

const samples = {
  human: `I missed the 6:40 daladala and ended up walking from Mwenge with a torn umbrella. The rain was not even serious, just that annoying spit that still soaks a notebook. My phone had 4 percent and of course the power bank was in the other bag, the one I left on the chair at home. By the time I got to class the quiz had started. I wrote my name too big and then stared at question two, the one about buffers, and my mind went completely blank except for the fact that my socks were wet. I still think the lecturer saw me come in. She did not say anything. She just tapped her watch once, which was worse.`,
  ai: `Artificial intelligence has transformed the way students approach academic writing. These systems can generate coherent essays, summarize complex materials, and provide structured arguments within seconds. However, the widespread availability of such tools raises important questions about academic integrity and original thought. Educators must balance the benefits of technological assistance with the need to preserve critical thinking skills. Institutions are therefore adopting detection methods and clearer policies to guide responsible use. Ultimately, the goal is not to reject innovation, but to ensure that submitted work reflects a student's own understanding and effort.`,
};

let detectorReady = false;
let humanizerReady = false;
let lastCheck = null;
let lastRewrite = null;

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

async function readJson(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error("Flyleaf could not finish that request. Wait a minute and try again.");
  }
}

async function readJob(url) {
  try {
    const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) return null;
    return JSON.parse(await response.text());
  } catch (error) {
    return null;
  }
}

function words(value) {
  const found = value.trim().match(/\b[\w']+\b/g);
  return found ? found.length : 0;
}

function refreshCount() {
  const count = words(draft.value);
  wordCount.textContent = `${count} word${count === 1 ? "" : "s"}`;
  draft.classList.toggle("has-prose", Boolean(draft.value.trim()));
  if (typeof buttonsAvailable === "function") buttonsAvailable();
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
  const { ai, uncertain } = reading;
  let lead = "The draft was read as human-like.";
  if (ai > 0 && uncertain === 0) lead = `${ai}% was classified as AI-like.`;
  if (ai === 0 && uncertain > 0) lead = `None of it was classified as clearly AI-like. ${uncertain}% was inconclusive.`;
  if (ai > 0 && uncertain > 0) lead = `${ai}% was classified as AI-like. ${uncertain}% was inconclusive.`;
  return `${lead} The result is an estimate and does not establish whether the text was written by AI.`;
}

let gaugeSerial = 0;

function drawGauge(host, reading, caption) {
  const cx = 240;
  const cy = 168;
  const radius = 112;
  const width = 28;
  const value = Math.max(0, Math.min(100, reading.ai));
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
  host.innerHTML = `<svg viewBox="0 0 480 300" role="img" aria-label="${value}% AI-like, ${reading.uncertain}% inconclusive">
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
    <text x="360" y="268" text-anchor="middle" font-family="Outfit, sans-serif" font-size="22" font-weight="650" fill="#6b5b8a">${reading.uncertain}%</text>
    <text x="360" y="288" text-anchor="middle" font-family="Outfit, sans-serif" font-size="12" fill="#5c6b7a">Inconclusive</text>
  </svg>`;
}

function shareSentence(reading, kind) {
  const { ai, uncertain } = reading;
  let lead = "This draft was not classified as AI-like.";
  if (ai >= 60) lead = "Much of this draft was classified as AI-like.";
  else if (ai >= 25) lead = "This draft is mixed. Some of it was classified as AI-like.";
  else if (ai > 0) lead = "A small share was classified as AI-like.";
  else if (uncertain >= 25) lead = "None of it was classified as clearly AI-like. A noticeable share was inconclusive.";
  if (kind === "rewrite") lead = `After the rewrite, ${lead.charAt(0).toLowerCase()}${lead.slice(1)}`;
  return lead;
}

function drawShareRing(host, reading) {
  if (!host) return;
  const human = reading.human;
  const mid = reading.uncertain;
  const ai = reading.ai;
  const parts = [
    { value: human, color: "#1f9d57" },
    { value: mid, color: "#6b5b8a" },
    { value: ai, color: "#c9342e" },
  ];
  let cursor = 0;
  const arcs = parts.map((part) => {
    const start = cursor;
    cursor += part.value;
    if (part.value <= 0) return "";
    const begin = Math.PI * 2 * (start / 100) - Math.PI / 2;
    const end = Math.PI * 2 * (cursor / 100) - Math.PI / 2;
    const large = part.value > 50 ? 1 : 0;
    const r = 46;
    const cx = 60;
    const cy = 60;
    const x0 = cx + r * Math.cos(begin);
    const y0 = cy + r * Math.sin(begin);
    const x1 = cx + r * Math.cos(end);
    const y1 = cy + r * Math.sin(end);
    if (part.value >= 100) {
      return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${part.color}" stroke-width="12"></circle>`;
    }
    return `<path d="M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}" fill="none" stroke="${part.color}" stroke-width="12"></path>`;
  }).join("");
  host.innerHTML = `<svg viewBox="0 0 120 120" role="img" aria-label="${ai}% AI-like, ${mid}% inconclusive, ${human}% human-like">
    <circle cx="60" cy="60" r="46" fill="none" stroke="#e6edf3" stroke-width="12"></circle>
    ${arcs}
    <text x="60" y="56" text-anchor="middle" font-family="Outfit, sans-serif" font-size="22" font-weight="650" fill="#1c2430">${ai}%</text>
    <text x="60" y="72" text-anchor="middle" font-family="Outfit, sans-serif" font-size="10" fill="#5c6b78">AI-like</text>
  </svg>`;
}

function fillReading(reading, confidence, wordCount, kind) {
  const host = document.querySelector("#reading-more");
  if (!host) return;
  const line = document.querySelector("#reading-line");
  line.innerHTML = "";
  const lead = document.createElement("span");
  lead.textContent = shareSentence(reading, kind);
  lead.style.fontWeight = "650";
  lead.style.color = "var(--ink)";
  lead.style.fontSize = "20px";
  const note = document.createElement("span");
  note.textContent = "That is an estimate. It does not establish whether the text was written by AI.";
  line.append(lead, note);
  drawShareRing(document.querySelector("#share-ring"), reading);
  const list = document.querySelector("#share-list");
  const rows = [
    ["Human-like", reading.human, "#1f9d57"],
    ["Inconclusive", reading.uncertain, "#6b5b8a"],
    ["AI-like", reading.ai, "#c9342e"],
  ];
  list.replaceChildren();
  for (const [name, value, color] of rows) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.className = "share-name";
    const dot = document.createElement("span");
    dot.className = "share-dot";
    dot.style.background = color;
    label.append(dot, document.createTextNode(name));
    const strong = document.createElement("strong");
    strong.textContent = `${value}%`;
    item.append(label, strong);
    list.append(item);
  }
  const facts = document.querySelector("#reading-facts");
  facts.replaceChildren();
  const cards = [
    ["Confidence", confidence ? confidence.charAt(0).toUpperCase() + confidence.slice(1) : "Shown on the gauge"],
    ["Length", `${Number(wordCount) || 0} words`],
    ["The reading", "One English model, on this computer"],
  ];
  for (const [title, body] of cards) {
    const card = document.createElement("article");
    const heading = document.createElement("h3");
    heading.textContent = title;
    const copy = document.createElement("p");
    copy.textContent = body;
    card.append(heading, copy);
    facts.append(card);
  }
  host.hidden = false;
}

function sentenceSpan(sentence) {
  const span = document.createElement("span");
  const pct = Math.round((Number(sentence.ai_probability) || 0) * 100);
  const names = { ai: "AI-like", uncertain: "Inconclusive", human: "Human-like" };
  const shown = sentence.label === "human" ? 100 - pct : pct;
  span.className = sentence.label || "human";
  span.dataset.tip = `${names[sentence.label] || "Read"} ${shown}%`;
  return span;
}

function locateSentence(text, needle, from) {
  if (!needle) return null;
  const exact = text.indexOf(needle, from);
  if (exact >= 0) return { start: exact, end: exact + needle.length };
  const parts = needle.split(/\s+/).filter(Boolean);
  if (!parts.length) return null;
  const pattern = parts.map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  const match = new RegExp(pattern, "g");
  match.lastIndex = from;
  const found = match.exec(text);
  if (!found) return null;
  return { start: found.index, end: found.index + found[0].length };
}

function paintPassage(host, source, sentences) {
  host.replaceChildren();
  const text = source && source.trim() ? source : (sentences || []).map((item) => item.text).join(" ");
  let cursor = 0;
  (sentences || []).forEach((sentence) => {
    const place = locateSentence(text, sentence.text || "", cursor);
    const span = sentenceSpan(sentence);
    if (!place) {
      if (host.childNodes.length) host.append(document.createTextNode("\n\n"));
      span.textContent = sentence.text || "";
      host.append(span);
      return;
    }
    if (place.start > cursor) host.append(document.createTextNode(text.slice(cursor, place.start)));
    span.textContent = text.slice(place.start, place.end);
    host.append(span);
    cursor = place.end;
  });
  if (cursor < text.length) host.append(document.createTextNode(text.slice(cursor)));
}

function showReport(result) {
  lastCheck = result;
  const reading = readingOf(result.flagged_percent, result.uncertain_percent);
  drawGauge(document.querySelector("#donut"), reading, "AI-like");
  document.querySelector("#donut-blurb").textContent = `${explainReading(reading)} Confidence is ${result.confidence}.`;
  const confidenceLine = document.querySelector("#confidence-line");
  if (confidenceLine) confidenceLine.textContent = "";
  fillReading(reading, result.confidence, result.word_count, "check");

  const warnings = document.querySelector("#warnings");
  if (warnings) {
    warnings.replaceChildren();
    for (const warning of result.warnings || []) {
      const item = document.createElement("li");
      item.textContent = warning;
      warnings.appendChild(item);
    }
  }

  const essay = document.querySelector("#essay");
  if (essay) {
    const typed = draft && draft.value ? draft.value : "";
    paintPassage(essay, typed, result.sentences || []);
  }
  if (rewriteBody) rewriteBody.hidden = true;
  if (reportEmpty) reportEmpty.hidden = true;
  if (reportBody) reportBody.hidden = false;
  const scoreMore = document.querySelector("#score-more");
  const reportScore = document.querySelector("#report-score");
  const rewriteScore = document.querySelector("#rewrite-score");
  if (scoreMore) scoreMore.hidden = false;
  if (reportScore) reportScore.hidden = false;
  if (rewriteScore) rewriteScore.hidden = true;
  if (offerHumanize) offerHumanize.hidden = reading.ai < HIGH_AI;
  const marked = document.querySelector("#marked-text");
  const rewriteText = document.querySelector("#rewrite-text");
  if (marked) marked.hidden = false;
  if (rewriteText) rewriteText.hidden = true;
  resetSave("#save-check", "#save-check-note", "Save this check");
  if (reportBody) reportBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showRewrite(result) {
  lastRewrite = result;
  const before = readingOf(result.before_flagged, result.before_uncertain);
  const after = readingOf(result.after_flagged, result.after_uncertain);
  drawGauge(document.querySelector("#before-donut"), before, "before");
  drawGauge(document.querySelector("#after-donut"), after, "after");
  document.querySelector("#pair-blurb").textContent = `Before: ${explainReading(before)} After: ${explainReading(after)}`;
  const rewrite = document.querySelector("#rewrite");
  if (rewrite) rewrite.textContent = result.text;
  fillReading(after, "", result.word_count, "rewrite");
  if (reportBody) reportBody.hidden = true;
  if (reportEmpty) reportEmpty.hidden = true;
  if (rewriteBody) rewriteBody.hidden = false;
  const scoreMore = document.querySelector("#score-more");
  const reportScore = document.querySelector("#report-score");
  const rewriteScore = document.querySelector("#rewrite-score");
  if (scoreMore) scoreMore.hidden = false;
  if (reportScore) reportScore.hidden = true;
  if (rewriteScore) rewriteScore.hidden = false;
  if (offerHumanize) offerHumanize.hidden = true;
  const marked = document.querySelector("#marked-text");
  const rewriteText = document.querySelector("#rewrite-text");
  if (marked) marked.hidden = true;
  if (rewriteText) rewriteText.hidden = false;
  resetSave("#save-rewrite", "#save-rewrite-note", "Save this rewrite");
  if (rewriteBody) rewriteBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function resetSave(buttonId, noteId, label) {
  const button = document.querySelector(buttonId);
  const note = document.querySelector(noteId);
  if (button && button.tagName === "BUTTON") {
    button.disabled = false;
    button.textContent = label;
  }
  if (note) note.textContent = "";
}

function sourceFor(result) {
  const typed = (draft && draft.value ? draft.value : "").trim();
  if (typed) return typed;
  return (result.sentences || []).map((item) => item.text).join(" ");
}

async function keepUpload(filename, result) {
  if (!result || !result.review_id) return;
  const token = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
  const response = await fetch(appPath("/api/documents"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
    body: JSON.stringify({ filename, review_id: result.review_id, result }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "That PDF could not be kept.");
}

async function storeWork(button, note, kind, source, result) {
  button.disabled = true;
  if (note) note.textContent = "Saving...";
  try {
    const token = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
    const response = await fetch(appPath("/api/saved"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
      },
      body: JSON.stringify({ kind, source_text: source, result }),
    });
    const payload = await readJson(response);
    if (!response.ok) throw new Error(payload.error || "Could not save that draft.");
    button.textContent = "Saved";
    if (note) note.textContent = "Kept in your saved work.";
  } catch (error) {
    button.disabled = false;
    if (note) note.textContent = error.message;
  }
}

function paintProgress(value, label) {
  const shown = Math.max(0, Math.min(100, Math.round(value)));
  if (progressBar) progressBar.style.width = `${shown}%`;
  if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(shown));
  if (progressPct) progressPct.textContent = `${shown}%`;
  if (progressLabel) progressLabel.textContent = label;
}

function setBusyLabel(button, label) {
  const node = button && button.querySelector(".btn-label");
  if (!node) return;
  if (!button.dataset.idleLabel) button.dataset.idleLabel = node.textContent;
  node.textContent = label;
  button.classList.add("is-busy");
}

function clearBusyLabel(button) {
  const node = button && button.querySelector(".btn-label");
  if (node && button.dataset.idleLabel) node.textContent = button.dataset.idleLabel;
  if (button) button.classList.remove("is-busy");
}

function buttonsAvailable() {
  const busy = (checkButton && checkButton.classList.contains("is-busy"))
    || (humanizeButton && humanizeButton.classList.contains("is-busy"));
  if (busy) return;
  const count = draft ? words(draft.value) : 0;
  const hasFile = Boolean(fileInput && fileInput.files && fileInput.files.length > 0);
  if (checkButton) checkButton.disabled = !detectorReady || (count < 20 && !hasFile);
  if (humanizeButton) humanizeButton.disabled = !humanizerReady || count < 8;
  if (offerHumanize) offerHumanize.disabled = !humanizerReady;
}

async function readStatus(path) {
  const response = await fetch(appPath(path));
  if (!response.ok) throw new Error("status unavailable");
  return response.json();
}

async function pollReady() {
  const detector = await readStatus("/api/status");
  let human = { status: "loading", error: null };
  try {
    human = await readStatus("/api/humanize/status");
  } catch (error) {
    human = { status: "loading", error: null };
  }
  detectorReady = detector.status === "ready";
  humanizerReady = human.status === "ready";
  if (detector.error && !detectorReady) {
    modelState.textContent = detector.error;
  } else if (detector.status === "error") {
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

async function runJob(url, body, isForm, workingLabel, doneLabel, onDone, busyButton) {
  checkButton.disabled = true;
  humanizeButton.disabled = true;
  if (offerHumanize) offerHumanize.disabled = true;
  setBusyLabel(busyButton, "Processing");
  if (reportEmpty) reportEmpty.hidden = true;
  if (reportBody) reportBody.hidden = true;
  if (rewriteBody) rewriteBody.hidden = true;
  const scoreMore = document.querySelector("#score-more");
  if (scoreMore) scoreMore.hidden = true;
  const readingMore = document.querySelector("#reading-more");
  const marked = document.querySelector("#marked-text");
  const rewriteText = document.querySelector("#rewrite-text");
  if (readingMore) readingMore.hidden = true;
  if (marked) marked.hidden = true;
  if (rewriteText) rewriteText.hidden = true;
  progress.hidden = false;
  let shown = 4;
  let target = 8;
  let finished = false;
  paintProgress(shown, workingLabel);
  const timer = window.setInterval(() => {
    const ceiling = finished ? 100 : 90;
    target = Math.min(ceiling, target);
    shown += (target - shown) * 0.12;
    paintProgress(shown, finished ? doneLabel : workingLabel);
  }, 80);

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: isForm ? undefined : { "Content-Type": "application/json" },
      body: isForm ? body : JSON.stringify(body),
    });
    const payload = await readJson(response);
    if (!response.ok) throw new Error(payload.error || "The request could not be started.");
    if (payload.status === "done" && payload.result) {
      finished = true;
      target = 100;
      await new Promise((resolve) => setTimeout(resolve, 350));
      onDone(payload.result);
      return;
    }
    if (payload.status === "error") throw new Error(payload.error || "The job could not be finished.");

    const started = Date.now();
    let lastBeat = Date.now();
    let lastUpdated = 0;
    const watchUrl = payload.watch_url || appPath(`/api/jobs/${payload.job_id}`);
    for (;;) {
      if (Date.now() - lastBeat > 90000) {
        throw new Error("The host stopped this check before it finished. Wait a minute and try again.");
      }
      await new Promise((resolve) => setTimeout(resolve, 700));
      let job = await readJob(watchUrl);
      if (!job) job = await readJob(appPath(`/api/jobs/${payload.job_id}`));
      if (!job) continue;
      if (typeof job.updated === "number" && job.updated !== lastUpdated) {
        lastUpdated = job.updated;
        lastBeat = Date.now();
      }
      if (Date.now() - started > 900000) {
        throw new Error("This reading is still going. Leave the page open a little longer.");
      }
      if (typeof job.percent === "number") target = Math.max(6, job.percent);
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
    clearBusyLabel(checkButton);
    clearBusyLabel(humanizeButton);
    clearBusyLabel(offerHumanize);
    if (reportEmpty && reportBody && rewriteBody && reportBody.hidden && rewriteBody.hidden) {
      reportEmpty.hidden = false;
    }
    buttonsAvailable();
  }
}

if (draft) {
checkButton.addEventListener("click", () => {
  if (selectedPdf() || (fileInput.files.length > 0 && words(draft.value) < 20)) {
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    runJob(appPath("/api/analyze"), form, true, "Reviewing the draft", "Opening the review", (result) => {
      const chosen = fileInput.files[0];
      const openReview = () => {
        if (result.review_url) {
          const opened = window.open(appPath(result.review_url), "_blank");
          if (!opened) window.location = appPath(result.review_url);
          return;
        }
        showReport(result);
      };
      if (chosen && result.review_id && document.body.dataset.signedIn === "1") {
        keepUpload(chosen.name, result).then(openReview).catch((error) => {
          window.alert(error.message);
          openReview();
        });
        return;
      }
      openReview();
    }, checkButton);
    return;
  }
  const textBody = new URLSearchParams();
  textBody.set("text", draft.value);
  runJob(appPath("/api/analyze"), textBody, true, "Reviewing the draft", "Opening the review", showReport, checkButton);
});

function startHumanize(busyButton) {
  if (words(draft.value) < 8) {
    window.alert("Paste a paragraph to humanize.");
    return;
  }
  const textBody = new URLSearchParams();
  textBody.set("text", draft.value);
  runJob(appPath("/api/humanize"), textBody, true, "Rewriting the draft", "Rewrite ready", showRewrite, busyButton);
}

humanizeButton.addEventListener("click", () => startHumanize(humanizeButton));
if (offerHumanize) offerHumanize.addEventListener("click", () => startHumanize(offerHumanize));

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

function showChosenFile(file) {
  if (!upload) return;
  if (!file) {
    upload.classList.remove("has-file");
    if (uploadLabel) uploadLabel.textContent = "Upload";
    return;
  }
  upload.classList.add("has-file");
  if (uploadLabel) uploadLabel.textContent = file.name;
}

function setPasteMode(mode) {
  const checking = mode !== "humanize";
  const modeCheck = document.querySelector("#mode-check");
  const modeHumanize = document.querySelector("#mode-humanize");
  if (modeCheck) {
    modeCheck.classList.toggle("is-selected", checking);
    modeCheck.setAttribute("aria-pressed", checking ? "true" : "false");
  }
  if (modeHumanize) {
    modeHumanize.classList.toggle("is-selected", !checking);
    modeHumanize.setAttribute("aria-pressed", checking ? "false" : "true");
  }
  if (checkButton) checkButton.hidden = !checking;
  if (humanizeButton) humanizeButton.hidden = checking;
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
  buttonsAvailable();
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
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    const active = humanizeButton && !humanizeButton.hidden ? humanizeButton : checkButton;
    if (active && !active.disabled) active.click();
  }
});

const modeCheck = document.querySelector("#mode-check");
const modeHumanize = document.querySelector("#mode-humanize");
if (modeCheck) modeCheck.addEventListener("click", () => setPasteMode("check"));
if (modeHumanize) modeHumanize.addEventListener("click", () => setPasteMode("humanize"));

const clearDraft = document.querySelector("#clear-draft");
if (clearDraft) {
  clearDraft.addEventListener("click", () => {
    draft.value = "";
    fileInput.value = "";
    showChosenFile(null);
    refreshCount();
  });
}

const saveCheck = document.querySelector("#save-check");
if (saveCheck && saveCheck.tagName === "BUTTON") {
  saveCheck.addEventListener("click", () => {
    const source = sourceFor(lastCheck || {});
    if (!lastCheck || !source) return;
    storeWork(saveCheck, document.querySelector("#save-check-note"), "check", source, lastCheck);
  });
}
const saveRewrite = document.querySelector("#save-rewrite");
if (saveRewrite && saveRewrite.tagName === "BUTTON") {
  saveRewrite.addEventListener("click", () => {
    const source = (draft.value || "").trim();
    if (!lastRewrite || !source) return;
    storeWork(saveRewrite, document.querySelector("#save-rewrite-note"), "rewrite", source, lastRewrite);
  });
}

refreshCount();
waitUntilReady();
}
