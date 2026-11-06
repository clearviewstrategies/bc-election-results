#!/usr/bin/env python3
"""Check a results snapshot for internal consistency.

The checks compare figures that Elections BC published in the same report.
They do not fill in missing numbers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "results.json"
BOUNDARIES_PATH = ROOT / "data" / "districts.geojson"

MAJOR_GROUPS = {
    "BC Green Party": "GP",
    "BC NDP": "NDP",
    "Conservative Party": "CP",
}

# The two official reports use these pairs for the same vote totals.
PARTY_NAME_ON_PARTY_REPORT = {
    "": "Unaffiliated",
    "Unaffiliated": "Unaffiliated",
    "Christian Heritage Party of BC": "Christian Heritage Party of B.C.",
    "Christian Heritage Party of B.C.": "Christian Heritage Party of B.C.",
}


def canonical_party_name(name: str) -> str:
    return PARTY_NAME_ON_PARTY_REPORT.get(name, name)


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def party_group(affiliation: str) -> str:
    return MAJOR_GROUPS.get(affiliation, "Other")


def validate(results: dict, boundaries: dict | None = None) -> list[str]:
    errors: list[str] = []
    districts = results.get("districts") or []
    parties = results.get("parties") or []
    names = [district["name"] for district in districts]
    if len(districts) != 93:
        errors.append(f"expected 93 electoral districts, found {len(districts)}")
    if len(names) != len(set(names)):
        errors.append("electoral district names are not unique")
    slugs = [district["slug"] for district in districts]
    if len(slugs) != len(set(slugs)):
        errors.append("electoral district slugs are not unique")

    affiliation_votes: dict[str, int] = {}
    computed_leads: dict[str, int] = {}
    considered_sum = 0
    valid_sum = 0

    for district in districts:
        label = district["name"]
        candidates = district["candidates"]
        if not candidates:
            errors.append(f"{label}: no candidates")
            continue
        votes = [candidate["votes"] for candidate in candidates]
        if sum(votes) != district["total_valid_votes"]:
            errors.append(f"{label}: candidate votes do not add up to total valid votes")
        if district["total_valid_votes"] + district["rejected_ballots"] != district["total_considered_votes"]:
            errors.append(f"{label}: valid votes plus rejected ballots do not equal votes considered")
        if district["total_valid_share"] is None or district["rejected_share"] is None:
            errors.append(f"{label}: missing an official share for valid or rejected ballots")

        grouped = {"GP": 0, "NDP": 0, "CP": 0, "Other": 0}
        for candidate in candidates:
            grouped[party_group(candidate["affiliation"])] += candidate["votes"]
            party_name = canonical_party_name(candidate["affiliation"])
            affiliation_votes[party_name] = affiliation_votes.get(party_name, 0) + candidate["votes"]
        published = district["party_columns"]
        for key in grouped:
            if grouped[key] != published[key]:
                errors.append(
                    f"{label}: {key} column {published[key]} does not match candidate votes {grouped[key]}"
                )
        if sum(published[key] for key in ("GP", "NDP", "CP", "Other")) != district["total_valid_votes"]:
            errors.append(f"{label}: party columns do not add up to total valid votes")

        ranking = sorted(candidates, key=lambda item: item["votes"], reverse=True)
        top = ranking[0]["votes"]
        tied = [candidate for candidate in ranking if candidate["votes"] == top]
        leading = district.get("leading")
        if len(tied) == 1:
            if leading is None:
                errors.append(f"{label}: a unique vote leader was not recorded")
            else:
                if leading["ballot_name"] != tied[0]["ballot_name"]:
                    errors.append(f"{label}: recorded leader does not have the most votes")
                if leading["margin"] != top - ranking[1]["votes"]:
                    errors.append(f"{label}: margin does not match the two highest totals")
                lead_name = canonical_party_name(tied[0]["affiliation"])
                computed_leads[lead_name] = computed_leads.get(lead_name, 0) + 1
        else:
            if leading is not None:
                errors.append(f"{label}: a tie was recorded as a single leader")
            if district.get("tied") is None or len(district["tied"]) != len(tied):
                errors.append(f"{label}: tie was not recorded")

        considered_sum += district["total_considered_votes"]
        valid_sum += district["total_valid_votes"]

    summary = results.get("summary") or {}
    if summary.get("total_votes_considered") != considered_sum:
        errors.append("provincial votes considered do not match the district table")
    if summary.get("total_valid_votes") != valid_sum:
        errors.append("provincial valid votes do not match the district table")

    party_votes = 0
    leading_sum = 0
    for party in parties:
        party_votes += party["votes"]
        leading_sum += party["districts_leading"]
        counted = affiliation_votes.get(party["name"])
        if counted != party["votes"]:
            errors.append(
                f"{party['name']}: published votes {party['votes']} do not match candidate totals {counted}"
            )
        lead_count = computed_leads.get(canonical_party_name(party["name"]), 0)
        if lead_count != party["districts_leading"]:
            errors.append(
                f"{party['name']}: published districts leading {party['districts_leading']} "
                f"does not match the candidate totals {lead_count}"
            )
    if party_votes != valid_sum:
        errors.append("party vote totals do not add up to valid votes")
    if leading_sum != len(districts):
        errors.append("districts-leading column does not add up to the number of districts")
    extra_affiliations = set(affiliation_votes) - {party["name"] for party in parties}
    if extra_affiliations:
        errors.append(f"candidate affiliations missing from the party table: {sorted(extra_affiliations)}")

    if boundaries is not None:
        features = boundaries.get("features") or []
        boundary_names = [feature["properties"]["ED_NAME"] for feature in features]
        if len(boundary_names) != 93:
            errors.append(f"expected 93 boundary features, found {len(boundary_names)}")
        if set(boundary_names) != set(names):
            missing = sorted(set(names) - set(boundary_names))
            extra = sorted(set(boundary_names) - set(names))
            errors.append(f"boundary names do not match results (missing {missing}, extra {extra})")
        for feature in features:
            geometry = feature.get("geometry") or {}
            if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                errors.append(f"{feature['properties'].get('ED_NAME')}: missing polygon geometry")

    return errors


def main() -> int:
    if not RESULTS_PATH.exists():
        print(f"Missing {RESULTS_PATH}", file=sys.stderr)
        return 1
    results = load_json(RESULTS_PATH)
    boundaries = load_json(BOUNDARIES_PATH) if BOUNDARIES_PATH.exists() else None
    if boundaries is None:
        print("No boundary file is present. District lookup will not include a map.")
    errors = validate(results, boundaries)
    if errors:
        print("Results snapshot failed these checks:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Checked {len(results['districts'])} districts and "
        f"{len(results['parties'])} parties against the packaged snapshot."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
