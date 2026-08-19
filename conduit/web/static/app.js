/* Conduit demo — renders the MCP loop as a rail of tool calls.
 *
 * Two sources, one renderer: recorded transcripts (static JSON, captured by
 * scripts/record_transcripts.py) and live turns (SSE from /api/ask). Both
 * produce the same step objects, so drawStep() does not care which it got.
 *
 * The API may live on a different origin than this page — the deployed setup
 * puts the static files on a CDN so they paint while the API instance wakes.
 * Set that origin in <body data-api="https://...">.
 */

const API = document.body.dataset.api || "";
const REPO = "https://github.com/krishivsaini/Conduit";

const el = {
  chips: document.getElementById("tool-chips"),
  presets: document.getElementById("presets"),
  trace: document.getElementById("trace"),
  badge: document.getElementById("stage-badge"),
  form: document.getElementById("freeform"),
  input: document.getElementById("q"),
  button: document.getElementById("ask-btn"),
  btnMeta: document.getElementById("btn-meta"),
  note: document.getElementById("freeform-note"),
  footerMeta: document.getElementById("footer-meta"),
};

let running = false;

/* --- Naming the boundary -------------------------------------------------
 * A refusal is only meaningful if the page says which guarantee fired. The
 * server's actionable errors carry that in their text; map it to the test
 * that proves it. */
const BOUNDARIES = [
  {
    match: /deny-list|denylist|excluded/i,
    title: "Stopped — secrets deny-list",
    proof: "tests/test_security_denylist.py",
    file: "tests/test_security_denylist.py",
  },
  {
    match: /outside the repo root|escape|traversal/i,
    title: "Stopped — repo-root confinement",
    proof: "tests/test_security_traversal.py",
    file: "tests/test_security_traversal.py",
  },
];

function classify(text) {
  for (const b of BOUNDARIES) if (b.match.test(text)) return b;
  return { title: "Refused by the server", proof: "the server's tests", file: "tests" };
}

/* --- Small DOM helpers --------------------------------------------------- */

function h(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function formatArgs(args) {
  const frag = document.createDocumentFragment();
  const keys = Object.keys(args || {});
  keys.forEach((k, i) => {
    frag.append(h("span", "arg-k", `${k}=`));
    frag.append(h("span", "arg-v", JSON.stringify(args[k])));
    if (i < keys.length - 1) frag.append(document.createTextNode(", "));
  });
  return frag;
}

/* Tool results are JSON blobs; show them readably without pretending they
 * are anything other than what the model received. */
function prettyResult(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

/* --- Rendering ----------------------------------------------------------- */

function resetTrace(question, kind) {
  el.trace.textContent = "";
  el.badge.hidden = false;
  el.badge.dataset.kind = kind;
  el.badge.textContent = kind === "live" ? "live run" : "recorded run";

  el.trace.append(h("p", "question", question));
  const rail = h("ol", "rail");
  rail.id = "rail";
  el.trace.append(rail);
  return rail;
}

function drawStep(rail, step, n) {
  const li = h("li", `step${step.is_error ? " step-refused" : ""}`);

  const head = h("div", "step-head");
  head.append(h("span", "step-n", String(n).padStart(2, "0")));
  const call = h("span", "step-call");
  call.append(document.createTextNode(`${step.name}(`));
  call.append(formatArgs(step.arguments));
  call.append(document.createTextNode(")"));
  head.append(call);
  if (!step.is_error) head.append(h("span", "step-status", "returned"));
  li.append(head);

  const body = h("div", "step-body");
  if (step.is_error) {
    body.append(barrier(step.result_text));
  } else {
    const pre = h("pre", "step-out", prettyResult(step.result_text));
    pre.hidden = true;
    const toggle = h("button", "step-toggle", "Show what the server returned");
    toggle.type = "button";
    toggle.addEventListener("click", () => {
      pre.hidden = !pre.hidden;
      toggle.textContent = pre.hidden
        ? "Show what the server returned"
        : "Hide what the server returned";
    });
    body.append(toggle, pre);
  }
  li.append(body);
  rail.append(li);

  if (step.is_error) rail.classList.add("is-severed");
  return li;
}

/* The signature element: the conduit visibly cut at the boundary. */
function barrier(text) {
  const kind = classify(text);
  const box = h("div", "barrier");
  box.append(h("div", "barrier-bar"));

  const body = h("div", "barrier-body");
  body.append(h("p", "barrier-title", kind.title));
  body.append(h("p", "barrier-detail", text.replace(/^Error executing tool \w+:\s*/, "")));

  const proof = h("p", "barrier-proof");
  const link = h("a", null, `Proven by ${kind.proof} →`);
  link.href = `${REPO}/blob/main/${kind.file}`;
  proof.append(link);
  body.append(proof);

  box.append(body);
  return box;
}

function drawAnswer(text, meta) {
  const wrap = h("div", "answer");
  wrap.append(h("p", "answer-label", "Answer"));
  wrap.append(h("p", "answer-text", text));
  if (meta) wrap.append(meta);
  el.trace.append(wrap);
  return wrap;
}

function working(label) {
  const box = h("div", "working");
  box.append(h("span", "working-dot"));
  box.append(h("span", null, label));
  return box;
}

function notice(message) {
  const box = h("p", "notice", message);
  el.trace.append(box);
  return box;
}

/* --- Recorded playback ---------------------------------------------------
 * Replayed with the same staggered arrival as a live run, because the pacing
 * is what makes the loop legible. Instant when motion is reduced. */

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));

