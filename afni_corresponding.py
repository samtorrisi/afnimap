#!/usr/bin/env python3
"""AFNI-in-methods papers -> corresponding-author institution counts.

Step 1  Europe PMC: find papers whose methods section mentions AFNI, afni_proc or
        afni_proc.py AND that mention fMRI / "functional MRI" / "functional magnetic
        resonance imaging" / EPI / "echo planar imaging" / BOLD, published 1996-2026. Preprints are excluded and papers
        are de-duplicated by DOI; only papers with a DOI are kept.
Step 2  OpenAlex: look the DOIs up, take authors flagged is_corresponding,
        and their institutions.
Step 3  OpenAlex: fetch city/coordinates for those institutions.
Outputs (current directory):
    afni_papers.csv         one row per paper, with what was kept or dropped and why
    afni_institutions.csv   institution x year credit with country and lat/lon
Each paper counts once (whole numbers): it is credited to the first listed institution
of its first corresponding author who has an institution.
Papers without a DOI, not found in OpenAlex, or with no corresponding-author flag
are dropped (reasons are counted and printed).

Resumable: progress is cached in afni_cache.json. If the run is interrupted,
just run the same command again and it continues. Delete the cache to start over.

Usage:  python3 afni_corresponding.py [N]    # default N=200 (test run)
        python3 afni_corresponding.py 100000 # everything
Standard library only; no API keys needed.
"""
import csv, json, os, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 200
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OA = "https://api.openalex.org"
QUERY = ('(METHODS:"AFNI" OR METHODS:"afni_proc" OR METHODS:"afni_proc.py") '
         'AND ("fMRI" OR "functional MRI" OR '
         '"functional magnetic resonance imaging" OR '
         '"EPI" OR "echo planar imaging" OR "BOLD") '
         'AND PUB_YEAR:[1996 TO 2026] AND NOT SRC:PPR')
CACHE = "afni_cache.json"
SAVE_EVERY = 10  # batches


def get(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "afni-lit-sample/0.2"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("query") == QUERY and c.get("limit") == LIMIT:
            return c
        # Query or size changed: redo the Europe PMC search, but keep the
        # OpenAlex lookups (keyed by DOI / institution id), which stay valid.
        print("Query or size changed: re-running the Europe PMC search, "
              "reusing cached OpenAlex lookups.")
        return {"query": QUERY, "limit": LIMIT, "papers": None,
                "hit_count": None, "oa": c.get("oa", {}),
                "geo": c.get("geo", {})}
    return {"query": QUERY, "limit": LIMIT, "papers": None,
            "hit_count": None, "oa": {}, "geo": {}}


def save_cache(c):
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.replace(tmp, CACHE)


cache = load_cache()

# ---- Step 1: Europe PMC --------------------------------------------------
if cache["papers"] is None:
    papers, cursor, hit_count = [], "*", None
    while len(papers) < LIMIT:
        q = urllib.parse.urlencode({
            "query": QUERY, "format": "json", "pageSize": 100,
            "resultType": "lite", "cursorMark": cursor,
            "sort": "P_PDATE_D desc"})
        data = get(f"{EPMC}?{q}")
        hit_count = data.get("hitCount", hit_count)
        res = (data.get("resultList") or {}).get("result") or []
        if not res:
            break
        for r in res:
            papers.append({"year": r.get("pubYear"), "pmid": r.get("pmid", ""),
                           "doi": (r.get("doi") or "").lower(),
                           "title": r.get("title", "")})
        print(f"  Europe PMC: {len(papers)} fetched", flush=True)
        nxt = data.get("nextCursorMark")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)
    papers = papers[:LIMIT]
    if hit_count and len(papers) < int(hit_count):
        print(f"\n*** WARNING: fetching only {len(papers)} of {hit_count} "
              f"matching papers, newest first, so the results skew to recent "
              f"years. Re-run with a bigger number (e.g. 100000) to get "
              f"everything. ***\n")
    # de-duplicate by DOI (records without a DOI are kept, then dropped later)
    seen, uniq = set(), []
    for p in papers:
        if p["doi"] and p["doi"] in seen:
            continue
        seen.add(p["doi"])
        uniq.append(p)
    print(f"Europe PMC total matches (no preprints): {hit_count}; "
          f"fetched {len(papers)}; {len(papers) - len(uniq)} duplicate DOIs "
          f"removed -> {len(uniq)} papers")
    cache["papers"], cache["hit_count"] = uniq, hit_count
    save_cache(cache)
else:
    print(f"Resuming: {len(cache['papers'])} papers from cache")
papers = cache["papers"]

