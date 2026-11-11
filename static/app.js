// Simple, framework-free UI. All text is inserted with textContent (never innerHTML),
// so nothing from the server or the LLM can inject markup.
const SAMPLES = [
  "What is the recommended coolant concentration for the TX-200 CNC turning centre?",
  "The machine is showing alarm AL-104. What does it mean and what should the operator do?",
  "Who is allowed to remove a lockout lock from a machine?",
  "What is the outer diameter tolerance for the BH-220 bearing housing?",
  "How often should spindle runout be checked, and who does it?",
];
const CHIP_LABELS = ["Coolant concentration", "Alarm AL-104", "Remove a lockout lock", "BH-220 OD tolerance", "Spindle runout"];

const form = document.getElementById("ask-form");
const input = document.getElementById("question");
const button = document.getElementById("ask-button");
const result = document.getElementById("result");
let lastQuestion = "";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}


// Highlight the question's words inside the evidence text (DOM nodes only, no innerHTML).
function highlightedText(text, terms) {
  const usable = (terms || []).filter((t) => t.length >= 3).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const fragment = document.createDocumentFragment();
  if (!usable.length) { fragment.append(text); return fragment; }
  const pattern = new RegExp("\\b(?:" + usable.join("|") + ")[\\w-]*", "gi");
  let last = 0, match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) fragment.append(text.slice(last, match.index));
    fragment.append(el("mark", "", match[0]));
    last = match.index + match[0].length;
    if (match[0].length === 0) pattern.lastIndex++;
  }
  if (last < text.length) fragment.append(text.slice(last));
  return fragment;
}

// Example chips: tap to fill and ask.
const chips = document.getElementById("chips");
SAMPLES.forEach((question, i) => {
  const chip = el("button", "chip", CHIP_LABELS[i]);
  chip.type = "button";
  chip.addEventListener("click", () => { input.value = question; ask(question); });
  chips.appendChild(chip);
});

form.addEventListener("submit", (event) => { event.preventDefault(); ask(input.value); });
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(input.value); }
});

const BADGES = {
  answered: "Answer from the documents",
  evidence_only: "Relevant passages (no generated answer)",
  not_found: "Not found in the provided documents",
  needs_detail: "More detail needed",
  error: "Something went wrong",
};

async function ask(rawQuestion) {
  const question = (rawQuestion || "").trim();
  result.replaceChildren();
  if (!question) {
    const card = el("div", "card");
    card.append(el("p", "message", "Please type a question first."));
    result.append(card);
    input.focus();
    return;
  }
  lastQuestion = question;
  button.disabled = true;
  button.textContent = "Searching documents…";
  result.setAttribute("aria-busy", "true");

  try {
    // Relative URL, so it works from a phone at http://<laptop-ip>:8000 as well as on localhost.
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    let data = null;
    try { data = await response.json(); } catch (_) { /* not JSON */ }
    if (!response.ok || !data) {
      renderError((data && data.message) || `The server replied with an error (HTTP ${response.status}).`);
    } else {
      render(data);
    }
  } catch (_) {
    renderError("Could not reach the copilot. Check that you are on the same Wi-Fi as the laptop, then try again.");
  } finally {
    button.disabled = false;
    button.textContent = "Ask";
    result.removeAttribute("aria-busy");
  }
}

function renderError(message) {
  result.replaceChildren();
  const card = el("div", "card");
  card.append(el("span", "badge error", BADGES.error), el("p", "message", message));
  const retry = el("button", "retry", "Try again");
  retry.type = "button";
  retry.addEventListener("click", () => ask(lastQuestion));
  card.append(retry);
  result.append(card);
}

function banner(kind, title, text) {
  const box = el("div", `banner ${kind}`);
  box.append(el("strong", "", title), el("span", "", text));
  return box;
}

function sourceBlock(source, openByDefault, terms) {
  const details = el("details", "source");
  details.open = openByDefault;
  const status = source.revision_status === "newest_supplied" ? "newest supplied" : "superseded";
  const summary = el("summary", "", `[${source.ref}] ${source.doc_no} · ${source.revision_label}`);
  summary.append(el("small", "", `${status} · page ${source.page} · ${source.section}`));
  const body = el("div", "source-body");
  body.append(
    el("p", "meta", `Applies to: ${source.scope || "not stated"}`),
    el("p", "meta", `${source.title} · effective ${source.effective_date || "date not stated"} · ${source.filename}`),
  );
  const evidence = el("pre", "evidence");
  evidence.append(highlightedText(source.evidence, terms));
  body.append(evidence);
  details.append(summary, body);
  return details;
}

function render(data) {
  result.replaceChildren();

  const main = el("div", "card");
  main.append(el("span", `badge ${data.status}`, BADGES[data.status] || data.status));
  if (data.status === "answered") main.append(el("p", "answer", data.answer));
  if (data.message) main.append(el("p", "message", data.message));
  result.append(main);

  if (data.safety_note) result.append(banner("safety", "Safety procedure", data.safety_note));
  if (data.revision_note) result.append(banner("revision", "Revision note", data.revision_note));

  const cited = data.sources.filter((s) => s.cited);
  const others = data.sources.filter((s) => !s.cited);
  const showOpen = (s) => data.status === "evidence_only" || s.safety_critical;

  if (cited.length) {
    result.append(el("h2", "group", "Source"));
    cited.forEach((s, i) => result.append(sourceBlock(s, showOpen(s, i), data.highlights)));
  }
  if (others.length) {
    const heading = data.status === "evidence_only" ? "Relevant passages" : "Also check (same document)";
    result.append(el("h2", "group", heading));
    others.forEach((s, i) => result.append(sourceBlock(s, showOpen(s, i), data.highlights)));
  }
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}
