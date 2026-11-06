# 2026 British Columbia provincial election results

A static page for the provincial general election held on 24 October 2026. It shows the province-wide totals published by Elections BC and a lookup for each of the 93 electoral districts.

Final count was still in progress when the packaged snapshot was retrieved. These are not certified final results. The live report is at <https://results.elections.bc.ca/>.

## Run it locally

From this folder:

```bash
python3 -m http.server 8080
```

Open <http://127.0.0.1:8080/>.

The page reads `data/results.json` and `data/districts.geojson`. Opening `index.html` directly will not load those files.

The same files can be published from a static host. There is no custom domain and no analytics.

## Refresh the snapshot

```bash
python3 scripts/update_results.py
python3 scripts/validate_results.py
```

The update script downloads the Elections BC candidate report and party report, plus the 2023 electoral-district boundary layer from the B.C. Geographic Warehouse. It replaces the data files only when the candidate totals, the party totals, and the district columns agree. If the boundary service is down, `python3 scripts/update_results.py --skip-boundaries` refreshes the results and leaves an existing boundary file in place.

## Sources

Results, candidate ballot names, and district names come from Elections BC event-night reporting for event 11684, report `GE-2026-10-24`:

- <https://results.elections.bc.ca/>
- <https://results.elections.bc.ca/Results_11684_GE-2026-10-24_Candidate.html>
- <https://results.elections.bc.ca/Results_11684_GE-2026-10-24_Party.html>

The election calendar is the Elections BC 2026 provincial election page: <https://elections.bc.ca/2026-provincial-election/>. Final count preparations are described at <https://elections.bc.ca/news/update-on-preparations-for-final-count/>.

District shapes come from the Elections BC layer “Provincial Electoral Districts — Electoral Boundaries Redistribution, 2023” in the B.C. Geographic Warehouse:

- Catalogue: <https://catalogue.data.gov.bc.ca/dataset/provincial-electoral-districts-electoral-boundaries-redistribution-2023>
- Layer: `WHSE_ADMIN_BOUNDARIES.EBC_ELECTORAL_DISTS_BS11_SVW`

The packaged geometry uses that service’s own generalization (`maxAllowableOffset` of 0.002 degrees, five decimal places, output EPSG:4326). It is for browsing district names. Elections BC says the spatial data must not be used to determine a voter’s electoral district. Official maps are at <https://elections.bc.ca/resources/maps/provincial-maps/>.

Contains information licenced under the [Elections BC Open Data Licence](https://www.elections.bc.ca/docs/EBC-Open-Data-Licence.pdf).

The retrieval time and the “as of” time printed by Elections BC are stored in `data/results.json`.

## What is not included

- Certified final results. Final count was unfinished, and Return Day had not arrived.
- A Statement of Votes, or results by voting area or ballot box. The provincial voting-results archive did not yet list this election.
- An address search. Use the Elections BC maps page for the official district finder.
- Party logos or the Elections BC logo.

Where the candidate report leaves affiliation blank, those votes match the Unaffiliated line on the party report. The candidate report prints “Christian Heritage Party of BC”; the party report prints “Christian Heritage Party of B.C.” The packaged file keeps both facts, and the checks require the vote totals to match.

Margins are the difference between the two highest published totals. Elections BC does not print that difference.