# ---- Step 2: OpenAlex works by DOI --------------------------------------
oa = cache["oa"]  # doi -> {"n_corresponding": int, "insts": {id: [name, cc]}}
todo = [p["doi"] for p in papers if p["doi"] and p["doi"] not in oa]
batches = [todo[i:i + 40] for i in range(0, len(todo), 40)]
for bi, batch in enumerate(batches, 1):
    flt = "doi:" + "|".join("https://doi.org/" + d for d in batch)
    q = urllib.parse.urlencode({"filter": flt, "per-page": 100,
                                "select": "doi,authorships"})
    data = get(f"{OA}/works?{q}")
    for d in batch:
        oa.setdefault(d, None)  # None = looked up, not found
    for w in data.get("results", []):
        d = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        corr = [a for a in w.get("authorships", []) if a.get("is_corresponding")]
        insts = {}
        for a in corr:
            for ins in a.get("institutions", []):
                insts[ins["id"]] = [ins.get("display_name", ""),
                                    ins.get("country_code", "")]
        oa[d] = {"n_corresponding": len(corr), "insts": insts}
    if bi % SAVE_EVERY == 0 or bi == len(batches):
        print(f"  OpenAlex works: batch {bi}/{len(batches)}", flush=True)
        save_cache(cache)
    time.sleep(0.3)

# ---- classify + count ----------------------------------------------------
reasons = Counter()
credit = defaultdict(int)     # (inst_id, year) -> number of papers
inst_meta = {}                # institutions that received credit
listed = {}                   # every corresponding institution seen (for cities)
for p in papers:
    rec = oa.get(p["doi"]) if p["doi"] else None
    p["insts"] = (rec or {}).get("insts", {})
    if not p["doi"]:
        p["status"] = "no DOI"
    elif rec is None:
        p["status"] = "not found in OpenAlex"
    elif not rec["n_corresponding"]:
        p["status"] = "no corresponding-author flag"
    elif not rec["insts"]:
        p["status"] = "corresponding author has no institution"
    else:
        p["status"] = "kept"
        listed.update(rec["insts"])
        # insts is ordered: corresponding authors in author order, each
        # author's institutions in listed order. The first entry is therefore
        # the first listed institution of the first corresponding author
        # who has one.
        iid = next(iter(rec["insts"]))
        credit[(iid, p["year"])] += 1
        inst_meta[iid] = rec["insts"][iid]
        p["credited"] = iid
    reasons[p["status"]] += 1

# ---- Step 3: institution coordinates ------------------------------------
geo = cache["geo"]  # inst_id -> [lat, lon, city]
ids = [i for i in listed if i not in geo]
for bi in range(0, len(ids), 40):
    batch = ids[bi:bi + 40]
    short = [x.rsplit("/", 1)[-1] for x in batch]
    q = urllib.parse.urlencode({
        "filter": "openalex:" + "|".join(short), "per-page": 100,
        "select": "id,display_name,country_code,geo"})
    for i in batch:
        geo.setdefault(i, [None, None, None])
    for ins in get(f"{OA}/institutions?{q}").get("results", []):
        g = ins.get("geo") or {}
        geo[ins["id"]] = [g.get("latitude"), g.get("longitude"), g.get("city")]
    print(f"  OpenAlex institutions: {min(bi + 40, len(ids))}/{len(ids)}",
          flush=True)
    time.sleep(0.3)
save_cache(cache)

# ---- write ---------------------------------------------------------------
with open("afni_papers.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["year", "pmid", "doi", "title", "status",
                "credited_institution", "all_corresponding_institutions",
                "credited_institution_name", "credited_country"])

    def fmt(iid, name, cc):
        city = (geo.get(iid) or [None, None, None])[2]
        place = ", ".join(x for x in (city, cc) if x)
        return f"{name} ({place})" if place else name

    for p in papers:
        parts = [fmt(i, n, c) for i, (n, c) in p["insts"].items()]
        cid = p.get("credited")
        credited = fmt(cid, *p["insts"][cid]) if cid else ""
        cname, ccc = p["insts"][cid] if cid else ("", "")
        w.writerow([p["year"], p["pmid"], p["doi"], p["title"],
                    p["status"], credited, "; ".join(parts), cname, ccc])

with open("afni_institutions.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["institution", "country", "city", "lat", "lon",
                "year", "paper_credit"])
    for (iid, year), c in sorted(credit.items(), key=lambda kv: -kv[1]):
        name, cc = inst_meta[iid]
        lat, lon, city = geo.get(iid, [None, None, None])
        w.writerow([name, cc, city, lat, lon, year, round(c, 3)])

print("\nPaper outcomes:")
for k, v in reasons.most_common():
    print(f"  {k}: {v}")
print(f"\nInstitutions with credit: {len(inst_meta)}  -> afni_institutions.csv")
print("Wrote afni_papers.csv")
