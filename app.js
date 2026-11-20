// Browse Bleau — flip through beta videos for a sector + grade range.
// State lives in the URL hash so a view can be bookmarked or shared:
//   #area=canard&min=6a&max=7a&i=3

const GRADES = [
  "1", "2", "3", "3+", "4", "4+", "5", "5+",
  "6a", "6a+", "6b", "6b+", "6c", "6c+",
  "7a", "7a+", "7b", "7b+", "7c", "7c+",
  "8a", "8a+", "8b", "8b+", "8c", "8c+", "9a",
];

// Must match grade_value() in scraper/scrape.py
function gradeValue(g) {
  const m = /^([1-9])([abc])?(\+)?(-)?$/i.exec((g || "").trim());
  if (!m) return null;
  let v = Number(m[1]) * 6;
  if (m[2]) v += "abc".indexOf(m[2].toLowerCase()) * 2;
  if (m[3]) v += 1;
  if (m[4]) v -= 0.5;
  return v;
}

const $ = (id) => document.getElementById(id);
const els = {
  area: $("area"), gmin: $("gmin"), gmax: $("gmax"), count: $("count"),
  player: $("player"), info: $("info"), list: $("list"), pos: $("pos"),
  prev: $("prev"), next: $("next"),
  videoNav: $("video-nav"), vprev: $("vprev"), vnext: $("vnext"), vlabel: $("vlabel"),
};

const state = { area: null, min: "6a", max: "7a", i: 0, v: 0 };
let areaData = null;   // full JSON for the current area
let filtered = [];     // boulders in grade range, ranked by ascents
const cache = new Map();

// ---------------------------------------------------------------- hash state
function readHash() {
  // keep literal "+" in grades like 6a+ (URLSearchParams would decode it as a space)
  const p = new URLSearchParams(location.hash.slice(1).replace(/\+/g, "%2B"));
  if (p.get("area")) state.area = p.get("area");
  if (p.get("min")) state.min = p.get("min");
  if (p.get("max")) state.max = p.get("max");
  if (!GRADES.includes(state.min)) state.min = "6a";
  if (!GRADES.includes(state.max)) state.max = "7a";
  state.i = Number(p.get("i")) || 0;
}
function writeHash() {
  const p = new URLSearchParams({ area: state.area, min: state.min, max: state.max, i: state.i });
  history.replaceState(null, "", "#" + p);
}

