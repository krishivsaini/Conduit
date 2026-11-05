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

// data-api points the *deployed* static page at the separately hosted API.
// When the page comes from localhost it is being served by `conduit-web`
// itself, which hosts the API on the same origin — use that, not production.
const IS_LOCAL = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
const API = IS_LOCAL ? "" : document.body.dataset.api || "";
const REPO = "https://github.com/krishivsaini/Conduit";

/* --- Which repository the server is pointed at -----------------------------
 * The page always says what it is serving, so an answer can be checked
 * against the code it came from. The sample repo is what the live API serves;
 * Conduit itself is shown through runs recorded against one pinned commit. */
const REPOS = {
  sample: {
    transcripts: "transcripts.json",
    name: "sample-repo/",
    detail: () =>
      "A three-file fictional billing service (auth, payments, utils), with intentionally " +
      "fake secrets (.env, service.key) for the deny-list to refuse.",
    link: () => `${REPO}/tree/main/sample-repo`,
    evalFile: "eval/evaluation.xml",
    placeholder: "What does the charge function do when the amount is too low?",
  },
  conduit: {
    transcripts: "transcripts.conduit.json",
    name: "Conduit, this project's own repository",
    detail: (data) =>
      `The real codebase, ${data.files} files. Recorded runs are pinned at commit ` +
      `${data.commit.slice(0, 7)} (tracked files only); ${data.deny.join(", ")} is denied, so ` +
      "the eval answer key can't be read.",
    link: (data) => `${REPO}/tree/${data.commit}`,
    evalFile: "eval/evaluation.conduit.xml",
    placeholder: "Where does the server decide which files it won't serve?",
  },
};
let currentRepo = "sample";
// Which repos the live API serves, and at which commit; filled in by /api/tools.
let liveRepos = null;

/* Say where a live question goes, for the selected repo. */
function describeLive() {
  const live = liveRepos && liveRepos[currentRepo];
  el.input.placeholder = REPOS[currentRepo].placeholder;
  if (liveRepos && !live) {
    el.note.textContent = "This deployment doesn't serve this repo live; its recorded runs above still work.";
    el.button.disabled = true;
    return;
  }
  el.button.disabled = running;
  const at = live && live.commit ? ` at commit ${live.commit.slice(0, 7)}` : "";
  const what = currentRepo === "sample" ? "the sample repo" : `Conduit${at}`;
  el.note.textContent = `Live runs ask ${what}, and are rate limited. Recorded runs never are.`;
}

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
  wake: document.getElementById("wake"),
  wakeText: document.getElementById("wake-text"),
  servingName: document.getElementById("serving-name"),
  servingDetail: document.getElementById("serving-detail"),
  servingLink: document.getElementById("serving-link"),
  repoTabs: document.querySelectorAll(".repo-tab"),
};

let running = false;
let apiAwake = false;

/* --- Naming the boundary -------------------------------------------------
 * A refusal is only meaningful if the page says which guarantee fired. The
 * server's actionable errors carry that in their text; map it to the test
 * that proves it. */
const BOUNDARIES = [
  {
    match: /deny-list|denylist|excluded/i,
    title: "Stopped — secrets deny-list",
    security: true,
    proof: "tests/test_security_denylist.py",
    file: "tests/test_security_denylist.py",
  },
  {
    match: /outside the repo root|escape|traversal/i,
    title: "Stopped — repo-root confinement",
    security: true,
    proof: "tests/test_security_traversal.py",
    file: "tests/test_security_traversal.py",
  },
  {
    match: /is not served/i,
    title: "Stopped — the repo's own exclusions (.gitignore)",
    security: true,
    proof: "tests/test_real_repo.py",
    file: "tests/test_real_repo.py",
  },
  {
    // Not a boundary: the call named an argument the tool doesn't take, and
    // the server answered with the right names so the model can retry.
    match: /does not take|should be|is required/i,
    title: "Sent back — wrong argument, with the right names",
    security: false,
    proof: "tests/test_tools.py",
    file: "tests/test_tools.py",
  },
];

function classify(text) {
  for (const b of BOUNDARIES) if (b.match.test(text)) return b;
  return { title: "Refused by the server", security: true, proof: "the server's tests", file: "tests" };
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
  revealTrace();
  return rail;
}

/* On a phone the trace stacks below the presets and the form, so a tapped
 * question would play entirely off-screen and look like nothing happened. On a
 * short desktop viewport the same is true of everything below the fold. Scroll
 * only when the trace is not already comfortably in view. */
function revealTrace() {
  const stage = el.trace.closest(".stage");
  const top = stage.getBoundingClientRect().top;
  // Leave it alone if at least ~40% of the viewport is already free below it.
  if (top < 0 || top > window.innerHeight * 0.6) {
    stage.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }
}

