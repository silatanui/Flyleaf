const draft = document.querySelector("#draft");
const fileInput = document.querySelector("#file");
const uploadLabel = document.querySelector("#upload-label");
const wordCount = document.querySelector("#word-count");
const checkButton = document.querySelector("#run-check");
const humanizeButton = document.querySelector("#humanize");
const similarityButton = document.querySelector("#run-similarity");
const offerHumanize = document.querySelector("#offer-humanize");
const HIGH_AI = 50;
const modelState = document.querySelector("#model-state");
const reportBody = document.querySelector("#report-body");
const rewriteBody = document.querySelector("#rewrite-body");
const similarityBody = document.querySelector("#similarity-body");
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
let similarityReady = false;
let pasteMode = "check";
let lastCheck = null;
let lastRewrite = null;
let lastSimilarity = null;
let secondaryPoll = 0;

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

function selectedUpload() {
  const file = fileInput && fileInput.files && fileInput.files[0];
  if (!file) return false;
  const name = file.name.toLowerCase();
  return name.endsWith(".pdf") || name.endsWith(".docx") || name.endsWith(".txt");
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
  const { ai, uncertain, human } = reading;
  let lead = "Most of this draft was read as human-like.";
  if (ai >= 60) lead = "Much of this draft was classified as AI-like.";
  else if (ai >= 25) lead = "This draft is mixed. A clear share was classified as AI-like.";
  else if (ai > 0 && uncertain > 0) lead = `${ai}% was classified as AI-like, and ${uncertain}% was inconclusive.`;
  else if (ai > 0) lead = `${ai}% was classified as AI-like.`;
  else if (uncertain >= 25) lead = `None of it was classified as clearly AI-like. ${uncertain}% was inconclusive.`;
  else if (uncertain > 0) lead = `None of it was classified as clearly AI-like. ${uncertain}% was inconclusive.`;
  return `${lead} Breakdown: ${ai}% AI-like, ${uncertain}% inconclusive, ${human}% human-like. That is an estimate and does not establish whether the text was written by AI.`;
}

