// ForgeJudge dashboard — renders the leaderboard + per-run pages from static
// JSON snapshots (data/leaderboard.json, data/runs.json) exported from Neon.

async function getJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

const pct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
const money = (x) => "$" + (x ?? 0).toFixed(4);
const fmt = (x, d = 0) => (x == null ? "—" : Number(x).toFixed(d));
// Escape data into HTML text context (data is our own, but escape anyway).
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Only allow http(s) links (never javascript: etc.).
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");

function bar(frac) {
  const w = Math.round((frac || 0) * 90);
  return `<span class="barwrap"><span class="bar" style="width:${w}px"></span></span>`;
}

async function renderLeaderboard(el) {
  let data;
  try { data = await getJSON("data/leaderboard.json"); }
  catch { el.innerHTML = `<p class="muted">Leaderboard data not available yet.</p>`; return; }

  const models = data.models || [];
  // pass@k is "any seed for a task resolves" — k = the number of seeds actually
  // swept (db.py emits n_seeds). Label it honestly so a non-default sweep (e.g.
  // 2 or 5 seeds) is not mislabeled "pass@3" (finding #39). Field renamed from
  // pass_at_3 → pass_at_k upstream; fall back to the old name for stale snapshots.
  const seeds = models.length ? Number(models[0].n_seeds) : 0;
  const passKLabel = Number.isFinite(seeds) && seeds > 0 ? `pass@${seeds}` : "pass@k";
  const passK = (m) => (m.pass_at_k ?? m.pass_at_3);

  const rows = models.map((m, i) => `
    <tr>
      <th scope="row"><span class="rank">${i + 1}.</span> <span class="model">${esc(m.model)}</span></th>
      <td class="num">${bar(m.pass_at_1)}${pct(m.pass_at_1)}</td>
      <td class="num">${pct(passK(m))}</td>
      <td class="num">${money(m.mean_cost_usd)}</td>
      <td class="num">${fmt(m.mean_tokens)}</td>
      <td class="num">${fmt(m.mean_wall_s, 1)}s</td>
      <td class="num">${m.n_runs}</td>
      <td class="model muted">${esc(m.scaffold_version)}</td>
    </tr>`).join("");

  // Defensive timestamp: generated_at is already an ISO-8601 UTC string from the
  // exporter, so slice it after a validity guard rather than re-parsing — a bad
  // or missing value must not throw and blank the whole table (finding #29).
  const d = new Date(data.generated_at);
  const snap = data.generated_at && !isNaN(d)
    ? String(data.generated_at).slice(0, 16).replace("T", " ")
    : "—";

  el.innerHTML = `
    <table class="board" aria-label="leaderboard">
      <caption style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap">Model leaderboard: resolve rates, per-task cost, tokens and latency.</caption>
      <thead><tr>
        <th scope="col">Model</th><th scope="col">pass@1</th><th scope="col">${passKLabel}</th>
        <th scope="col">$/task</th><th scope="col">tokens/task</th><th scope="col">wall/task</th>
        <th scope="col">runs</th><th scope="col">scaffold</th>
      </tr></thead>
      <tbody>${rows || `<tr><td colspan="8" class="muted">No runs yet.</td></tr>`}</tbody>
    </table>
    <p class="small muted">Golden set: ${data.n_tasks} intrinsically-verifiable tasks ·
      snapshot ${snap} UTC ·
      same harness, model swapped — score reflects the model, not a tuned scaffold.</p>`;
}

async function renderRuns(el) {
  let data;
  try { data = await getJSON("data/runs.json"); }
  catch { el.innerHTML = `<p class="muted">Run data not available yet.</p>`; return; }
  const runs = data.runs || [];
  const rows = runs.map((r) => {
    const url = safeUrl(r.trace_url);
    return `
    <tr>
      <th scope="row" class="model">${esc(r.task_id)}</th>
      <td class="model muted">${esc(r.model)}</td>
      <td>${r.resolved ? '<span class="badge pass">RESOLVED</span>' : '<span class="badge fail">unsolved</span>'}</td>
      <td class="num">${r.f2p_passed}/${r.f2p_total}</td>
      <td class="num">${r.p2p_passed}/${r.p2p_total}</td>
      <td class="num">${fmt(r.tokens_in + r.tokens_out)}</td>
      <td class="num">${fmt(r.wall_clock_s, 1)}s</td>
      <td>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">trace ↗</a>` : "—"}</td>
    </tr>`; }).join("");
  el.innerHTML = `
    <table class="board" aria-label="runs">
      <caption style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap">Per-run results: each task attempt, result, tests passed, tokens, latency and trace.</caption>
      <thead><tr><th scope="col">Task</th><th scope="col">Model</th><th scope="col">Result</th>
        <th scope="col">F2P</th><th scope="col">P2P</th><th scope="col">tokens</th>
        <th scope="col">wall</th><th scope="col">trace</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="8" class="muted">No runs yet.</td></tr>`}</tbody>
    </table>`;
}

document.addEventListener("DOMContentLoaded", () => {
  const lb = document.getElementById("leaderboard");
  if (lb) renderLeaderboard(lb);
  const rt = document.getElementById("runs");
  if (rt) renderRuns(rt);
});
