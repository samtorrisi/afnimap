# afnimap

An interactive map of published fMRI papers whose methods sections list the
software [AFNI](https://afni.nimh.nih.gov) (Analysis of Functional NeuroImages)
among their tools. Circles are placed at the institution of the corresponding
author, and each circle's area is proportional to the number of papers in the
selected range of years.

**[Try it in your browser →](https://samtorrisi.github.io/afnimap/)**

Hover a circle for details, click it for links to its papers, scroll to zoom
(up to 400×), drag to pan. The "?" button in the page header explains the data
and its limits.

## How it works

Two standard-library Python scripts, no API keys needed:

| Script | What it does |
| --- | --- |
| `afni_corresponding.py` | Finds papers in Europe PMC, looks up each paper's corresponding author and institution in OpenAlex, and writes `afni_papers.csv` (one row per paper) and `afni_institutions.csv` (papers per institution per year, with coordinates). |
| `make_afni_map.py` | Turns those two CSVs into a single self-contained web page. |

## Data sources

- **Papers:** [Europe PMC](https://europepmc.org) (full-text search of open-access articles)
- **Corresponding authors, institutions, locations:** [OpenAlex](https://openalex.org)
- **State and province lines:** [Natural Earth](https://www.naturalearthdata.com) (public domain)
- **Country outlines and mapping library:** [world-atlas](https://github.com/topojson/world-atlas) and [D3](https://d3js.org), loaded from the jsDelivr CDN

## Search filters

A paper is included if its methods section contains "AFNI", "afni_proc" or
"afni_proc.py", the paper also mentions "fMRI", "functional MRI" or "functional
magnetic resonance imaging", and it was published between 1996 and 2026.
Preprints are excluded. The Europe PMC query is:

```
(METHODS:"AFNI" OR METHODS:"afni_proc" OR METHODS:"afni_proc.py")
AND (fMRI OR "functional MRI" OR "functional magnetic resonance imaging")
AND PUB_YEAR:[1996 TO 2026] AND NOT SRC:PPR
```

## Counting rules

- Each paper counts once, for the first listed institution of its first
  corresponding author who has an institution.
- Papers without a DOI, not found in OpenAlex, or with no corresponding-author
  flag are dropped (the reasons are counted and printed).
- Institutions within 2 km of a larger one are combined into one circle
  ("+N nearby"; change with `--merge-km`).

## Limitations

- Only open-access full texts are searched, so counts understate use,
  especially in earlier years.
- Listing AFNI in a methods section does not mean it was the main analysis tool.
- The latest year is incomplete.
- "First listed institution" depends on the order OpenAlex stores affiliations.

## Reproduce it

Requires Python 3.7+ and an internet connection.

```
python3 afni_corresponding.py 100000
python3 make_afni_map.py --out index.html
```

The number is the maximum papers to fetch (the default of 200 is only a test
run, newest first). The fetch takes minutes and is resumable: progress is cached
in `afni_cache.json` (not tracked in git), so an interrupted run continues when
you run the same command again. Open `index.html` in a browser.

Add `--goatcounter CODE` to `make_afni_map.py` to include a
[GoatCounter](https://www.goatcounter.com) visit counter for
`https://CODE.goatcounter.com`. Without it the page has no analytics.

If you change the search query in `afni_corresponding.py`, also update
`SEARCH_YEARS` near the top of `make_afni_map.py` so the "?" help text matches.

## Credits

By Salvatore (Sam) Torrisi with Claude Sonnet (Anthropic).

## License

See [LICENSE](LICENSE).