function drawGauge(host, reading, caption) {
  if (!host) return;
  const human = reading.human;
  const mid = reading.uncertain;
  const ai = reading.ai;
  const cx = 150;
  const cy = 150;
  const radius = 108;
  const width = 34;
  const parts = [
    { value: human, color: "#1f9d57", label: "Human-like" },
    { value: mid, color: "#6b5b8a", label: "Inconclusive" },
    { value: ai, color: "#c9342e", label: "AI-like" },
  ];
  let cursor = 0;
  const arcs = parts.map((part) => {
    const start = cursor;
    cursor += part.value;
    if (part.value <= 0) return "";
    const begin = Math.PI * 2 * (start / 100) - Math.PI / 2;
    const end = Math.PI * 2 * (cursor / 100) - Math.PI / 2;
    if (part.value >= 99.5) {
      return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="none" stroke="${part.color}" stroke-width="${width}"></circle>`;
    }
    const [x0, y0] = gaugePoint(cx, cy, radius, begin);
    const [x1, y1] = gaugePoint(cx, cy, radius, end);
    const large = part.value > 50 ? 1 : 0;
    return `<path d="M ${x0} ${y0} A ${radius} ${radius} 0 ${large} 1 ${x1} ${y1}" fill="none" stroke="${part.color}" stroke-width="${width}" stroke-linecap="butt"></path>`;
  }).join("");
  const centerColor = speedColor(ai);
  host.innerHTML = `<svg viewBox="0 0 300 300" role="img" aria-label="${ai}% AI-like, ${mid}% inconclusive, ${human}% human-like">
    <circle cx="${cx}" cy="${cy}" r="${radius}" fill="none" stroke="#e6edf3" stroke-width="${width}"></circle>
    ${arcs}
    <text x="${cx}" y="${cy - 8}" text-anchor="middle" font-family="Outfit, sans-serif" font-size="52" font-weight="650" fill="${centerColor}">${ai}%</text>
    <text x="${cx}" y="${cy + 22}" text-anchor="middle" font-family="Outfit, sans-serif" font-size="15" fill="#5c6b7a">${caption || "AI-like"}</text>
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

function fillScoreBreakdown(reading) {
  const list = document.querySelector("#score-breakdown");
  if (!list) return;
  const rows = [
    ["AI-like", reading.ai, "#c9342e"],
    ["Inconclusive", reading.uncertain, "#6b5b8a"],
    ["Human-like", reading.human, "#1f9d57"],
  ];
  list.replaceChildren();
  for (const [name, value, color] of rows) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    const dot = document.createElement("span");
    dot.className = "share-dot";
    dot.style.background = color;
    label.append(dot, document.createTextNode(` ${name}`));
    const strong = document.createElement("strong");
    strong.textContent = `${value}%`;
    item.append(label, strong);
    list.appendChild(item);
  }
}

function showReport(result) {
  lastCheck = result;
  const reading = readingOf(result.flagged_percent, result.uncertain_percent);
  drawGauge(document.querySelector("#donut"), reading, "AI-like");
  document.querySelector("#donut-blurb").textContent = `${explainReading(reading)} Confidence is ${result.confidence}.`;
  fillScoreBreakdown(reading);
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
  if (similarityBody) similarityBody.hidden = true;
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
  const rewrite = document.querySelector("#rewrite");
  if (rewrite) rewrite.textContent = result.text || "";
  if (reportBody) reportBody.hidden = true;
  if (similarityBody) similarityBody.hidden = true;
  if (reportEmpty) reportEmpty.hidden = true;
  if (rewriteBody) rewriteBody.hidden = false;
  const scoreMore = document.querySelector("#score-more");
  const reportScore = document.querySelector("#report-score");
  const rewriteScore = document.querySelector("#rewrite-score");
  if (scoreMore) scoreMore.hidden = false;
  if (reportScore) reportScore.hidden = true;
  if (rewriteScore) rewriteScore.hidden = false;
  if (offerHumanize) offerHumanize.hidden = true;
  const pairBlurb = document.querySelector("#pair-blurb");
  if (pairBlurb) {
    pairBlurb.textContent = "Here is the rewritten draft. Use Check this rewrite if you want an AI reading of it.";
  }
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
    || (humanizeButton && humanizeButton.classList.contains("is-busy"))
    || (similarityButton && similarityButton.classList.contains("is-busy"));
  if (busy) return;
  const count = draft ? words(draft.value) : 0;
  const hasFile = Boolean(fileInput && fileInput.files && fileInput.files.length > 0);
  // Allow a click while models load; the job waits on the server until ready.
  if (checkButton) checkButton.disabled = count < 20 && !hasFile;
  if (humanizeButton) humanizeButton.disabled = count < 8;
  if (similarityButton) similarityButton.disabled = count < 40 && !hasFile;
  if (offerHumanize) offerHumanize.disabled = count < 8;
}

function showSimilarity(result) {
  lastSimilarity = result;
  const headline = document.querySelector("#similarity-headline");
  const note = document.querySelector("#similarity-note");
  const warnings = document.querySelector("#similarity-warnings");
  const sources = document.querySelector("#similarity-sources");
  const matches = document.querySelector("#similarity-matches");
  const download = document.querySelector("#similarity-download");
  if (headline) {
    headline.textContent = `${Number(result.overall_percent || 0)}% similar to public web pages`;
  }
  if (note) {
    note.textContent = result.disclaimer
      || "This estimate comes from public web pages found for this draft. It is not a finding of misconduct.";
  }
  if (warnings) {
    warnings.replaceChildren();
    for (const warning of result.warnings || []) {
      const item = document.createElement("li");
      item.textContent = warning;
      warnings.appendChild(item);
    }
  }
  if (sources) {
    sources.replaceChildren();
    const rows = result.sources || [];
    if (!rows.length) {
      const item = document.createElement("li");
      item.textContent = "No public sources matched.";
      sources.appendChild(item);
    } else {
      rows.forEach((row) => {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = row.url || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = row.title || row.host || row.url || "Source";
        const meta = document.createElement("span");
        const host = row.host || "";
        const share = `${Number(row.share || 0)}%`;
        meta.textContent = host ? ` · ${host} · ${share}` : ` · ${share}`;
        item.append(link, meta);
        sources.appendChild(item);
      });
    }
  }
  if (matches) {
    matches.replaceChildren();
    const rows = result.matches || [];
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "similarity-empty";
      empty.textContent = "No close excerpts were kept.";
      matches.appendChild(empty);
    } else {
      rows.slice(0, 20).forEach((row) => {
        const card = document.createElement("article");
        card.className = "similarity-match";
        const head = document.createElement("p");
        head.className = "similarity-match-head";
        const link = document.createElement("a");
        link.href = row.url || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = row.title || row.url || "Source";
        head.append(
          document.createTextNode(`${Math.round(100 * Number(row.score || 0))}% · `),
          link,
        );
        const draftLine = document.createElement("p");
        draftLine.textContent = `Your draft: ${row.draft_excerpt || ""}`;
        const sourceLine = document.createElement("p");
        sourceLine.textContent = `Source text: ${row.source_excerpt || ""}`;
        card.append(head, draftLine, sourceLine);
        matches.appendChild(card);
      });
    }
  }
  if (download) {
    // Full report / download is only for PDF uploads, not pasted text.
    if (result.review_url) {
      download.hidden = false;
      download.href = appPath(result.review_url);
      const label = download.querySelector(".btn-label");
      if (label) label.textContent = "Open full report";
      download.target = "_blank";
      download.rel = "noopener noreferrer";
    } else {
      download.hidden = true;
      download.removeAttribute("href");
      download.removeAttribute("target");
    }
  }
  if (reportBody) reportBody.hidden = true;
  if (rewriteBody) rewriteBody.hidden = true;
  if (reportEmpty) reportEmpty.hidden = true;
  if (similarityBody) similarityBody.hidden = false;
  const scoreMore = document.querySelector("#score-more");
  if (scoreMore) scoreMore.hidden = true;
  if (similarityBody) similarityBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function readStatus(path) {
  const response = await fetch(appPath(path));
  if (!response.ok) throw new Error("status unavailable");
  return response.json();
}

function shortToolError(prefix, detail) {
  const note = String(detail || "").replace(/\s+/g, " ").trim();
  if (!note) return prefix;
  const clipped = note.length > 160 ? `${note.slice(0, 157)}...` : note;
  return `${prefix} ${clipped}`;
}

async function pollReady() {
  const detector = await readStatus("/api/status");
  let human = { status: "loading", error: null };
  let similar = { status: "loading", error: null };
  try {
    human = await readStatus("/api/humanize/status");
  } catch (error) {
    human = { status: "loading", error: null };
  }
  try {
    similar = await readStatus("/api/similarity/status");
  } catch (error) {
    similar = { status: "loading", error: null };
  }
  detectorReady = detector.status === "ready";
  humanizerReady = human.status === "ready";
  similarityReady = similar.status === "ready";
  if (detector.error && !detectorReady) {
    modelState.textContent = detector.error;
  } else if (detector.status === "error") {
    modelState.textContent = detector.error || "Flyleaf failed to load.";
  } else if (detectorReady && human.status === "error" && similar.status === "error") {
    modelState.textContent = shortToolError(
      "Check for AI is ready. Humanize and Similarity could not load.",
      human.error || similar.error,
    );
  } else if (detectorReady && human.status === "error") {
    modelState.textContent = shortToolError(
      similarityReady
        ? "Check for AI and Similarity are ready. The humanizer failed to load."
        : "Check for AI is ready. The humanizer failed to load.",
      human.error,
    );
  } else if (detectorReady && similar.status === "error") {
    modelState.textContent = shortToolError(
      humanizerReady
        ? "Check for AI and Humanize are ready. Similarity failed to load."
        : "Check for AI is ready. Similarity failed to load.",
      similar.error,
    );
  } else if (detectorReady && humanizerReady && similarityReady) {
    modelState.textContent = "Ready · English · free to use";
  } else if (detectorReady) {
    const waiting = [];
    if (!humanizerReady) waiting.push("Humanize");
    if (!similarityReady) waiting.push("Similarity");
    modelState.textContent = waiting.length
      ? `Check for AI is ready. Still loading ${waiting.join(" and ")}...`
      : "Check for AI is ready.";
  } else {
    modelState.textContent = "Flyleaf is getting ready...";
  }
  buttonsAvailable();
  return detectorReady;
}

async function waitUntilReady() {
  for (;;) {
    try {
      const settled = await pollReady();
      if (settled) {
        if ((!humanizerReady || !similarityReady) && !secondaryPoll) {
          secondaryPoll = window.setInterval(() => {
            pollReady().catch(() => {});
          }, 4000);
        }
        return;
      }
    } catch (error) {
      modelState.textContent = "Flyleaf could not reach the checker.";
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

async function runJob(url, body, isForm, workingLabel, doneLabel, onDone, busyButton) {
  checkButton.disabled = true;
  humanizeButton.disabled = true;
  if (similarityButton) similarityButton.disabled = true;
  if (offerHumanize) offerHumanize.disabled = true;
  setBusyLabel(busyButton, "Processing");
  if (reportEmpty) reportEmpty.hidden = true;
  if (reportBody) reportBody.hidden = true;
  if (rewriteBody) rewriteBody.hidden = true;
  if (similarityBody) similarityBody.hidden = true;
  const scoreMore = document.querySelector("#score-more");
  if (scoreMore) scoreMore.hidden = true;
  const readingMore = document.querySelector("#reading-more");
  const marked = document.querySelector("#marked-text");
  const rewriteText = document.querySelector("#rewrite-text");
  if (readingMore) readingMore.hidden = true;
  if (marked) marked.hidden = true;
  if (rewriteText) rewriteText.hidden = true;
  progress.hidden = false;
  // Match server job start (6%) so the bar never climbs past the job then snaps back.
  let shown = 6;
  let target = 6;
  let finished = false;
  let liveLabel = workingLabel;
  paintProgress(shown, liveLabel);
  const timer = window.setInterval(() => {
    const ceiling = finished ? 100 : 94;
    if (target > ceiling) target = ceiling;
    // Ease forward only so the bar never jumps backward.
    if (target > shown) shown += Math.max(0.15, (target - shown) * 0.14);
    else if (finished && shown < 100) shown += Math.max(0.4, (100 - shown) * 0.2);
    paintProgress(shown, finished ? doneLabel : liveLabel);
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
      if (typeof job.percent === "number") {
        // Keep progress monotonic: never let a later poll pull the bar back down.
        target = Math.max(target, Math.min(94, job.percent));
      }
      if (job.message) liveLabel = job.message;
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
    clearBusyLabel(similarityButton);
    clearBusyLabel(offerHumanize);
    if (
      reportEmpty
      && reportBody
      && rewriteBody
      && reportBody.hidden
      && rewriteBody.hidden
      && (!similarityBody || similarityBody.hidden)
    ) {
      reportEmpty.hidden = false;
    }
    buttonsAvailable();
  }
}

async function assertPdfUploadAllowed() {
  try {
    const response = await fetch(appPath("/api/upload-quota"), { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!payload.allowed) {
      window.alert(payload.error || "PDF uploads are not available right now.");
      return false;
    }
    return true;
  } catch (error) {
    window.alert("Flyleaf could not check the upload allowance.");
    return false;
  }
}

if (draft) {
checkButton.addEventListener("click", async () => {
  if (selectedUpload() || (fileInput.files.length > 0 && words(draft.value) < 20)) {
    if (selectedUpload()) {
      if (!(await assertPdfUploadAllowed())) return;
    }
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
          window.alert(error.message || "That document could not be kept.");
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
  pasteMode = mode;
  const modeCheck = document.querySelector("#mode-check");
  const modeHumanize = document.querySelector("#mode-humanize");
  const modeSimilarity = document.querySelector("#mode-similarity");
  if (modeCheck) {
    modeCheck.classList.toggle("is-selected", mode === "check");
    modeCheck.setAttribute("aria-pressed", mode === "check" ? "true" : "false");
  }
  if (modeHumanize) {
    modeHumanize.classList.toggle("is-selected", mode === "humanize");
    modeHumanize.setAttribute("aria-pressed", mode === "humanize" ? "true" : "false");
  }
  if (modeSimilarity) {
    modeSimilarity.classList.toggle("is-selected", mode === "similarity");
    modeSimilarity.setAttribute("aria-pressed", mode === "similarity" ? "true" : "false");
  }
  if (checkButton) checkButton.hidden = mode !== "check";
  if (humanizeButton) humanizeButton.hidden = mode !== "humanize";
  if (similarityButton) similarityButton.hidden = mode !== "similarity";
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

async function startSimilarity(busyButton) {
  if (words(draft.value) < 40 && !(fileInput.files && fileInput.files.length)) {
    window.alert("Paste a short paragraph for a similarity check.");
    return;
  }
  if (selectedPdf() || (fileInput.files.length > 0 && words(draft.value) < 40)) {
    if (selectedPdf() || (fileInput.files[0] && fileInput.files[0].name.toLowerCase().endsWith(".pdf"))) {
      if (!(await assertPdfUploadAllowed())) return;
    }
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    const openPdfReport = selectedPdf();
    runJob(
      appPath("/api/plagiarism"),
      form,
      true,
      "Searching public pages",
      openPdfReport ? "Opening the report" : "Similarity ready",
      (result) => {
        if (!openPdfReport) {
          showSimilarity(result);
          return;
        }
        const chosen = fileInput.files[0];
        const openReview = () => {
          if (result.review_url) {
            const opened = window.open(appPath(result.review_url), "_blank");
            if (!opened) window.location = appPath(result.review_url);
            return;
          }
          showSimilarity(result);
        };
        if (chosen && result.review_id && document.body.dataset.signedIn === "1") {
          keepUpload(chosen.name, result).then(openReview).catch((error) => {
            window.alert(error.message || "That PDF could not be kept.");
          });
          return;
        }
        openReview();
      },
      busyButton,
    );
    return;
  }
  const textBody = new URLSearchParams();
  textBody.set("text", draft.value);
  runJob(
    appPath("/api/plagiarism"),
    textBody,
    true,
    "Searching public pages",
    "Similarity ready",
    showSimilarity,
    busyButton,
  );
}

if (similarityButton) {
  similarityButton.addEventListener("click", () => startSimilarity(similarityButton));
}

draft.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    const active = !checkButton.hidden
      ? checkButton
      : !humanizeButton.hidden
        ? humanizeButton
        : similarityButton;
    if (active && !active.disabled) active.click();
  }
});

const modeCheck = document.querySelector("#mode-check");
const modeHumanize = document.querySelector("#mode-humanize");
const modeSimilarity = document.querySelector("#mode-similarity");
if (modeCheck) modeCheck.addEventListener("click", () => setPasteMode("check"));
if (modeHumanize) modeHumanize.addEventListener("click", () => setPasteMode("humanize"));
if (modeSimilarity) modeSimilarity.addEventListener("click", () => setPasteMode("similarity"));

function modeFromHash() {
  const hash = (location.hash || "").replace(/^#/, "").toLowerCase();
  if (hash === "humanize") return "humanize";
  if (hash === "similarity" || hash === "plagiarism") return "similarity";
  if (hash === "check" || hash === "upload") return "check";
  return null;
}

function applyHashMode() {
  const mode = modeFromHash();
  if (mode) setPasteMode(mode);
}

applyHashMode();
window.addEventListener("hashchange", applyHashMode);

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