// ---------------------------------------------------------------- data
async function loadJSON(url) {
  if (!cache.has(url)) {
    cache.set(url, fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(url);
}

async function loadArea(slug) {
  areaData = await loadJSON(`data/areas/${encodeURIComponent(slug)}.json`);
}

function applyFilter() {
  const lo = gradeValue(state.min), hi = gradeValue(state.max);
  filtered = areaData.boulders
    .filter((b) => b.grade_value != null && b.grade_value >= lo && b.grade_value <= hi)
    .sort((a, b) => (b.ascents || 0) - (a.ascents || 0));
  els.count.textContent = `${filtered.length} boulders with video`;
  if (state.i >= filtered.length) state.i = 0;
}

// ---------------------------------------------------------------- rendering
function embedUrl(video) {
  const u = new URL(video.src);
  if (video.kind === "youtube") {
    if (video.start) u.searchParams.set("start", video.start);
    u.searchParams.set("rel", "0");
  } else if (video.kind === "vimeo" && video.start) {
    u.hash = `t=${video.start}s`;
  }
  return u.toString();
}

function renderPlayer() {
  const b = filtered[state.i];
  els.player.replaceChildren();
  if (!b) {
    els.player.innerHTML = `<div class="empty">No boulders with video in this grade range.</div>`;
    els.videoNav.hidden = true;
    return;
  }
  const video = b.videos[state.v];
  if (video.kind === "mp4") {
    const el = document.createElement("video");
    el.src = video.src; el.controls = true; el.preload = "metadata"; el.playsInline = true;
    els.player.append(el);
  } else if (video.kind === "link") {
    els.player.innerHTML = `<div class="empty"><a href="${escapeAttr(video.src)}" target="_blank" rel="noopener">Open video ↗</a></div>`;
  } else {
    const el = document.createElement("iframe");
    el.src = embedUrl(video);
    el.allow = "autoplay; fullscreen; picture-in-picture; encrypted-media";
    el.allowFullscreen = true;
    el.referrerPolicy = "strict-origin-when-cross-origin";
    els.player.append(el);
  }
  els.videoNav.hidden = b.videos.length < 2 && !video.climber;
  els.vlabel.textContent =
    `Video ${state.v + 1}/${b.videos.length}` + (video.climber ? ` · ${video.climber}` : "");
  els.vprev.disabled = state.v === 0;
  els.vnext.disabled = state.v >= b.videos.length - 1;
}

function renderInfo() {
  const b = filtered[state.i];
  if (!b) { els.info.innerHTML = ""; els.pos.textContent = ""; return; }
  const stars = b.rating != null ? `★ ${b.rating.toFixed(1)}` : "";
  els.info.innerHTML = `
    <h2>${escapeHtml(b.name)}<span class="grade">${escapeHtml(b.grade)}</span>
      ${b.alt_grade ? `<span class="muted" style="font-size:14px"> (${escapeHtml(b.alt_grade)})</span>` : ""}</h2>
    <div class="meta">
      <span>${b.ascents} ascents</span>
      ${stars ? `<span>${stars}</span>` : ""}
      ${b.type ? `<span>${escapeHtml(b.type)}</span>` : ""}
      <a href="${escapeAttr(b.url)}" target="_blank" rel="noopener">bleau.info ↗</a>
    </div>`;
  els.pos.textContent = `${state.i + 1} / ${filtered.length}`;
  els.prev.disabled = state.i === 0;
  els.next.disabled = state.i >= filtered.length - 1;
}

function renderList() {
  els.list.replaceChildren(...filtered.map((b, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="g">${escapeHtml(b.grade)}</span>
      <span class="n" title="${escapeAttr(b.name)}">${escapeHtml(b.name)}</span>
      <span class="a">${b.ascents}</span>`;
    li.onclick = () => go(i);
    return li;
  }));
  markActive();
}

function markActive() {
  [...els.list.children].forEach((li, i) => li.classList.toggle("active", i === state.i));
  els.list.children[state.i]?.scrollIntoView({ block: "nearest" });
}

function render() {
  renderPlayer();
  renderInfo();
  markActive();
  writeHash();
}

// ---------------------------------------------------------------- navigation
function go(i) {
  if (i < 0 || i >= filtered.length) return;
  state.i = i; state.v = 0;
  render();
}
function goVideo(v) {
  const b = filtered[state.i];
  if (!b || v < 0 || v >= b.videos.length) return;
  state.v = v;
  renderPlayer();
}

els.prev.onclick = () => go(state.i - 1);
els.next.onclick = () => go(state.i + 1);
els.vprev.onclick = () => goVideo(state.v - 1);
els.vnext.onclick = () => goVideo(state.v + 1);

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "SELECT") return;
  const k = { ArrowLeft: () => go(state.i - 1), ArrowRight: () => go(state.i + 1),
              ArrowUp: () => goVideo(state.v - 1), ArrowDown: () => goVideo(state.v + 1) }[e.key];
  if (k) { e.preventDefault(); k(); }
});

// Swipe left/right on the info card to flip boulders (iframes swallow touches).
let touchX = null;
els.info.addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
els.info.addEventListener("touchend", (e) => {
  if (touchX == null) return;
  const dx = e.changedTouches[0].clientX - touchX;
  if (Math.abs(dx) > 50) go(state.i + (dx < 0 ? 1 : -1));
  touchX = null;
});

// ---------------------------------------------------------------- controls
function fillGradeSelect(sel, value) {
  sel.replaceChildren(...GRADES.map((g) => new Option(g, g, false, g === value)));
}

async function onFilterChange() {
  state.min = els.gmin.value;
  state.max = els.gmax.value;
  if (gradeValue(state.min) > gradeValue(state.max)) {
    state.max = state.min; els.gmax.value = state.max;
  }
  state.i = 0; state.v = 0;
  applyFilter(); renderList(); render();
}

async function onAreaChange() {
  state.area = els.area.value;
  state.i = 0; state.v = 0;
  await loadArea(state.area);
  applyFilter(); renderList(); render();
}

els.gmin.onchange = onFilterChange;
els.gmax.onchange = onFilterChange;
els.area.onchange = onAreaChange;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const escapeAttr = escapeHtml;

// ---------------------------------------------------------------- boot
(async function init() {
  readHash();
  let areas;
  try {
    areas = await loadJSON("data/areas.json");
  } catch {
    els.player.innerHTML = `<div class="empty">No data yet. Run <code>python3 scraper/scrape.py &lt;sector&gt;</code> first.</div>`;
    return;
  }
  els.area.replaceChildren(...areas.map((a) =>
    new Option(`${a.name} (${a.boulders})`, a.slug)));
  if (!areas.some((a) => a.slug === state.area)) state.area = areas[0]?.slug;
  els.area.value = state.area;
  fillGradeSelect(els.gmin, state.min);
  fillGradeSelect(els.gmax, state.max);

  const startIndex = state.i;
  await loadArea(state.area);
  applyFilter();
  state.i = startIndex < filtered.length ? startIndex : 0;
  renderList();
  render();
})();
