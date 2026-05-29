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

  const rows = (data.models || []).map((m, i) => `
    <tr>
      <td><span class="rank">${i + 1}.</span> <span class="model">${esc(m.model)}</span></td>
      <td class="num">${bar(m.pass_at_1)}${pct(m.pass_at_1)}</td>
      <td class="num">${pct(m.pass_at_3)}</td>
      <td class="num">${money(m.mean_cost_usd)}</td>
      <td class="num">${fmt(m.mean_tokens)}</td>
      <td class="num">${fmt(m.mean_wall_s, 1)}s</td>
      <td class="num">${m.n_runs}</td>
      <td class="model muted">${esc(m.scaffold_version)}</td>
    </tr>`).join("");

  el.innerHTML = `
    <table class="board" aria-label="leaderboard">
      <thead><tr>
        <th>Model</th><th>pass@1</th><th>pass@3</th><th>$/task</th>
        <th>tokens/task</th><th>wall/task</th><th>runs</th><th>scaffold</th>
      </tr></thead>
      <tbody>${rows || `<tr><td colspan="8" class="muted">No runs yet.</td></tr>`}</tbody>
    </table>
    <p class="small muted">Golden set: ${data.n_tasks} intrinsically-verifiable tasks ·
      snapshot ${new Date(data.generated_at).toISOString().slice(0, 16).replace("T", " ")} UTC ·
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
      <td class="model">${esc(r.task_id)}</td>
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
      <thead><tr><th>Task</th><th>Model</th><th>Result</th><th>F2P</th><th>P2P</th>
        <th>tokens</th><th>wall</th><th>trace</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="8" class="muted">No runs yet.</td></tr>`}</tbody>
    </table>`;
}

document.addEventListener("DOMContentLoaded", () => {
  const lb = document.getElementById("leaderboard");
  if (lb) renderLeaderboard(lb);
  const rt = document.getElementById("runs");
  if (rt) renderRuns(rt);
});
