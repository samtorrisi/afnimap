#!/usr/bin/env python3
"""Build an interactive map (single HTML file) from the AFNI literature CSVs.

Inputs (made by afni_corresponding.py):
    afni_institutions.csv   institution x year paper counts with coordinates
    afni_papers.csv         one row per paper (used for the click-to-list-papers
                            panel; the map still works without it)

Circle area is proportional to the number of papers credited to an institution.
Institutions within --merge-km of a larger one are merged into one circle so a
campus, its medical school and its hospital show as a single place. Click a
circle to list its papers (as links) in the panel under the map.

The projection is a drop-down in the page: Mercator (default) or Equal Earth.
The map is cropped to the latitudes of the data (northernmost and southernmost
institution) plus a 5 degree buffer.

Usage:
    python3 make_afni_map.py                          # defaults
    python3 make_afni_map.py in.csv --papers p.csv --out map.html --merge-km 3
    python3 make_afni_map.py --out index.html --goatcounter afnimap   # to publish

Outputs:
    afni_map.html        open in any browser. Needs internet: D3, the country
                         outlines and the US-state / Canadian-province lines
                         are loaded from CDNs (Natural Earth, public domain).
    afni_unmapped.csv    institutions with no coordinates (not on the map);
                         only written if there are any
Standard library only.
"""
import argparse, csv, datetime, html, json, math, os, re
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("infile", nargs="?", default="afni_institutions.csv")
ap.add_argument("--papers", default=None,
                help="afni_papers.csv (default: next to the input file)")
ap.add_argument("--out", default="afni_map.html")
ap.add_argument("--unmapped", default="afni_unmapped.csv")
ap.add_argument("--goatcounter", default=None, metavar="CODE",
                help="add the GoatCounter visit counter for "
                     "https://CODE.goatcounter.com (omit for no analytics)")
ap.add_argument("--merge-km", type=float, default=2.0,
                help="merge institutions closer than this (default 2 km; "
                     "0 disables merging)")
args = ap.parse_args()
if args.goatcounter and not re.fullmatch(r"[a-z0-9-]+", args.goatcounter):
    ap.error("--goatcounter CODE should be just the site code, e.g. afnimap")
papers_path = args.papers or os.path.join(
    os.path.dirname(os.path.abspath(args.infile)), "afni_papers.csv")

# Shown in the "?" help. Keep in sync with the query in afni_corresponding.py.
SEARCH_YEARS = "1996–2026"
_today = datetime.date.today()
BUILT = f"{_today:%B} {_today.day}, {_today.year}"   # shown as "Last update"


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def clean_title(t):
    """Europe PMC titles can carry markup like <i>..</i> and HTML entities."""
    return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()


