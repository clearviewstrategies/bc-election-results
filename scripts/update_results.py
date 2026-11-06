#!/usr/bin/env python3
"""Download the current Elections BC event-night report and district boundaries.

Figures are copied from the official pages. Nothing is estimated. If the two
official tables disagree, the script stops without replacing the snapshot.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_results import validate


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "results.json"
BOUNDARIES_PATH = ROOT / "data" / "districts.geojson"

CANDIDATE_URL = "https://results.elections.bc.ca/Results_11684_GE-2026-10-24_Candidate.html"
PARTY_URL = "https://results.elections.bc.ca/Results_11684_GE-2026-10-24_Party.html"
INITIAL_CANDIDATE_URL = "https://results.elections.bc.ca/Results_11684_GE-2026-10-24_Candidate_init_saved.html"
INITIAL_PARTY_URL = "https://results.elections.bc.ca/Results_11684_GE-2026-10-24_Party_init_saved.html"
LIVE_URL = "https://results.elections.bc.ca/"
BOUNDARY_URL = (
    "https://delivery.maps.gov.bc.ca/arcgis/rest/services/whse/"
    "bcgw_pub_whse_admin_boundaries/MapServer/74/query"
    "?where=1%3D1"
    "&outFields=ED_NAME,ED_ABBREVIATION,ELECTORAL_DISTRICT_ID"
    "&returnGeometry=true&outSR=4326&f=geojson"
    "&geometryPrecision=5&maxAllowableOffset=0.002"
)
CATALOGUE_URL = (
    "https://catalogue.data.gov.bc.ca/dataset/"
    "provincial-electoral-districts-electoral-boundaries-redistribution-2023"
)
LICENCE_URL = "https://www.elections.bc.ca/docs/EBC-Open-Data-Licence.pdf"

USER_AGENT = "bc-election-results/1.0 (public civic snapshot of Elections BC open results)"
PACIFIC = ZoneInfo("America/Vancouver")


class TableParser(HTMLParser):
    """Collect text cells from one HTML table."""

    def __init__(self, table_id: str | None = None, tbody_id: str | None = None):
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.tbody_id = tbody_id
        self.rows: list[dict] = []
        self._table_depth = 0
        self._active = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._cell_attrs: dict[str, str] = {}
        self._cells: list[dict] = []
        self._row_attrs: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        attributes = {key: value or "" for key, value in attrs}
        if tag == "table" and attributes.get("id") == self.table_id:
            self._table_depth += 1
            self._active = True
        elif tag == "table" and self._active:
            self._table_depth += 1
        elif tag == "tbody" and self.tbody_id and attributes.get("id") == self.tbody_id:
            self._active = True
        elif self._active and tag == "tr":
            self._in_row = True
            self._cells = []
            self._row_attrs = attributes
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
            self._cell_attrs = attributes

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._cell_parts)).strip()
            self._cells.append({"text": text, "attrs": self._cell_attrs})
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if any(cell["text"] for cell in self._cells):
                self.rows.append({"attrs": self._row_attrs, "cells": self._cells})
            self._in_row = False
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0 and self.table_id:
                self._active = False
        elif tag == "tbody" and self.tbody_id and self._active and not self.table_id:
            self._active = False

    def handle_data(self, data):
        if self._in_cell:
            self._cell_parts.append(data)


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def parse_int(value: str) -> int:
    cleaned = value.replace(",", "").strip()
    if not re.fullmatch(r"-?\d+", cleaned):
        raise ValueError(f"not an integer published by Elections BC: {value!r}")
    return int(cleaned)


def share_text(value: str) -> str:
    cleaned = value.replace("%", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        raise ValueError(f"not a percentage published by Elections BC: {value!r}")
    return f"{cleaned}%"


def slugify(name: str) -> str:
    slug = name.lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


def as_of_text(html: str) -> str:
    match = re.search(r"As of\s+([^<]+)", html)
    if not match:
        raise ValueError("the official page did not include an 'As of' time")
    return re.sub(r"\s+", " ", match.group(1)).strip()


def stage_from(html: str) -> dict:
    initial = re.search(
        r'href="([^"]+_init_saved\.html)"[^>]*>\s*INITIAL COUNT\s*</a>[\s\S]{0,400}?'
        r'class="small-line">\s*([^<]+)',
        html,
    )
    final = re.search(
        r'class="main-line">\s*FINAL COUNT\s*</div>[\s\S]{0,400}?class="small-line">\s*([^<]+)',
        html,
    )
    if not initial or not final:
        raise ValueError("could not read the initial-count and final-count status")
    return {
        "initial_count": {
            "label": "Initial count",
            "status": re.sub(r"\s+", " ", initial.group(2)).strip(),
            "snapshot_url": initial.group(1),
        },
        "final_count": {
            "label": "Final count",
            "status": re.sub(r"\s+", " ", final.group(1)).strip(),
        },
    }


def summary_from(html: str) -> dict:
    block = re.search(r'id="divInfoTable"(.*?)</div>\s*</div>\s*</div>\s*</div>', html, re.S)
    if not block:
        raise ValueError("the official page did not include the provincial summary block")
    pairs = re.findall(
        r'class="main-line">\s*([^<]+?)\s*</div>\s*</div>\s*<div class="small-line">\s*([^<]+?)\s*</div>',
        block.group(1),
    )
    found = {re.sub(r"\s+", " ", label).strip(): re.sub(r"\s+", " ", value).strip() for value, label in pairs}
    expected = {
        "Of ballot boxes reporting",
        "Preliminary Voter Turnout",
        "Total Votes Considered",
        "Registered voters as of October 14, 2026",
    }
    if set(found) != expected:
        raise ValueError(f"unexpected provincial summary labels: {sorted(found)}")
    hidden = "display:none" in html[html.find('id="divInfoTable"') - 80 : html.find('id="divInfoTable"') + 20]
    return {
        "ballot_boxes_reporting": found["Of ballot boxes reporting"],
        "preliminary_voter_turnout": found["Preliminary Voter Turnout"],
        "total_votes_considered": parse_int(found["Total Votes Considered"]),
        "registered_voters": parse_int(found["Registered voters as of October 14, 2026"]),
        "registered_voters_as_of": "October 14, 2026",
        "summary_block_hidden_in_page_style": hidden,
    }


def parties_from(html: str) -> list[dict]:
    parser = TableParser(tbody_id="partyTableBody")
    parser.feed(html)
    parties = []
    for row in parser.rows:
        cells = [cell["text"] for cell in row["cells"]]
        if len(cells) < 4:
            continue
        name, _bar, leading, votes, *share_parts = cells
        if name in {"Party", "View More"} or not share_parts:
            continue
        share = share_text(share_parts[0])
        parties.append(
            {
                "name": name,
                "districts_leading": parse_int(leading),
                "votes": parse_int(votes),
                "vote_share": share,
            }
        )
    if not parties:
        raise ValueError("no party rows were found")
    return parties


def party_columns_from(html: str) -> dict[str, dict]:
    parser = TableParser(table_id="tblReport")
    parser.feed(html)
    districts = {}
    for row in parser.rows:
        cells = [cell["text"] for cell in row["cells"]]
        if len(cells) != 9:
            continue
        name, green, ndp, conservative, other, valid, rejected, considered, status = cells
        if name not in row["attrs"].get("data-ed", ""):
            continue
        districts[name] = {
            "GP": parse_int(green),
            "NDP": parse_int(ndp),
            "CP": parse_int(conservative),
            "Other": parse_int(other),
            "total_valid_votes": parse_int(valid),
            "rejected_ballots": parse_int(rejected),
            "total_considered_votes": parse_int(considered),
            "status": status,
        }
    if not districts:
        raise ValueError("no district rows were found on the party report")
    return districts


def candidates_from(html: str) -> dict[str, dict]:
    parser = TableParser(table_id="tblReport")
    parser.feed(html)
    districts: dict[str, dict] = {}
    for row in parser.rows:
        name = row["attrs"].get("data-ed", "").strip()
        if not name or name.startswith("'"):
            continue
        cells = row["cells"]
        texts = [cell["text"] for cell in cells]
        if len(texts) == 1 and texts[0].startswith("Status"):
            status = texts[0].split("|", 1)[-1].strip()
            districts.setdefault(name, {"candidates": [], "status": None})["status"] = status
            continue
        if len(texts) < 4:
            continue
        label = texts[1]
        record = districts.setdefault(
            name,
            {"candidates": [], "status": None},
        )
        if label == "Total Valid Votes":
            record["total_valid_votes"] = parse_int(texts[3])
            record["total_valid_share"] = share_text(texts[4]) if len(texts) > 4 else None
        elif label.startswith("Rejected Ballots"):
            record["rejected_ballots"] = parse_int(texts[3])
            record["rejected_share"] = share_text(texts[4]) if len(texts) > 4 else None
        elif label == "Total Considered Votes":
            record["total_considered_votes"] = parse_int(texts[3])
            record["total_considered_share"] = share_text(texts[4]) if len(texts) > 4 and texts[4] else None
        elif label:
            ballot_name = cells[1]["attrs"].get("data-canname", "").strip() or label
            if ballot_name != label:
                raise ValueError(f"{name}: ballot name {ballot_name!r} does not match the visible name {label!r}")
            printed_affiliation = texts[2]
            record["candidates"].append(
                {
                    "ballot_name": ballot_name,
                    # A blank cell is how the candidate report shows an unaffiliated candidate.
                    "affiliation": printed_affiliation or "Unaffiliated",
                    "affiliation_blank_on_candidate_report": printed_affiliation == "",
                    "votes": parse_int(texts[3]),
                    "share": share_text(texts[4]),
                }
            )
    return districts


def build_districts(candidate_rows: dict, party_rows: dict, boundary_lookup: dict[str, dict]) -> list[dict]:
    if set(candidate_rows) != set(party_rows):
        raise ValueError("the candidate report and the party report list different districts")
    districts = []
    for name in sorted(candidate_rows):
        source = candidate_rows[name]
        columns = party_rows[name]
        required = [
            "candidates",
            "total_valid_votes",
            "rejected_ballots",
            "total_considered_votes",
            "total_considered_share",
            "status",
        ]
        missing = [key for key in required if source.get(key) in (None, [])]
        if missing:
            raise ValueError(f"{name}: the candidate report is missing {', '.join(missing)}")
        for key in ("total_valid_votes", "rejected_ballots", "total_considered_votes", "status"):
            if source[key] != columns[key]:
                raise ValueError(f"{name}: {key} differs between the candidate report and the party report")
        ranking = sorted(source["candidates"], key=lambda item: (-item["votes"], item["ballot_name"]))
        top_votes = ranking[0]["votes"]
        tied = [candidate for candidate in ranking if candidate["votes"] == top_votes]
        leading = None
        tied_public = None
        if len(tied) == 1 and len(ranking) > 1:
            leading = {
                "ballot_name": tied[0]["ballot_name"],
                "affiliation": tied[0]["affiliation"],
                "votes": tied[0]["votes"],
                "share": tied[0]["share"],
                "margin": tied[0]["votes"] - ranking[1]["votes"],
            }
        elif len(tied) > 1:
            tied_public = [
                {
                    "ballot_name": candidate["ballot_name"],
                    "affiliation": candidate["affiliation"],
                    "votes": candidate["votes"],
                    "share": candidate["share"],
                }
                for candidate in tied
            ]
        geography = boundary_lookup.get(name, {})
        districts.append(
            {
                "name": name,
                "slug": slugify(name),
                "abbreviation": geography.get("abbreviation"),
                "electoral_district_id": geography.get("electoral_district_id"),
                "status": source["status"],
                "candidates": source["candidates"],
                "total_valid_votes": source["total_valid_votes"],
                "total_valid_share": source["total_valid_share"],
                "rejected_ballots": source["rejected_ballots"],
                "rejected_share": source["rejected_share"],
                "total_considered_votes": source["total_considered_votes"],
                "total_considered_share": source.get("total_considered_share"),
                "party_columns": {
                    "GP": columns["GP"],
                    "NDP": columns["NDP"],
                    "CP": columns["CP"],
                    "Other": columns["Other"],
                },
                "leading": leading,
                "tied": tied_public,
            }
        )
    return districts


def boundary_lookup_from(payload: dict) -> dict[str, dict]:
    lookup = {}
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        name = properties.get("ED_NAME")
        if not name:
            continue
        lookup[name] = {
            "abbreviation": properties.get("ED_ABBREVIATION"),
            "electoral_district_id": properties.get("ELECTORAL_DISTRICT_ID"),
        }
    return lookup


def write_json(path: Path, payload: dict | list, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2 if pretty else None)
        handle.write("\n")
    temporary.replace(path)


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "--skip-boundaries",
        action="store_true",
        help="refresh the results snapshot without downloading district boundaries",
    )
    args = argument_parser.parse_args()

    print("Downloading the Elections BC candidate report")
    candidate_html = fetch(CANDIDATE_URL)
    print("Downloading the Elections BC party report")
    party_html = fetch(PARTY_URL)

    candidate_as_of = as_of_text(candidate_html)
    party_as_of = as_of_text(party_html)
    if candidate_as_of != party_as_of:
        raise SystemExit(
            f"The official pages are not from the same update ({candidate_as_of} vs {party_as_of})."
        )

    candidate_stage = stage_from(candidate_html)
    party_stage = stage_from(party_html)
    if (
        candidate_stage["initial_count"]["status"] != party_stage["initial_count"]["status"]
        or candidate_stage["final_count"] != party_stage["final_count"]
    ):
        raise SystemExit("The official pages disagree about whether final count is finished.")
    summary = summary_from(party_html)
    if summary_from(candidate_html) != summary:
        raise SystemExit("The official pages disagree about the provincial summary.")

    parties = parties_from(party_html)
    if parties_from(candidate_html) != parties:
        raise SystemExit("The official pages disagree about the provincial party totals.")

    retrieved_at = datetime.now(PACIFIC).replace(microsecond=0).isoformat()
    boundaries_payload = None
    boundary_meta = {
        "included": False,
        "dataset": "Provincial Electoral Districts - Electoral Boundaries Redistribution, 2023",
        "catalogue_url": CATALOGUE_URL,
        "feature_layer": "WHSE_ADMIN_BOUNDARIES.EBC_ELECTORAL_DISTS_BS11_SVW",
        "service_url": (
            "https://delivery.maps.gov.bc.ca/arcgis/rest/services/whse/"
            "bcgw_pub_whse_admin_boundaries/MapServer/74"
        ),
        "licence_name": "Elections BC Open Data Licence",
        "licence_url": LICENCE_URL,
        "attribution": "Contains information licenced under the Elections BC Open Data Licence",
    }
    gaps = []

    if args.skip_boundaries:
        gaps.append(
            "District boundaries were not downloaded on this run. "
            "The map was left unchanged if a boundary file was already present."
        )
        if BOUNDARIES_PATH.exists():
            boundaries_payload = json.loads(BOUNDARIES_PATH.read_text(encoding="utf-8"))
            boundary_meta["included"] = True
    else:
        print("Downloading electoral district boundaries from the B.C. Geographic Warehouse")
        raw_boundaries = fetch_bytes(BOUNDARY_URL)
        boundaries_payload = json.loads(raw_boundaries)
        boundary_meta.update(
            {
                "included": True,
                "retrieved_at": retrieved_at,
                "out_sr": "EPSG:4326",
                "geometry_precision": 5,
                "max_allowable_offset_degrees": 0.002,
                "query_url": BOUNDARY_URL,
                "note": (
                    "Coordinates come from the official boundary layer. The warehouse "
                    "generalized them for this file using maxAllowableOffset of 0.002 "
                    "degrees and five decimal places. The shapes are for browsing "
                    "district names. Elections BC says this spatial data must not be "
                    "used to determine a voter's electoral district."
                ),
            }
        )

    geography = boundary_lookup_from(boundaries_payload) if boundaries_payload else {}
    districts = build_districts(candidates_from(candidate_html), party_columns_from(party_html), geography)
    summary["total_valid_votes"] = sum(district["total_valid_votes"] for district in districts)

    results = {
        "election": {
            "name": "2026 Provincial General Election",
            "jurisdiction": "British Columbia",
            "final_voting_day": "2026-10-24",
            "event_number": "11684",
            "report_code": "GE-2026-10-24",
        },
        "provenance": {
            "source": "Elections BC",
            "as_of_text": candidate_as_of,
            "retrieved_at": retrieved_at,
            "candidate_results_url": CANDIDATE_URL,
            "party_results_url": PARTY_URL,
            "initial_candidate_results_url": INITIAL_CANDIDATE_URL,
            "initial_party_results_url": INITIAL_PARTY_URL,
            "live_results_url": LIVE_URL,
            "election_page_url": "https://elections.bc.ca/2026-provincial-election/",
            "final_count_notice_url": "https://elections.bc.ca/news/update-on-preparations-for-final-count/",
            "maps_page_url": "https://elections.bc.ca/resources/maps/provincial-maps/",
            "spatial_data_page_url": "https://elections.bc.ca/resources/maps/gis-spatial-data/",
            "counting_processes_url": "https://electionsbcenr.blob.core.windows.net/electionsbcenr/counting-processes.pdf",
            "boundaries": boundary_meta,
            "rejected_ballot_note": (
                "Rejected ballots are ballots that cannot be counted because they were "
                "not marked clearly for one candidate."
            ),
            "party_column_note": (
                "On the party report, GP is the BC Green Party, NDP is the BC NDP, "
                "and CP is the Conservative Party. Other is every remaining affiliation, "
                "including independent and unaffiliated candidates."
            ),
            "share_note": (
                "A candidate's published share is that candidate's votes divided by all "
                "votes considered in the district, including rejected ballots. The party "
                "table's share of the vote is the share printed by Elections BC."
            ),
            "margin_note": (
                "The margin is the difference between the two highest published totals "
                "in a district. Elections BC does not print that difference."
            ),
            "affiliation_note": (
                "Some candidate rows have a blank affiliation cell. Those votes match "
                "the Unaffiliated line on the party report, and they are labelled "
                "Unaffiliated here. The candidate report says Christian Heritage Party "
                "of BC. The party report says Christian Heritage Party of B.C. The vote "
                "totals match."
            ),
            "gaps": gaps,
        },
        "stage": candidate_stage,
        "summary": summary,
        "parties": parties,
        "districts": districts,
    }

    errors = validate(results, boundaries_payload if boundary_meta["included"] else None)
    if errors:
        print("The official tables did not reconcile. The snapshot was not replaced.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    write_json(RESULTS_PATH, results)
    if boundaries_payload is not None and not args.skip_boundaries:
        write_json(BOUNDARIES_PATH, boundaries_payload, pretty=False)
    print(
        f"Wrote {len(districts)} districts. Elections BC time: {candidate_as_of}. "
        f"Retrieved {retrieved_at}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
