(function () {
  "use strict";

  var RESULTS_URL = "data/results.json";
  var BOUNDARIES_URL = "data/districts.geojson";
  var PARTY_COLOURS = {
    "BC NDP": "#9a3412",
    "BC Green Party": "#166534",
    "Conservative Party": "#1e3a8a"
  };
  var numberFormat = new Intl.NumberFormat("en-CA");
  var app = document.getElementById("app");
  var status = document.getElementById("status");
  var state = { results: null, selected: "", query: "" };
  var applyingHash = false;

  function colourFor(party) {
    return PARTY_COLOURS[party] || "#4b5563";
  }

  function formatNumber(value) {
    return numberFormat.format(value);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function fetchJson(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error(url + " returned " + response.status);
      return response.json();
    });
  }

  function slugFromHash() {
    var match = decodeURIComponent(window.location.hash).match(/^#district\/([a-z0-9-]+)$/);
    return match ? match[1] : "";
  }

  function districtBySlug(slug) {
    var districts = state.results.districts;
    for (var i = 0; i < districts.length; i += 1) {
      if (districts[i].slug === slug) return districts[i];
    }
    return null;
  }

  function rankedCandidates(district) {
    return district.candidates.slice().sort(function (a, b) {
      return b.votes - a.votes || a.ballot_name.localeCompare(b.ballot_name, "en-CA");
    });
  }

  function leadSentence(district) {
    if (!district.leading) {
      if (district.tied && district.tied.length) {
        return "The highest published totals are tied. Elections BC has not declared a candidate elected.";
      }
      return "Elections BC has not declared a candidate elected.";
    }
    var ranked = rankedCandidates(district);
    var first = ranked[0];
    var second = ranked[1];
    var margin = formatNumber(district.leading.margin);
    if (!second) return first.ballot_name + " (" + first.affiliation + ") is the only candidate in this snapshot.";
    var secondVotes = second.votes;
    var tiedForSecond = ranked.filter(function (candidate) { return candidate.votes === secondVotes; });
    if (tiedForSecond.length > 1) {
      return first.ballot_name + " (" + first.affiliation + ") is ahead of the next published total by " + margin + " votes.";
    }
    return first.ballot_name + " (" + first.affiliation + ") leads " + second.ballot_name + " (" + second.affiliation + ") by " + margin + " votes.";
  }

  function matchesQuery(district, query) {
    if (!query) return true;
    var haystack = [district.name, district.abbreviation || ""].concat(district.candidates.map(function (candidate) {
      return candidate.ballot_name + " " + candidate.affiliation;
    })).join(" ").toLowerCase();
    return haystack.indexOf(query) !== -1;
  }

  function visibleDistricts() {
    return state.results.districts.filter(function (district) {
      return matchesQuery(district, state.query);
    });
  }

  function setHash(slug) {
    var next = slug ? "#district/" + slug : "";
    if (window.location.hash === next || (!slug && !window.location.hash)) return;
    applyingHash = true;
    if (slug) window.location.hash = "district/" + slug;
    else history.pushState(null, "", window.location.pathname + window.location.search);
  }

  function render() {
    var results = state.results;
    var provenance = results.provenance;
    app.replaceChildren();

    app.appendChild(renderNotice(results));
    app.appendChild(renderStats(results));
    app.appendChild(renderParties(results));
    app.appendChild(renderClosest(results));
    app.appendChild(renderMapHost());
    app.appendChild(renderLookup(results));
    app.appendChild(renderAbout(results));

    var selected = districtBySlug(state.selected);
    document.title = selected
      ? selected.name + " — 2026 British Columbia provincial election results"
      : "2026 British Columbia provincial election results";
    status.textContent = "Snapshot from Elections BC, as of " + provenance.as_of_text + ".";
  }

  function renderNotice(results) {
    var box = el("div", "notice");
    var stage = results.stage;
    box.appendChild(el("p", null, stage.final_count.label + " is " + stage.final_count.status.toLowerCase() + ". " + stage.initial_count.label + " is " + stage.initial_count.status.toLowerCase() + ". A candidate shown as leading has not been declared elected."));
    var links = el("p");
    var live = el("a", null, "Live Elections BC results");
    live.href = results.provenance.live_results_url;
    live.rel = "noopener";
    var initial = el("a", null, "Initial-count snapshot");
    initial.href = stage.initial_count.snapshot_url;
    initial.rel = "noopener";
    links.appendChild(live);
    links.appendChild(document.createTextNode(" · "));
    links.appendChild(initial);
    box.appendChild(links);
    return box;
  }

  function renderStats(results) {
    var summary = results.summary;
    var grid = el("section", "stats");
    grid.setAttribute("aria-label", "Provincial summary");
    [
      [summary.ballot_boxes_reporting, "Of ballot boxes reporting"],
      [summary.preliminary_voter_turnout, "Preliminary voter turnout"],
      [formatNumber(summary.total_votes_considered), "Total votes considered"],
      [formatNumber(summary.registered_voters), "Registered voters as of " + summary.registered_voters_as_of]
    ].forEach(function (pair) {
      var card = el("div", "stat");
      card.appendChild(el("strong", null, pair[0]));
      card.appendChild(el("span", "label", pair[1]));
      grid.appendChild(card);
    });
    return grid;
  }

  function renderParties(results) {
    var section = el("section", "panel");
    section.appendChild(el("h2", null, "Province-wide"));
    section.appendChild(el("p", "note", "Party order, districts leading, vote totals, and shares are copied from the Elections BC party report. The share is the percentage Elections BC printed. It matches that party's votes divided by all valid votes, to the nearest hundredth of a percent."));

    var barParties = results.parties.filter(function (party) { return party.districts_leading > 0; })
      .slice()
      .sort(function (a, b) { return b.districts_leading - a.districts_leading; });
    var bar = el("div", "bar");
    bar.setAttribute("aria-hidden", "true");
    barParties.forEach(function (party) {
      var segment = el("span");
      segment.style.width = (party.districts_leading / results.districts.length * 100) + "%";
      segment.style.background = colourFor(party.name);
      bar.appendChild(segment);
    });
    var mark = el("span", "majority");
    mark.style.left = (47 / results.districts.length * 100) + "%";
    bar.appendChild(mark);
    section.appendChild(bar);
    section.appendChild(el("p", "note", "The mark on the bar is 47 districts, a majority of 93. The colours show where a candidate is leading while final count is in progress."));

    var legend = el("ul", "legend");
    barParties.forEach(function (party) {
      var item = el("li");
      var swatch = el("span", "swatch");
      swatch.style.background = colourFor(party.name);
      swatch.setAttribute("aria-hidden", "true");
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(party.name + ", " + formatNumber(party.districts_leading) + " leading"));
      legend.appendChild(item);
    });
    section.appendChild(legend);

    var scroller = el("div", "table-scroll");
    var table = el("table");
    var caption = el("caption", null, "Votes and districts leading, by party");
    table.appendChild(caption);
    var thead = el("thead");
    var head = el("tr");
    ["Party", "Districts leading", "Votes", "Share of the vote"].forEach(function (label, index) {
      var cell = el("th", index ? "num" : null, label);
      if (index) cell.scope = "col";
      else cell.scope = "col";
      head.appendChild(cell);
    });
    thead.appendChild(head);
    table.appendChild(thead);
    var tbody = el("tbody");
    results.parties.forEach(function (party) {
      var row = el("tr");
      var nameCell = el("th");
      nameCell.scope = "row";
      var swatch = el("span", "swatch");
      swatch.style.background = colourFor(party.name);
      swatch.setAttribute("aria-hidden", "true");
      nameCell.appendChild(swatch);
      nameCell.appendChild(document.createTextNode(party.name));
      row.appendChild(nameCell);
      row.appendChild(el("td", "num", formatNumber(party.districts_leading)));
      row.appendChild(el("td", "num", formatNumber(party.votes)));
      row.appendChild(el("td", "num", party.vote_share));
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    scroller.appendChild(table);
    section.appendChild(scroller);
    return section;
  }

  function renderClosest(results) {
    var section = el("section", "panel");
    section.appendChild(el("h2", null, "Narrowest leads"));
    section.appendChild(el("p", "note", "The difference is calculated from the two highest totals Elections BC published. It will change if final count changes those totals."));
    var list = el("ol", "close-list");
    results.districts.filter(function (district) { return district.leading; })
      .slice()
      .sort(function (a, b) {
        return a.leading.margin - b.leading.margin || a.name.localeCompare(b.name, "en-CA");
      })
      .slice(0, 8)
      .forEach(function (district) {
        var item = el("li");
        var link = el("a", null, district.name);
        link.href = "#district/" + district.slug;
        item.appendChild(link);
        item.appendChild(document.createTextNode(": " + leadSentence(district)));
        list.appendChild(item);
      });
    section.appendChild(list);
    return section;
  }

  function renderMapHost() {
    var section = el("section", "panel");
    section.id = "map-section";
    section.appendChild(el("h2", null, "Electoral districts"));
    section.appendChild(el("p", "note", "The map is a visual aid. Boundaries are generalized from the official 2023 redistribution layer and must not be used to decide which district a voter lives in. Use the list to look a district up."));
    var frame = el("div", "map-frame");
    frame.id = "map-frame";
    section.appendChild(frame);
    return section;
  }

  function renderLookup(results) {
    var section = el("section", "panel");
    section.appendChild(el("h2", null, "Look up a district"));
    var tools = el("div", "lookup-tools");
    var field = el("div");
    var label = el("label", null, "District, candidate, or party");
    label.htmlFor = "district-search";
    var input = el("input");
    input.id = "district-search";
    input.type = "search";
    input.autocomplete = "off";
    input.value = state.query;
    input.setAttribute("aria-controls", "district-list");
    field.appendChild(label);
    field.appendChild(input);
    tools.appendChild(field);
    var clear = el("button", "text-button", "Clear search");
    clear.type = "button";
    clear.addEventListener("click", function () {
      state.query = "";
      input.value = "";
      updateLookup();
      input.focus();
    });
    tools.appendChild(clear);
    section.appendChild(tools);
    var count = el("p", "match-count");
    count.id = "match-count";
    count.setAttribute("aria-live", "polite");
    section.appendChild(count);

    var grid = el("div", "lookup");
    var list = el("ul", "district-list");
    list.id = "district-list";
    grid.appendChild(list);
    var detail = el("div", "detail");
    detail.id = "district-detail";
    grid.appendChild(detail);
    section.appendChild(grid);

    input.addEventListener("input", function () {
      state.query = input.value.trim().toLowerCase();
      updateLookup();
    });
    return section;
  }

  function renderAbout(results) {
    var provenance = results.provenance;
    var section = el("section", "panel");
    section.appendChild(el("h2", null, "About these figures"));
    section.appendChild(el("p", null, "Elections BC printed this report as of " + provenance.as_of_text + ". The files in this project were retrieved at " + provenance.retrieved_at + "."));
    if (results.summary.summary_block_hidden_in_page_style) {
      section.appendChild(el("p", null, "The provincial summary for ballot boxes, turnout, votes considered, and registered voters is in the official results file. The final-count page hides that block with a style rule. The votes-considered figure matches the sum of the district rows, so it is shown here with Elections BC's own labels."));
    }
    section.appendChild(el("p", null, provenance.rejected_ballot_note + " That wording is Elections BC's."));
    section.appendChild(el("p", null, provenance.party_column_note));
    section.appendChild(el("p", null, provenance.share_note));
    section.appendChild(el("p", null, provenance.margin_note));
    section.appendChild(el("p", null, provenance.affiliation_note));
    section.appendChild(el("p", null, "On the Elections BC election page, final count is planned for 6 to 10 November 2026, and Return Day is 18 November 2026. The Statement of Votes for this election was not on the provincial results archive when this snapshot was taken, so there is no voting-area breakdown here."));

    var gaps = provenance.gaps || [];
    if (gaps.length) {
      var gapList = el("ul", "sources");
      gaps.forEach(function (gap) { gapList.appendChild(el("li", null, gap)); });
      section.appendChild(gapList);
    }

    var list = el("ul", "sources");
    [
      ["Event-night results", provenance.live_results_url],
      ["Results by candidate", provenance.candidate_results_url],
      ["Results by party", provenance.party_results_url],
      ["2026 provincial election", provenance.election_page_url],
      ["Final count notice", provenance.final_count_notice_url],
      ["Counting processes", provenance.counting_processes_url],
      ["Provincial maps", provenance.maps_page_url],
      ["GIS spatial data", provenance.spatial_data_page_url],
      ["2023 electoral district boundaries", provenance.boundaries.catalogue_url],
      ["Elections BC Open Data Licence", provenance.boundaries.licence_url],
      ["Packaged results file", RESULTS_URL],
      ["Packaged boundary file", BOUNDARIES_URL]
    ].forEach(function (pair) {
      var item = el("li");
      var link = el("a", null, pair[0]);
      link.href = pair[1];
      if (pair[1].indexOf("http") === 0) link.rel = "noopener";
      item.appendChild(link);
      list.appendChild(item);
    });
    section.appendChild(list);
    if (provenance.boundaries && provenance.boundaries.note) {
      section.appendChild(el("p", null, provenance.boundaries.note));
    }
    section.appendChild(el("p", null, provenance.boundaries.attribution + "."));
    return section;
  }

  function updateLookup() {
    var list = document.getElementById("district-list");
    var detail = document.getElementById("district-detail");
    var count = document.getElementById("match-count");
    var visible = visibleDistricts();
    var visibleSlugs = {};
    list.replaceChildren();
    visible.forEach(function (district) {
      visibleSlugs[district.slug] = true;
      var item = el("li");
      var button = el("button", "district-button");
      button.type = "button";
      button.setAttribute("aria-pressed", district.slug === state.selected ? "true" : "false");
      button.appendChild(el("span", null, district.name));
      var meta = district.leading
        ? district.leading.affiliation + " leading"
        : (district.tied ? "Tied" : district.status);
      button.appendChild(el("span", "meta", meta));
      button.addEventListener("click", function () {
        selectDistrict(district.slug, true);
      });
      item.appendChild(button);
      list.appendChild(item);
    });
    var noun = visible.length === 1 ? "district" : "districts";
    count.textContent = formatNumber(visible.length) + " " + noun;
    if (!visible.length) {
      list.appendChild(el("li", "empty", "No district or candidate matches that search."));
    }
    renderDetail(detail);
    document.querySelectorAll(".district-shape").forEach(function (path) {
      path.classList.toggle("is-dimmed", state.query && !visibleSlugs[path.getAttribute("data-slug")]);
      path.classList.toggle("is-selected", path.getAttribute("data-slug") === state.selected);
    });
  }

  function renderDetail(detail) {
    detail.replaceChildren();
    var district = districtBySlug(state.selected);
    if (!district) {
      detail.appendChild(el("p", "empty", "Select a district from the list or the map."));
      return;
    }
    var heading = el("h2", null, district.name);
    heading.tabIndex = -1;
    heading.id = "district-heading";
    detail.appendChild(heading);
    var statusLine = district.status + ".";
    if (district.abbreviation) statusLine += " Boundary-file abbreviation: " + district.abbreviation + ".";
    detail.appendChild(el("p", null, statusLine));
    detail.appendChild(el("p", null, leadSentence(district) + " Share of votes considered for the leading total: " + (district.leading ? district.leading.share : "not applicable") + "."));

    var scroller = el("div", "table-scroll");
    var table = el("table");
    table.appendChild(el("caption", null, "Candidates in " + district.name));
    var head = el("tr");
    ["Candidate", "Affiliation", "Votes", "Share of votes considered"].forEach(function (label) {
      var cell = el("th", label === "Candidate" || label === "Affiliation" ? null : "num", label);
      cell.scope = "col";
      head.appendChild(cell);
    });
    table.appendChild(el("thead")).appendChild(head);
    var body = el("tbody");
    district.candidates.forEach(function (candidate) {
      var row = el("tr");
      var leading = district.leading && candidate.ballot_name === district.leading.ballot_name;
      if (leading) row.className = "is-leading";
      var nameCell = el("th", null, candidate.ballot_name);
      nameCell.scope = "row";
      row.appendChild(nameCell);
      var affiliation = candidate.affiliation;
      if (candidate.affiliation_blank_on_candidate_report) {
        affiliation += " (blank on the candidate report)";
      }
      row.appendChild(el("td", null, affiliation));
      row.appendChild(el("td", "num", formatNumber(candidate.votes)));
      row.appendChild(el("td", "num", candidate.share));
      body.appendChild(row);
    });
    table.appendChild(body);
    scroller.appendChild(table);
    detail.appendChild(scroller);

    var totals = el("div", "table-scroll");
    var totalTable = el("table");
    totalTable.appendChild(el("caption", null, "District totals published by Elections BC"));
    var totalBody = el("tbody");
    [
      ["Total valid votes", formatNumber(district.total_valid_votes), district.total_valid_share],
      ["Rejected ballots", formatNumber(district.rejected_ballots), district.rejected_share],
      ["Total votes considered", formatNumber(district.total_considered_votes), district.total_considered_share || ""]
    ].forEach(function (rowData) {
      var row = el("tr");
      var label = el("th", null, rowData[0]);
      label.scope = "row";
      row.appendChild(label);
      row.appendChild(el("td", "num", rowData[1]));
      row.appendChild(el("td", "num", rowData[2]));
      totalBody.appendChild(row);
    });
    totalTable.appendChild(totalBody);
    totals.appendChild(totalTable);
    detail.appendChild(totals);

    detail.appendChild(el("h3", null, "Party columns on the party report"));
    var columns = el("p", null, "BC Green Party " + formatNumber(district.party_columns.GP) + ", BC NDP " + formatNumber(district.party_columns.NDP) + ", Conservative Party " + formatNumber(district.party_columns.CP) + ", other affiliations " + formatNumber(district.party_columns.Other) + ".");
    detail.appendChild(columns);
  }

  function selectDistrict(slug, focusHeading) {
    if (slug && !districtBySlug(slug)) slug = "";
    state.selected = slug;
    setHash(slug);
    updateLookup();
    if (focusHeading && slug) {
      var heading = document.getElementById("district-heading");
      if (heading) heading.focus();
    }
  }

  function drawMap(boundaries) {
    var frame = document.getElementById("map-frame");
    if (!boundaries || !boundaries.features) {
      frame.appendChild(el("p", "map-missing", "The boundary file is not available, so there is no map. The district list still uses the Elections BC results."));
      return;
    }
    var cos = Math.cos(54 * Math.PI / 180);
    function project(lon, lat) { return [lon * cos, -lat]; }

    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    function include(point) {
      var projected = project(point[0], point[1]);
      minX = Math.min(minX, projected[0]);
      maxX = Math.max(maxX, projected[0]);
      minY = Math.min(minY, projected[1]);
      maxY = Math.max(maxY, projected[1]);
    }
    boundaries.features.forEach(function (feature) {
      walkCoordinates(feature.geometry.coordinates, include);
    });
    var padX = (maxX - minX) * 0.03;
    var padY = (maxY - minY) * 0.03;
    var initial = { x: minX - padX, y: minY - padY, w: (maxX - minX) + padX * 2, h: (maxY - minY) + padY * 2 };
    var view = { x: initial.x, y: initial.y, w: initial.w, h: initial.h };

    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", "Map of British Columbia electoral districts");
    var group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    boundaries.features.forEach(function (feature) {
      var name = feature.properties.ED_NAME;
      var district = state.results.districts.filter(function (item) { return item.name === name; })[0];
      if (!district) return;
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", pathData(feature.geometry));
      path.setAttribute("data-slug", district.slug);
      path.setAttribute("fill", colourFor(district.leading ? district.leading.affiliation : ""));
      path.classList.add("district-shape");
      var title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = district.name;
      path.appendChild(title);
      group.appendChild(path);
    });
    svg.appendChild(group);
    frame.appendChild(svg);

    var controls = el("div", "map-controls");
    [["Zoom in", 0.75], ["Zoom out", 1.33], ["Show all", null]].forEach(function (item) {
      var button = el("button", null, item[0]);
      button.type = "button";
      button.addEventListener("click", function () {
        if (item[1] === null) view = { x: initial.x, y: initial.y, w: initial.w, h: initial.h };
        else zoom(item[1]);
        applyView();
      });
      controls.appendChild(button);
    });
    frame.appendChild(controls);

    function applyView() {
      svg.setAttribute("viewBox", view.x + " " + view.y + " " + view.w + " " + view.h);
    }
    function zoom(factor) {
      var rect = svg.getBoundingClientRect();
      zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
    }
    function zoomAt(clientX, clientY, factor) {
      var nextW = view.w * factor;
      if (nextW < initial.w / 18 || nextW > initial.w * 1.4) return;
      var point = clientToSvg(clientX, clientY);
      view.x = point.x - (point.x - view.x) * factor;
      view.y = point.y - (point.y - view.y) * factor;
      view.w = nextW;
      view.h = view.h * factor;
    }
    function clientToSvg(clientX, clientY) {
      var rect = svg.getBoundingClientRect();
      return {
        x: view.x + (clientX - rect.left) / rect.width * view.w,
        y: view.y + (clientY - rect.top) / rect.height * view.h
      };
    }
    function pathData(geometry) {
      var polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
      return polygons.map(function (polygon) {
        return polygon.map(function (ring) {
          return ring.map(function (point, index) {
            var projected = project(point[0], point[1]);
            return (index === 0 ? "M" : "L") + projected[0].toFixed(3) + " " + projected[1].toFixed(3);
          }).join("") + "Z";
        }).join("");
      }).join("");
    }
    function walkCoordinates(coordinates, visit) {
      if (typeof coordinates[0] === "number") visit(coordinates);
      else coordinates.forEach(function (part) { walkCoordinates(part, visit); });
    }

    var drag = null;
    svg.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, view: { x: view.x, y: view.y }, moved: false };
    });
    svg.addEventListener("pointermove", function (event) {
      if (!drag || drag.id !== event.pointerId) return;
      var dx = event.clientX - drag.x;
      var dy = event.clientY - drag.y;
      if (Math.hypot(dx, dy) > 4) drag.moved = true;
      var rect = svg.getBoundingClientRect();
      view.x = drag.view.x - dx * view.w / rect.width;
      view.y = drag.view.y - dy * view.h / rect.height;
      applyView();
    });
    function endDrag(event) {
      if (!drag || drag.id !== event.pointerId) return;
      var moved = drag.moved;
      drag = null;
      var path = event.target && event.target.closest ? event.target.closest("path[data-slug]") : null;
      if (!moved && path) selectDistrict(path.getAttribute("data-slug"), true);
    }
    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", function () { drag = null; });
    svg.addEventListener("wheel", function (event) {
      event.preventDefault();
      zoomAt(event.clientX, event.clientY, event.deltaY > 0 ? 1.12 : 0.89);
      applyView();
    }, { passive: false });

    applyView();
    updateLookup();
  }

  function showLoadError() {
    status.textContent = "";
    app.replaceChildren();
    var box = el("div", "notice");
    box.appendChild(el("p", null, "The results file did not load. From this project's folder, run python3 -m http.server 8080 and open the local address it prints. Opening the HTML file directly will not load the data."));
    var link = el("a", null, "Elections BC event-night results");
    link.href = "https://results.elections.bc.ca/";
    link.rel = "noopener";
    var paragraph = el("p");
    paragraph.appendChild(link);
    box.appendChild(paragraph);
    app.appendChild(box);
  }

  function onRoute() {
    if (applyingHash) {
      applyingHash = false;
      return;
    }
    var slug = slugFromHash();
    if (slug === state.selected) return;
    state.selected = slug;
    if (!state.results) return;
    updateLookup();
    var heading = document.getElementById("district-heading");
    if (heading) heading.focus();
  }

  window.addEventListener("hashchange", onRoute);
  window.addEventListener("popstate", onRoute);

  Promise.all([fetchJson(RESULTS_URL), fetchJson(BOUNDARIES_URL).catch(function () { return null; })])
    .then(function (files) {
      state.results = files[0];
      state.selected = slugFromHash();
      render();
      drawMap(files[1]);
      updateLookup();
    })
    .catch(showLoadError);
})();