# ---- papers, grouped by the institution they were credited to ------------
papers_by_inst = defaultdict(list)
credited_total = 0
have_papers = False
if os.path.exists(papers_path):
    with open(papers_path, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames or []
        if "credited_institution_name" in cols:
            have_papers = True
            for r in rd:
                if r.get("status") != "kept":
                    continue
                credited_total += 1
                key = (r["credited_institution_name"],
                       r.get("credited_country", ""))
                papers_by_inst[key].append(
                    [str(r["year"]), (r.get("doi") or "").strip(),
                     (r.get("pmid") or "").strip(), clean_title(r["title"])])
        else:
            print(f"NOTE: {papers_path} is from an older version of "
                  "afni_corresponding.py (no credited_institution_name "
                  "column). Re-run that script, then this one, to get "
                  "click-to-list-papers.")
else:
    print(f"NOTE: {papers_path} not found; the map will not list papers.")

# ---- institutions: one record each, credit by year -----------------------
inst = {}
with open(args.infile, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        key = (r["institution"], r["country"])
        d = inst.setdefault(key, {"name": r["institution"],
                                  "country": r["country"], "city": "",
                                  "lat": None, "lon": None,
                                  "by_year": defaultdict(float),
                                  "papers": papers_by_inst.get(key, [])})
        d["by_year"][str(r["year"])] += float(r["paper_credit"] or 0)
        if r.get("city"):
            d["city"] = r["city"]
        lat, lon = num(r.get("lat")), num(r.get("lon"))
        if lat is not None and lon is not None:
            d["lat"], d["lon"] = lat, lon

for d in inst.values():
    d["total"] = sum(d["by_year"].values())
    d["papers"].sort(key=lambda q: (q[0], q[3]), reverse=True)

mapped = sorted((d for d in inst.values() if d["lat"] is not None),
                key=lambda d: -d["total"])
unmapped = sorted((d for d in inst.values() if d["lat"] is None),
                  key=lambda d: -d["total"])

if unmapped:
    with open(args.unmapped, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution", "country", "city", "total_credit"])
        for d in unmapped:
            w.writerow([d["name"], d["country"], d["city"],
                        round(d["total"], 3)])
elif os.path.exists(args.unmapped):
    os.remove(args.unmapped)   # stale output from an earlier run


# ---- merge nearby institutions (greedy, largest first) -------------------
def km(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lon"] - a["lon"])
    h = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


clusters = []
for d in mapped:
    home = None
    if args.merge_km > 0:
        for c in clusters:
            if km(c["anchor"], d) <= args.merge_km:
                home = c
                break
    if home is None:
        home = {"anchor": d, "members": []}
        clusters.append(home)
    home["members"].append(d)

out = []
for c in clusters:
    a = c["anchor"]
    out.append({
        "city": a["city"], "country": a["country"],
        "lat": a["lat"], "lon": a["lon"],
        "members": [{"name": m["name"], "by_year": dict(m["by_year"]),
                     "papers": m["papers"]} for m in c["members"]],
    })

years = sorted({y for d in mapped for y in d["by_year"]})

# If the search found nothing before some year, say so in the help text.
_start = int(SEARCH_YEARS[:4])
EARLY = (f", and the search mechanisms did not locate papers published "
         f"before {years[0]}" if years and int(years[0]) > _start else "")

# Crop the map to the data: northernmost / southernmost institution + 5 deg.
# (Capped at 85 so Mercator stays finite.) Uses all years so the crop does not
# move when the year range changes.
BUFFER_DEG = 5.0
if mapped:
    north = max(mapped, key=lambda d: d["lat"])
    south = min(mapped, key=lambda d: d["lat"])
    lat_n = min(85.0, north["lat"] + BUFFER_DEG)
    lat_s = max(-85.0, south["lat"] - BUFFER_DEG)
else:
    lat_n, lat_s = 75.0, -60.0
payload = json.dumps({"places": out, "years": years,
                      "lat_n": lat_n, "lat_s": lat_s,
                      "merge_km": args.merge_km,
                      "have_papers": have_papers},
                     ensure_ascii=False).replace("</", "<\\/")

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Published use of AFNI for fMRI</title>
<style>
 html,body{height:100%;margin:0;font:14px/1.4 system-ui,sans-serif;color:#222}
 body{display:flex;flex-direction:column}
 #head{display:flex;align-items:center;justify-content:space-between;
       padding:10px 12px 12px;background:#fafafa}
 #title{margin:0;font-size:24px;font-weight:700}
 #help{position:relative;width:32px;height:32px;border-radius:50%;
       border:2px solid #1f5fae;color:#1f5fae;background:#fff;
       text-align:center;line-height:28px;font-size:18px;font-weight:700;
       cursor:help;user-select:none}
 #help:hover,#help:focus{background:#dcebfb;outline:none}
 #helptext{display:none;position:absolute;right:0;top:38px;width:560px;
           max-width:86vw;z-index:30;text-align:left;font-weight:400;
           font-size:13px;line-height:1.45;color:#fff;background:#1f5fae;
           border:1px solid #174a8b;border-radius:6px;padding:12px 16px;
           box-shadow:0 4px 14px rgba(0,0,0,.35);cursor:default}
 #helptext .by{color:#cfe0f7;font-size:12px}
 #helptext::before{content:"";position:absolute;left:0;right:0;top:-8px;
                   height:8px}
 #helptext p{margin:0 0 7px}
 #helptext p:last-child{margin:0}
 #help:hover #helptext,#help:focus #helptext{display:block}
 #bar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:8px 12px;
      border-bottom:1px solid #ddd;background:#fafafa}
 #bar label{display:flex;gap:6px;align-items:center}
 #wrap{display:flex;flex:1;min-height:0}
 #main{flex:1;min-width:0;display:flex;flex-direction:column}
 #map{flex:1 1 0;min-height:0;cursor:grab;overflow:hidden}
 #papers{flex:0 0 36%;min-height:140px;overflow:auto;box-sizing:border-box;
         border-top:2px solid #bbb;padding:8px 16px;background:#fff}
 #papers h3{margin:0 0 6px;font-size:14px}
 #papers ol{margin:0;padding-left:30px}
 #papers li{margin:3px 0;padding-left:12px}
 #papers li > b{margin-right:.5em}
 #papers a{color:#1a56a8}
 #papers .inst{color:#777}
 #side{width:320px;overflow:auto;border-left:1px solid #ddd;padding:8px 12px;
        font-size:12px}
 #side h3{margin:4px 0 6px;font-size:13px}
 #side ol{margin:0;padding-left:22px}
 #side li{margin:2px 0}
 .n{color:#666;white-space:nowrap}
 p.n{white-space:normal}
 #summary{color:#555}
 #note{color:#a33}
 #tip{position:fixed;pointer-events:none;display:none;max-width:340px;z-index:10;
      background:#fff;border:1px solid #888;border-radius:4px;padding:6px 9px;
      box-shadow:0 2px 8px rgba(0,0,0,.25);font-size:13px}
 #tip ul{margin:4px 0 0;padding-left:18px}
 @media(max-width:800px){#side{display:none}}
</style></head><body>
<div id="head">
 <h1 id="title">Published use of AFNI for fMRI</h1>
 <div id="help" tabindex="0" aria-label="Help">?
  <div id="helptext">
   <p><b>A community of users.</b> This map shows published fMRI papers whose
   methods sections list the software AFNI (Analysis of Functional
   NeuroImages) among their tools. The circles are placed at the institution
   of the corresponding author, and the circle's area is proportional to the
   number of papers published within the range of years selected.</p>
   <p><b>Data sources.</b> Papers: Europe PMC. Corresponding authors,
   institutions and locations: OpenAlex.</p>
   <p><b>Search filters.</b> A paper's methods section contained "AFNI",
   "afni_proc" or "afni_proc.py", and the paper also mentions "fMRI",
   "functional MRI", "functional magnetic resonance imaging", "EPI",
   "echo planar imaging" or "BOLD", and was
   published between __SEARCH_YEARS__. Note that preprints are excluded__EARLY__.
   Across all years some published work may have been missed.</p>
   <p><b>Counting.</b> Each paper counts once, for the first listed institution
   of its first corresponding author. Institutions within __MERGE_KM__ km are
   combined into one circle ("+N nearby").</p>
   <p><b>Caveats.</b> Only open-access full texts are searched, so counts
   understate use, especially in earlier years. Listing AFNI does not
   necessarily mean it was the main analysis tool.</p>
   <p><b>Map use.</b> Hover a circle for details, click it for links to the
   papers, scroll to zoom, drag to pan.</p>
   <p class="by">By Salvatore (Sam) Torrisi + Claude Sonnet. Last update:
   __BUILT__.</p>
  </div>
 </div>
</div>
<div id="bar">
 <label>From <select id="y0"></select></label>
 <label>to <select id="y1"></select></label>
 <label>Projection <select id="proj">
   <option value="mercator" selected>Mercator</option>
   <option value="equalearth">Equal Earth (equal-area)</option></select></label>
 <label>Dot size <input id="scale" type="range" min="0.4" max="1.5" step="0.05"
   value="0.9"></label>
 <span id="summary"></span><span id="note"></span>
</div>
<div id="wrap">
 <div id="main"><div id="map"></div><div id="papers"></div></div>
 <div id="side"></div>
</div>
<div id="tip"></div>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js"></script>
<script>
const DATA = __DATA__;
const WORLD_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";
const ADMIN1_URLS = [
  "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_50m_admin_1_states_provinces.geojson",
  "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_1_states_provinces.geojson"];
const esc = s => String(s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// whole numbers show as integers; anything fractional keeps one decimal
const fmt = v => (Math.abs(v - Math.round(v)) < 1e-6
                  ? String(Math.round(v)) : v.toFixed(1));
const LAT_N = DATA.lat_n, LAT_S = DATA.lat_s;   // data-driven crop
const OCEAN = '#dbe9f4';
const MIN_R = 1.5;                     // smallest circle radius in pixels

const ys = DATA.years;
const y0 = document.getElementById('y0'), y1 = document.getElementById('y1');
const scale = document.getElementById('scale');
const projSel = document.getElementById('proj');
ys.forEach(y => { y0.add(new Option(y, y)); y1.add(new Option(y, y)); });
y0.value = ys[0]; y1.value = ys[ys.length - 1];

const stage = document.getElementById('map');
const papersBox = document.getElementById('papers');
const svg = d3.select(stage).append('svg')
  .style('width', '100%').style('height', '100%').style('display', 'block')
  .style('overflow', 'hidden');
const gRoot = svg.append('g');
const gBase = gRoot.append('g');
const gDots = gRoot.append('g');
const tip = document.getElementById('tip');
let world = null, admin1 = null, zoomK = 1, W = 900, H = 500, projection = null;
let rows = [], selected = null;

const zoom = d3.zoom().scaleExtent([1, 400]).on('zoom', ev => {
  zoomK = ev.transform.k;
  gRoot.attr('transform', ev.transform);
  gDots.selectAll('circle').attr('r', d => d.r0 / zoomK)
       .attr('stroke-width', d => (d.id === selected ? 2.5 : 1) / zoomK);
});
svg.call(zoom);
svg.on('click', () => select(null));   // click on empty map clears selection

function inRange(by, a, b) {
  let t = 0;
  for (const y in by) if (y >= a && y <= b) t += by[y];
  return t;
}

function setupProjection() {
  const r = stage.getBoundingClientRect();
  W = r.width || 900; H = r.height || 500;
  svg.attr('viewBox', `0 0 ${W} ${H}`);
  zoom.extent([[0, 0], [W, H]]).translateExtent([[0, 0], [W, H]]);
  svg.call(zoom.transform, d3.zoomIdentity);
  const box = [[4, 4], [W - 4, H - 4]];
  if (projSel.value === 'equalearth') {
    // equal-area; the projection the UN General Assembly encouraged in
    // September 2026 (non-binding). Fit the equator's full width and the
    // LAT_N..LAT_S band; the rest of the globe is cropped by the viewport.
    projection = d3.geoEqualEarth().fitExtent(box, {type: 'MultiPoint',
      coordinates: [[-180, 0], [180, 0], [0, LAT_N], [0, LAT_S]]});
    stage.style.background = '#fff';
  } else {
    projection = d3.geoMercator().fitExtent(box, {type: 'MultiPoint',
      coordinates: [[-180, LAT_N], [180, LAT_N], [180, LAT_S], [-180, LAT_S]]});
    stage.style.background = OCEAN;
  }
}

// Draws the base map. Layers, bottom to top: ocean, graticule, country fill,
// state/province lines, country borders (on top so coastlines stay crisp).
// Strokes are non-scaling so lines stay thin when zoomed in.
function drawBase() {
  const path = d3.geoPath(projection);
  const line = (sel, color, w) => sel.attr('fill', 'none').attr('stroke', color)
    .attr('stroke-width', w).attr('vector-effect', 'non-scaling-stroke');
  gBase.selectAll('*').remove();
  line(gBase.append('path').datum({type: 'Sphere'}).attr('d', path),
       '#8fa3b5', 1).attr('fill', OCEAN);
  line(gBase.append('path').datum(d3.geoGraticule10()).attr('d', path),
       '#fff', 0.5).attr('stroke-opacity', 0.7);
  const countries = world ? topojson.feature(world, world.objects.countries) : null;
  if (countries)
    gBase.append('path').datum(countries).attr('d', path)
      .attr('fill', '#f2efe6').attr('stroke', 'none');
  if (admin1)
    line(gBase.append('path').datum(admin1).attr('d', path), '#c9c4b4', 0.5);
  if (countries)
    line(gBase.append('path').datum(countries).attr('d', path), '#a8a393', 0.6);
}

function computeRows() {
  const a = y0.value, b = y1.value;
  rows = [];
  DATA.places.forEach((p, id) => {
    const ms = p.members.map(m => ({name: m.name, v: inRange(m.by_year, a, b)}))
                        .filter(m => m.v > 0).sort((x, y) => y.v - x.v);
    const t = ms.reduce((s, m) => s + m.v, 0);
    // label = biggest institution in the selected years, plus how many
    // other institutions were merged into this circle
    if (t > 0) rows.push({id, p, t, ms, label: ms[0].name +
      (ms.length > 1 ? ` (+${ms.length - 1} nearby)` : '')});
  });
  rows.sort((x, y) => y.t - x.t);
}

function showTip(ev, d) {
  const list = d.ms.slice(0, 8).map(m =>
    `<li>${esc(m.name)}: ${fmt(m.v)}</li>`).join('');
  const more = d.ms.length > 8 ? `<li>…and ${d.ms.length - 8} more</li>` : '';
  const head = d.ms.length > 1
    ? `<br>Combined from ${d.ms.length} institutions within ` +
      `${DATA.merge_km} km:` : '';
  tip.innerHTML = `<b>${esc(d.label)}</b><br>${esc(d.p.city)} ` +
    `${esc(d.p.country)}<br>${fmt(d.t)} papers${head}` +
    `<ul>${list}${more}</ul><i>Click to list papers</i>`;
  tip.style.display = 'block';
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + w > window.innerWidth - 4) x = ev.clientX - w - 14;
  if (y + h > window.innerHeight - 4) y = ev.clientY - h - 14;
  tip.style.left = Math.max(4, x) + 'px';
  tip.style.top = Math.max(4, y) + 'px';
}

function paperLink(q) {
  const href = q.doi ? 'https://doi.org/' + encodeURI(q.doi)
    : (q.pmid ? 'https://pubmed.ncbi.nlm.nih.gov/' +
       encodeURIComponent(q.pmid) + '/' : null);
  const t = esc(q.title || '(untitled)');
  return href ? `<a href="${esc(href)}" target="_blank" ` +
                `rel="noopener noreferrer">${t}</a>` : t;
}

function showPapers() {
  if (selected === null) {
    papersBox.innerHTML = '<h3>Papers</h3><p class="n">Click a circle on the ' +
      'map to list its papers here. Click empty map to clear.</p>';
    return;
  }
  const a = y0.value, b = y1.value;
  const p = DATA.places[selected];
  const row = rows.find(r => r.id === selected);
  if (!row) {
    papersBox.innerHTML = `<h3>${esc(p.members[0].name)}</h3><p class="n">` +
      `No papers from here in ${esc(a)}–${esc(b)}.</p>`;
    return;
  }
  const list = [];
  for (const m of p.members)
    for (const q of (m.papers || []))
      if (q[0] >= a && q[0] <= b)
        list.push({y: q[0], doi: q[1], pmid: q[2], title: q[3], inst: m.name});
  list.sort((x, y) => y.y.localeCompare(x.y) || x.title.localeCompare(y.title));
  if (!list.length) {
    papersBox.innerHTML = `<h3>${esc(row.label)}: ${fmt(row.t)} papers</h3>` +
      '<p class="n">Paper list not available. Re-run afni_corresponding.py ' +
      'and then make_afni_map.py so afni_papers.csv has the ' +
      'credited_institution_name column.</p>';
    return;
  }
  const multi = row.ms.length > 1;
  papersBox.innerHTML =
    `<h3>${esc(row.label)}: ${list.length} papers, ${esc(a)}–${esc(b)}</h3><ol>` +
    list.map(q => `<li><b>${esc(q.y)}</b>${paperLink(q)}` +
      (multi ? ` <span class="inst">(${esc(q.inst)})</span>` : '') +
      '</li>').join('') + '</ol>';
  papersBox.scrollTop = 0;
}

function styleSelected() {
  gDots.selectAll('circle')
    .attr('stroke', d => d.id === selected ? '#000' : '#0b2a6b')
    .attr('stroke-width', d => (d.id === selected ? 2.5 : 1) / zoomK);
  gDots.selectAll('circle').filter(d => d.id === selected).raise();
}

function select(id) {
  selected = id;
  styleSelected();
  showPapers();
}

function drawDots() {
  computeRows();
  const k = +scale.value;
  rows.forEach(d => { d.r0 = Math.max(MIN_R, k * Math.sqrt(d.t)); });
  gDots.selectAll('circle').data(rows, d => d.id).join('circle')
    .attr('cx', d => projection([d.p.lon, d.p.lat])[0])
    .attr('cy', d => projection([d.p.lon, d.p.lat])[1])
    .attr('r', d => d.r0 / zoomK)
    .attr('fill', '#1d5fd1').attr('fill-opacity', 0.55)
    .style('cursor', 'pointer')
    .on('mousemove', showTip)
    .on('mouseleave', () => { tip.style.display = 'none'; })
    .on('click', (ev, d) => { ev.stopPropagation(); select(d.id); });
  styleSelected();
  const total = rows.reduce((s, r) => s + r.t, 0);
  document.getElementById('summary').textContent =
    `${Number(fmt(total)).toLocaleString()} papers across ` +
    `${rows.length} locations`;
  document.getElementById('side').innerHTML =
    `<h3>Top locations, ${esc(y0.value)}–${esc(y1.value)}</h3><ol>` +
    rows.slice(0, 25).map(r => `<li>${esc(r.label)} ` +
      `<span class="n">${fmt(r.t)}</span></li>`).join('') + '</ol>' +
    `<p class="n">“+N nearby” means N other institutions within ` +
    `${DATA.merge_km} km were combined into that circle. Hover a circle ` +
    `to see them, and click the circle to get paper links.</p>`;
  showPapers();
}

function renderAll() { setupProjection(); drawBase(); drawDots(); }
const noteEl = document.getElementById('note');

[y0, y1, scale].forEach(e => e.addEventListener('input', drawDots));
projSel.addEventListener('input', renderAll);
let rt = null;
window.addEventListener('resize', () => {
  clearTimeout(rt); rt = setTimeout(renderAll, 150);
});
renderAll();
d3.json(WORLD_URL).then(w => { world = w; drawBase(); })
  .catch(() => {
    noteEl.textContent += ' Country outlines could not be loaded (offline?).';
  });
d3.json(ADMIN1_URLS[0]).catch(() => d3.json(ADMIN1_URLS[1])).then(g => {
  admin1 = {type: 'FeatureCollection', features: g.features.filter(
    f => f.properties.adm0_a3 === 'USA' || f.properties.adm0_a3 === 'CAN')};
  drawBase();
}).catch(() => {
  noteEl.textContent += ' State/province lines could not be loaded.';
});
</script>
__GOATCOUNTER__
</body></html>
"""

GOATCOUNTER = (
    f'<script data-goatcounter="https://{args.goatcounter}.goatcounter.com/count"\n'
    f'        async src="//gc.zgo.at/count.js"></script>'
    if args.goatcounter else "")

with open(args.out, "w", encoding="utf-8") as f:
    f.write(HTML.replace("__SEARCH_YEARS__", SEARCH_YEARS)
                .replace("__MERGE_KM__", f"{args.merge_km:g}")
                .replace("__BUILT__", BUILT)
                .replace("__EARLY__", EARLY)
                .replace("__GOATCOUNTER__", GOATCOUNTER)
                .replace("__DATA__", payload))

shown = sum(d["total"] for d in mapped)
lost = sum(d["total"] for d in unmapped)
print(f"{len(inst)} institutions -> {len(mapped)} mapped, "
      f"{len(unmapped)} without coordinates")
print(f"{len(out)} circles after merging within {args.merge_km} km")
print(f"Papers on map: {shown:.0f}; with no coordinates: {lost:.0f} "
      f"({100 * lost / max(shown + lost, 1e-9):.1f}%)"
      + (f" -> {args.unmapped}" if unmapped else ""))
if have_papers:
    linked = sum(len(d["papers"]) for d in inst.values())
    print(f"Paper links: {linked} of {credited_total} credited papers "
          f"matched to an institution in the CSV")
    if linked != credited_total:
        print("  NOTE: the counts differ; afni_papers.csv and "
              "afni_institutions.csv may be from different runs.")
print(f"Wrote {args.out}")