async function playRecorded(t) {
  const rail = resetTrace(t.question, "recorded");
  for (let i = 0; i < t.steps.length; i++) {
    await wait(i === 0 ? 220 : 480);
    drawStep(rail, t.steps[i], i + 1);
  }
  await wait(420);

  const meta = h("p", "answer-check");
  const verdict = t.correct ? "matches" : "does not match";
  meta.append(document.createTextNode("Expected "));
  meta.append(h("b", null, t.expected));
  meta.append(document.createTextNode(` — ${verdict} the verified answer in `));
  const link = h("a", null, "eval/evaluation.xml");
  link.href = `${REPO}/blob/main/eval/evaluation.xml`;
  meta.append(link);
  meta.append(document.createTextNode(`. Recorded ${t.recorded} with ${t.model}.`));
  drawAnswer(t.answer, meta);
}

/* --- Live turn ----------------------------------------------------------- */

async function runLive(question) {
  const rail = resetTrace(question, "live");
  const spinner = working("asking the model");
  el.trace.append(spinner);

  let n = 0;
  let answered = false;
  try {
    const res = await fetch(`${API}/api/ask?q=${encodeURIComponent(question)}`, {
      headers: { Accept: "text/event-stream" },
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      spinner.remove();
      notice(body.error || `The demo API returned ${res.status}.`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let split;
      while ((split = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);

        let event = "message";
        let data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        const payload = JSON.parse(data);

        if (event === "step") {
          spinner.remove();
          drawStep(rail, payload, ++n);
          el.trace.append(spinner);
        } else if (event === "answer") {
          spinner.remove();
          answered = true;
          drawAnswer(
            payload.text,
            payload.hit_step_limit
              ? h("p", "answer-check", "The loop hit its step budget before finishing.")
              : null
          );
        } else if (event === "error") {
          spinner.remove();
          notice(payload.message);
          return;
        }
      }
    }
    if (!answered) notice("The stream ended before an answer arrived.");
  } catch (err) {
    notice(`Could not reach the demo API: ${err.message}`);
  } finally {
    spinner.remove();
  }
}

/* --- Wiring -------------------------------------------------------------- */

function setBusy(busy) {
  running = busy;
  el.button.disabled = busy;
  el.button.querySelector(".btn-label").textContent = busy ? "Running…" : "Run it live";
  document.querySelectorAll(".preset").forEach((b) => (b.disabled = busy));
}

function selectPreset(button) {
  document.querySelectorAll(".preset").forEach((b) => b.setAttribute("aria-pressed", "false"));
  if (button) button.setAttribute("aria-pressed", "true");
}

async function loadTranscripts() {
  let data;
  try {
    const res = await fetch("transcripts.json", { cache: "no-cache" });
    data = await res.json();
  } catch {
    el.presets.append(h("li", "preset-caption", "Recorded runs are unavailable."));
    return;
  }

  data.transcripts.forEach((t) => {
    const li = document.createElement("li");
    const button = h("button", `preset${t.index === 12 ? " preset-security" : ""}`);
    button.type = "button";
    button.setAttribute("aria-pressed", "false");
    button.append(h("span", "preset-tag", t.index === 12 ? "the boundary" : `${t.steps.length} tool calls`));
    button.append(h("span", "preset-caption", t.caption || t.question));
    button.addEventListener("click", async () => {
      if (running) return;
      setBusy(true);
      selectPreset(button);
      await playRecorded(t);
      setBusy(false);
    });
    li.append(button);
    el.presets.append(li);
  });

  el.footerMeta.textContent =
    `Recorded runs captured ${data.recorded} against ${data.repo} — real host output, replayed.`;
}

async function loadTools() {
  try {
    const res = await fetch(`${API}/api/tools`);
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    el.chips.textContent = "";
    data.tools.forEach((t) => {
      const chip = h("li", "chip", t.name);
      if (t.description) chip.title = t.description;
      el.chips.append(chip);
    });
    data.resources.forEach((r) => el.chips.append(h("li", "chip chip-resource", r.uri)));
  } catch {
    // The API sleeps on a free tier; the recorded path does not need it.
    el.chips.textContent = "";
    const known = ["read_file", "search_code", "list_symbols", "diff"];
    known.forEach((n) => el.chips.append(h("li", "chip chip-offline", n)));
    el.chips.append(h("li", "chip chip-offline", "server asleep — names from the last recording"));
    el.btnMeta.textContent = "server may take ~30s to wake";
    el.note.classList.add("is-warning");
    el.note.textContent =
      "The demo API is asleep. A live question will wake it, which takes about 30 seconds. Recorded runs work now.";
  }
}

el.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = el.input.value.trim();
  if (!question || running) return;
  setBusy(true);
  selectPreset(null);
  await runLive(question);
  setBusy(false);
});

loadTranscripts();
loadTools();