function drawStep(rail, step, n) {
  const kind = step.is_error ? classify(step.result_text) : null;
  const state = kind ? (kind.security ? " step-refused" : " step-corrected") : "";
  const li = h("li", `step${state}`);

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
    pre.id = `step-out-${n}`;
    const toggle = h("button", "step-toggle", "Show what the server returned");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", pre.id);
    toggle.addEventListener("click", () => {
      pre.hidden = !pre.hidden;
      toggle.setAttribute("aria-expanded", String(!pre.hidden));
      toggle.textContent = pre.hidden
        ? "Show what the server returned"
        : "Hide what the server returned";
    });
    body.append(toggle, pre);
  }
  li.append(body);
  rail.append(li);

  if (kind && kind.security) rail.classList.add("is-severed");
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

/* Recorded runs end with an "ANSWER: <value>" line because the eval grades
 * it. Show the reply once: drop that line, and keep the value only if the
 * prose doesn't already say it. (The recording itself stays byte-exact; CI
 * replays it.) */
function displayAnswer(text) {
  const lines = text.trim().split("\n");
  const last = lines.length - 1 - [...lines].reverse().findIndex((l) => /^[\s>*_]*answer[*_]*\s*:/i.test(l));
  if (last >= lines.length) return text.trim();
  const value = lines[last].replace(/^[\s>*_]*answer[*_]*\s*:\s*/i, "").replace(/^[*_`]+|[*_`]+$/g, "").trim();
  const prose = lines.filter((_, i) => i !== last).join("\n").trim();
  if (!prose) return value;
  return prose.toLowerCase().includes(value.toLowerCase()) ? prose : `${prose}\n\n${value}`;
}

/* Models answer in Markdown. Render **bold** and `code` as elements built from
 * text nodes. Never innerHTML: an answer can quote the repository, and a
 * repository can contain text written to attack whoever displays it. */
function renderInline(text) {
  const frag = document.createDocumentFragment();
  for (const part of text.split(/(\*\*[^*\n]+?\*\*|`[^`\n]+`)/)) {
    if (!part) continue;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      const strong = document.createElement("strong");
      strong.append(renderInline(part.slice(2, -2)));
      frag.append(strong);
    } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      frag.append(h("code", null, part.slice(1, -1)));
    } else {
      frag.append(document.createTextNode(part));
    }
  }
  return frag;
}

function drawAnswer(text, meta) {
  const wrap = h("div", "answer");
  wrap.append(h("p", "answer-label", "Answer"));
  const body = h("p", "answer-text");
  body.append(renderInline(displayAnswer(text)));
  wrap.append(body);
  if (meta) wrap.append(meta);
  el.trace.append(wrap);
  return wrap;
}

/* An off-topic question is declined by design, not failed: say so plainly,
 * in the same voice as a security refusal. */
function drawDeclined(reason) {
  const box = h("div", "declined");
  box.append(h("p", "declined-title", "Declined: not about this repository"));
  box.append(h("p", "declined-reason", reason));
  box.append(h("p", "declined-hint",
    "This demo answers questions about the repository it serves. Try one of the preset questions."));
  el.trace.append(box);
  return box;
}

function working(label) {
  const box = h("div", "working");
  box.append(h("span", "working-dot"));
  box.append(h("span", "working-label", label));
  box.setLabel = (next) => {
    box.querySelector(".working-label").textContent = next;
  };
  return box;
}

function notice(message) {
  const box = h("p", "notice", message);
  el.trace.append(box);
  return box;
}

/* --- Cold start ----------------------------------------------------------
 * The API sleeps on a free instance. A cold request does not fail — it hangs
 * for ~30-60s while the container boots, then succeeds. Left unexplained that
 * looks like a broken page, so name the cause and show a running clock. The
 * wait is the host booting, not the MCP server. */

const COLD_AFTER_MS = 2500;

/* One boot, one clock. A live question asked while the tool list is still
 * waking the server waits on the same boot; a second watch would drive the
 * same banner from a second t0 and the seconds would flicker between two. */
let wakeWatch = null;

function coldStartWatch() {
  if (wakeWatch) return wakeWatch;
  const t0 = Date.now();
  let ticker = null;

  const render = () => {
    const s = Math.round((Date.now() - t0) / 1000);
    el.wakeText.textContent = "";
    el.wakeText.append(h("b", null, `Waking the demo server — ${s}s.`));
    el.wakeText.append(
      document.createTextNode(
        " The API sleeps on a free Render instance and cold-starts on the first" +
        " request, usually 30–60s. This wait is the host booting, not the MCP" +
        " server: once it is up, tool calls return in milliseconds. The recorded" +
        " runs need no server and play instantly."
      )
    );
  };

  const armed = setTimeout(() => {
    el.wake.hidden = false;
    el.wake.dataset.state = "waking";
    render();
    ticker = setInterval(render, 1000);
  }, COLD_AFTER_MS);

  wakeWatch = {
    settle(ok) {
      if (wakeWatch !== this) return;       // already settled by another request
      wakeWatch = null;
      clearTimeout(armed);
      if (ticker) clearInterval(ticker);
      const ms = Date.now() - t0;
      if (el.wake.hidden) return ms;          // woke fast; never announced it
      if (!ok) { el.wake.hidden = true; return ms; }
      el.wake.dataset.state = "awake";
      el.wakeText.textContent = "";
      el.wakeText.append(h("b", null, `Server awake — cold start took ${(ms / 1000).toFixed(1)}s.`));
      el.wakeText.append(
        document.createTextNode(" Tool calls from here are immediate.")
      );
      setTimeout(() => { el.wake.hidden = true; }, 10000);
      return ms;
    },
  };
  return wakeWatch;
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
  const evalFile = REPOS[currentRepo].evalFile;
  const link = h("a", null, evalFile);
  link.href = `${REPO}/blob/main/${evalFile}`;
  meta.append(link);
  meta.append(document.createTextNode(`. Recorded ${t.recorded} with ${t.model}.`));
  drawAnswer(t.answer, meta);
}

/* --- Live turn ----------------------------------------------------------- */

async function runLive(question) {
  const rail = resetTrace(question, "live");
  const spinner = working(
    apiAwake ? "asking the model" : "waking the server — first request takes 30–60s"
  );
  el.trace.append(spinner);
  const watch = apiAwake ? null : coldStartWatch();

  let n = 0;
  let answered = false;
  try {
    const res = await fetch(`${API}/api/ask?q=${encodeURIComponent(question)}&repo=${currentRepo}`, {
      headers: { Accept: "text/event-stream" },
    });

    apiAwake = true;
    if (watch) watch.settle(true);
    spinner.setLabel("asking the model");

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
          if (payload.declined) {
            drawDeclined(payload.declined);
            continue;
          }
          drawAnswer(
            payload.text,
            payload.hit_step_limit
              ? h("p", "answer-check",
                  "The loop spent its full tool budget, then answered from the evidence it had.")
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
    if (watch) watch.settle(false);
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
  el.repoTabs.forEach((tab) => (tab.disabled = busy));
  if (!busy) describeLive();
}

function selectPreset(button) {
  document.querySelectorAll(".preset").forEach((b) => b.setAttribute("aria-pressed", "false"));
  if (button) button.setAttribute("aria-pressed", "true");
}

const transcriptCache = {};

async function loadTranscripts(repo) {
  const conf = REPOS[repo];
  el.presets.textContent = "";
  let data = transcriptCache[repo];
  if (!data) {
    try {
      const res = await fetch(conf.transcripts, { cache: "no-cache" });
      data = transcriptCache[repo] = await res.json();
    } catch {
      el.presets.append(h("li", "preset-caption", "Recorded runs are unavailable."));
      return;
    }
  }
  if (repo !== currentRepo) return; // the visitor switched while this loaded

  el.servingName.textContent = conf.name;
  el.servingDetail.textContent = conf.detail(data);
  el.servingLink.href = conf.link(data);

  data.transcripts.forEach((t) => {
    // A run where the server turned something down is the boundary preset.
    const refused = t.steps.some((s) => s.is_error && classify(s.result_text).security);
    const li = document.createElement("li");
    const button = h("button", `preset${refused ? " preset-security" : ""}`);
    button.type = "button";
    button.setAttribute("aria-pressed", "false");
    button.append(h("span", "preset-tag", refused ? "the boundary" : `${t.steps.length} tool calls`));
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

  const where = data.commit ? `${data.repo} at ${data.commit.slice(0, 7)}` : data.repo;
  el.footerMeta.textContent =
    `Recorded runs captured ${data.recorded} against ${where} — real host output, replayed.`;
}

function selectRepo(repo) {
  if (running || !REPOS[repo]) return;
  currentRepo = repo;
  el.repoTabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.repo === repo)));
  loadTranscripts(repo);
  describeLive();
}

el.repoTabs.forEach((tab) => tab.addEventListener("click", () => selectRepo(tab.dataset.repo)));

async function loadTools() {
  const watch = coldStartWatch();
  try {
    const res = await fetch(`${API}/api/tools`);
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    apiAwake = true;
    watch.settle(true);
    liveRepos = Object.fromEntries((data.repos || [{ id: "sample" }]).map((r) => [r.id, r]));
    describeLive();
    el.chips.textContent = "";
    data.tools.forEach((t) => {
      const chip = h("li", "chip", t.name);
      if (t.description) chip.title = t.description;
      el.chips.append(chip);
    });
    data.resources.forEach((r) => el.chips.append(h("li", "chip chip-resource", r.uri)));
  } catch {
    // The API sleeps on a free tier; the recorded path does not need it.
    watch.settle(false);
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

el.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    el.form.requestSubmit();
  }
});

el.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = el.input.value.trim();
  if (running) return;
  if (!question) {
    el.input.focus();                       // an empty submit should land somewhere
    return;
  }
  setBusy(true);
  selectPreset(null);
  await runLive(question);
  setBusy(false);
});

loadTranscripts(currentRepo);
loadTools();
