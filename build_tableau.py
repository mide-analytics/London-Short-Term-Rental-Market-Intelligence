"""Build the packaged London Tableau workbook and its local Hyper extract."""

import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed"
BUILD = ROOT / "data" / "tableau-build"
OUTPUT = ROOT / "tableau"
TITLE = "London Short-Term Rental Market Intelligence"
SOURCE = "hyper.londonairbnb"
CAPTION = "Inside Airbnb London"
USER = "http://www.tableausoftware.com/xml/user"
EXTRACT = "Data/London Airbnb.hyper"

FIELDS = {
    "ListingID": ("string", "Listing ID"), "HostID": ("string", "Host ID"),
    "Neighbourhood": ("string", "Neighbourhood"), "RoomType": ("string", "Room type"),
    "NightlyPrice": ("real", "Advertised nightly price"), "Rating": ("real", "Listing rating"),
    "HostListings": ("integer", "Host listing count"), "CalendarMonth": ("date", "Calendar month"),
    "ReviewMonth": ("date", "Review month"), "Observed": ("integer", "Observed nights"),
    "Available": ("integer", "Available nights"), "Reviews": ("integer", "Reviews"),
}
METRICS = {
    "ListingCount": ("Listing count", "COUNT([ListingID])", "#,##0"),
    "MedianPrice": ("Median nightly price", "MEDIAN([NightlyPrice])", 'c"£"#,##0.00;-"£"#,##0.00'),
    "PriceCoverage": ("Price coverage", "COUNT([NightlyPrice]) / COUNT([ListingID])", "p0.0%"),
    "HostCount": ("Host count", "COUNTD([HostID])", "#,##0"),
    "MultiHosts": ("Multi-listing hosts", "COUNTD(IF [HostListings] >= 2 THEN [HostID] END)", "#,##0"),
    "MultiHostShare": ("Multi-listing host share", "COUNTD(IF [HostListings] >= 2 THEN [HostID] END) / COUNTD([HostID])", "p0.0%"),
    "MultiSupply": ("Multi-listing host listings", "COUNT(IF [HostListings] >= 2 THEN [ListingID] END)", "#,##0"),
    "MultiSupplyShare": ("Multi-listing supply share", "COUNT(IF [HostListings] >= 2 THEN [ListingID] END) / COUNT([ListingID])", "p0.0%"),
    "Availability": ("Calendar availability", "SUM([Available]) / SUM([Observed])", "p0.0%"),
    "NightCount": ("Observed listing nights", "SUM([Observed])", "#,##0"),
    "ReviewCount": ("Review records", "SUM([Reviews])", "#,##0"),
    "AvgRating": ("Average listing rating", "ROUND(AVG([Rating]), 2)", "0.00"),
}


def read_csv(name):
    with (DATA / name).open(encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def extract_rows():
    dimensions = {}
    for row in read_csv("listings.csv"):
        key = row["listing_id"]
        group = row["neighbourhood_cleansed"], row["room_type"]
        dimensions[key] = group
        yield (
            key, row["host_id"] or None, *group,
            float(row["advertised_nightly_gbp"]) if row["advertised_nightly_gbp"] else None,
            float(row["review_scores_rating"]) if row["review_scores_rating"] else None,
            int(row["host_listing_count"]) if row["host_listing_count"] else None,
            None, None, None, None, None,
        )
    calendar = defaultdict(lambda: [0, 0])
    for row in read_csv("calendar_monthly.csv"):
        key = (*dimensions[row["listing_id"]], row["month"])
        calendar[key][0] += int(row["observed_nights"])
        calendar[key][1] += int(row["available_nights"])
    for (area, room, month), (observed, available) in calendar.items():
        yield None, None, area, room, None, None, None, date.fromisoformat(month), None, observed, available, None
    reviews = defaultdict(int)
    for row in read_csv("reviews_monthly.csv"):
        key = (*dimensions[row["listing_id"]], row["month"])
        reviews[key] += int(row["review_count"])
    for (area, room, month), count in reviews.items():
        yield None, None, area, room, None, None, None, None, date.fromisoformat(month), None, None, count


def build_extract(path):
    sys.path.insert(0, str(ROOT / "data" / "tableau-deps"))
    from tableauhyperapi import Connection, CreateMode, HyperProcess, Inserter, SqlType, TableDefinition, TableName, Telemetry

    types = {"string": SqlType.text(), "real": SqlType.double(), "integer": SqlType.big_int(), "date": SqlType.date()}
    table = TableDefinition(TableName("Extract", "Extract"), [
        TableDefinition.Column(key, types[dtype]) for key, (dtype, _) in FIELDS.items()
    ])
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_dir": str(BUILD)}) as hyper:
        with Connection(hyper.endpoint, path, CreateMode.CREATE_AND_REPLACE) as connection:
            connection.catalog.create_schema("Extract")
            connection.catalog.create_table(table)
            with Inserter(connection, table) as inserter:
                inserter.add_rows(extract_rows())
                inserter.execute()
            totals = connection.execute_list_query("""
                SELECT COUNT("ListingID"), COUNT(DISTINCT "HostID"),
                    COUNT(DISTINCT CASE WHEN "HostListings" >= 2 THEN "HostID" END),
                    SUM("Observed"), SUM("Available"), SUM("Reviews")
                FROM "Extract"."Extract"
            """)
            print("Extract totals (listings, hosts, multi-hosts, observed, available, reviews):", totals)


def element(parent, tag, **attributes):
    return ET.SubElement(parent, tag, {key.rstrip("_").replace("_", "-"): str(value) for key, value in attributes.items()})


def uid(parent):
    element(parent, "simple-id", uuid="{" + str(uuid4()).upper() + "}")


def define_column(parent, key):
    if key in METRICS:
        caption, formula, fmt = METRICS[key]
        column = element(parent, "column", name=f"[{key}]", caption=caption, datatype="real",
                         default_format=fmt, role="measure", type="quantitative")
        element(column, "calculation", class_="tableau", formula=formula)
        return
    dtype, caption = FIELDS[key]
    dimension = dtype in {"string", "date"}
    element(parent, "column", name=f"[{key}]", caption=caption, datatype=dtype,
            role="dimension" if dimension else "measure",
            type={"string": "nominal", "date": "ordinal"}.get(dtype, "quantitative"))


def build_workbook(path):
    ET.register_namespace("user", USER)
    root = ET.Element("workbook", {"original-version": "18.1", "version": "18.1",
                                  "source-build": "2026.3.0 (20263.26.1022.1645)", "source-platform": "win"})
    manifest = element(root, "document-format-change-manifest")
    for feature in ("AccessibleZoneTabOrder", "SheetIdentifierTracking", "WindowsPersistSimpleIdentifiers"):
        element(manifest, feature)
    source = element(element(root, "datasources"), "datasource", name=SOURCE, caption=CAPTION,
                     inline="true", version="18.1")
    connection = element(source, "connection", class_="hyper", dbname=EXTRACT, schema="Extract",
                         tablename="Extract", access_mode="readonly", authentication="auth-none",
                         default_settings="yes", username="tableau_internal_user")
    element(connection, "relation", name="Extract", table="[Extract].[Extract]", type="table")
    metadata = element(connection, "metadata-records")
    remote_types = {"string": 129, "real": 5, "integer": 20, "date": 133}
    for ordinal, (key, (dtype, _)) in enumerate(FIELDS.items()):
        record = element(metadata, "metadata-record", class_="column")
        for tag, value in {
            "remote-name": key, "remote-type": remote_types[dtype], "local-name": f"[{key}]",
            "parent-name": "[Extract]", "remote-alias": key, "ordinal": ordinal, "local-type": dtype,
            "aggregation": {"string": "Count", "date": "Year"}.get(dtype, "Sum"), "contains-null": "true",
        }.items():
            element(record, tag).text = str(value)
    for key in (*FIELDS, *METRICS):
        define_column(source, key)
    for key in ("Neighbourhood", "RoomType"):
        caption = f"Action ({FIELDS[key][1]})"
        group = element(source, "group", caption=caption, hidden="true", name=f"[{caption}]",
                        name_style="unqualified")
        group.set(f"{{{USER}}}auto-column", "sheet_link")
        element(element(group, "groupfilter", function="crossjoin"), "groupfilter",
                function="level-members", level=f"[{key}]")

    actions = element(root, "actions")
    sheets = element(root, "worksheets")
    dashboards = element(root, "dashboards")
    windows = element(root, "windows", source_height="800")

    def sheet(name, metric, category=None, trend=None, filters=()):
        work = element(sheets, "worksheet", name=name)
        table = element(work, "table")
        view = element(table, "view")
        element(element(view, "datasources"), "datasource", name=SOURCE, caption=CAPTION)
        deps = element(view, "datasource-dependencies", datasource=SOURCE)
        for key in (*FIELDS, metric):
            define_column(deps, key)

        def use(key, suffix, kind):
            measure = key in METRICS
            ref = f"[{'usr' if measure else 'none'}:{key}:{suffix}]"
            element(deps, "column-instance", column=f"[{key}]", name=ref, pivot="key", type=kind,
                    derivation="User" if measure else "None")
            return f"[{SOURCE}].{ref}"

        value = use(metric, "qk", "quantitative")
        category_ref = use(category, "nk", "nominal") if category else None
        month = use(f"{trend}Month", "qk", "quantitative") if trend else None
        filter_refs = []
        for dimension, action_name in filters:
            ref = f"[{SOURCE}].[Action ({FIELDS[dimension][1]})]"
            clause = element(view, "filter", class_="categorical", column=ref)
            group = element(clause, "groupfilter", function="level-members", level=f"[{dimension}]")
            group.attrib.update({f"{{{USER}}}ui-action-filter": action_name,
                                 f"{{{USER}}}ui-enumeration": "all", f"{{{USER}}}ui-marker": "enumerate"})
            filter_refs.append(ref)
        if month:
            element(view, "filter", class_="quantitative", column=month, included_values="non-null")
            filter_refs.append(month)
        if filter_refs:
            slices = element(view, "slices")
            for ref in filter_refs:
                element(slices, "column").text = ref
        element(view, "aggregation", value="true")
        element(table, "style")
        pane = element(element(table, "panes"), "pane", selection_relaxation_option="selection-relaxation-allow")
        element(element(pane, "view"), "breakdown", value="auto")
        mark = "Line" if trend else "Bar" if category else "Text"
        element(pane, "mark", class_=mark)
        if mark == "Text":
            element(element(pane, "encodings"), "text", column=value)
        style = element(element(pane, "style"), "style-rule", element="mark")
        element(style, "format", attr="color", value="#007E87")
        if mark == "Text":
            element(style, "format", attr="font-size", value="24")
            element(style, "format", attr="mark-labels-show", value="true")
        element(table, "rows").text = value if trend else category_ref
        element(table, "cols").text = month if trend else value if category else None
        uid(work)
        window = element(windows, "window", class_="worksheet", name=name, hidden="true")
        element(window, "cards")
        uid(window)

    def dashboard(name, cards, charts, description, selectors):
        action_ids = {}
        for selector, dimension in selectors.items():
            action_name = "[Action_" + uuid4().hex.upper() + "]"
            action_ids[dimension] = action_name
            action = element(actions, "action", caption=f"Filter by {FIELDS[dimension][1]}", name=action_name)
            element(action, "activation", type="on-select", auto_clear="true")
            element(action, "source", dashboard=name, type="sheet", worksheet=selector)
            command = element(action, "command", command="tsc:tsl-filter")
            element(command, "param", name="special-fields", value="all")
            element(command, "param", name="target", value=name)

        board = element(dashboards, "dashboard", name=name, enable_sort_zone_taborder="true")
        element(board, "style")
        element(board, "size", maxheight=760, minheight=760, maxwidth=1250, minwidth=1250)
        zones = element(element(board, "zones"), "zone", id=4, type_v2="layout-basic", x=0, y=0, w=100000, h=100000)
        for index, (label, y, height, size, color) in enumerate((
            (name, 500, 4900, 18, "#173F42"),
            (description, 5600, 3400, 10, "#416367"),
        ), 5):
            zone = element(zones, "zone", id=index, type_v2="text", x=1200, y=y, w=97600, h=height)
            element(element(zone, "formatted-text"), "run", fontsize=size, fontcolor=color).text = label

        win = element(windows, "window", class_="dashboard", name=name)
        viewpoints = element(win, "viewpoints")
        placements = [(title, metric, None, None, (1200 + index * 24500, 9100, 23900, 12000))
                      for index, (title, metric) in enumerate(cards)] + charts
        for index, (title, metric, category, trend, (x, y, width, height)) in enumerate(placements, 10):
            sheet(title, metric, category, trend, filters=[
                (dimension, key) for dimension, key in action_ids.items() if selectors.get(title) != dimension
            ])
            zone = element(zones, "zone", id=index, name=title, x=x, y=y, w=width, h=height)
            style = element(zone, "zone-style")
            element(style, "format", attr="margin", value="5")
            viewpoint = element(viewpoints, "viewpoint", name=title)
            if not category:
                element(viewpoint, "zoom", type="entire-view")
        element(win, "active", id=10)
        uid(win)
        uid(board)

    dashboard("London market overview", [
        ("Listings", "ListingCount"), ("Median nightly price", "MedianPrice"),
        ("Price coverage", "PriceCoverage"), ("Hosts", "HostCount"),
    ], [
        ("Listings by neighbourhood", "ListingCount", "Neighbourhood", None, (1200, 22200, 51000, 76600)),
        ("Listings by room type", "ListingCount", "RoomType", None, (53200, 22200, 45600, 36500)),
        ("Nightly price by room type", "MedianPrice", "RoomType", None, (53200, 60000, 45600, 38800)),
    ], "Inside Airbnb · September 2026 snapshot. Select a neighbourhood or room type to filter this dashboard.",
        {"Listings by neighbourhood": "Neighbourhood", "Listings by room type": "RoomType"})

    dashboard("Host concentration", [
        ("Distinct hosts", "HostCount"), ("Multi-listing hosts", "MultiHosts"),
        ("Multi-listing host share", "MultiHostShare"), ("Multi-host supply share", "MultiSupplyShare"),
    ], [
        ("Multi-listing supply by neighbourhood", "MultiSupply", "Neighbourhood", None, (1200, 22200, 51000, 76600)),
        ("Multi-listing host share by room type", "MultiHostShare", "RoomType", None, (53200, 22200, 45600, 76600)),
    ], "Multi-listing hosts have at least two listings across London. Select a bar to filter the dashboard.",
        {"Multi-listing supply by neighbourhood": "Neighbourhood", "Multi-listing host share by room type": "RoomType"})

    dashboard("Calendar and reviews", [
        ("Calendar availability", "Availability"), ("Observed listing nights", "NightCount"),
        ("Review records", "ReviewCount"), ("Average listing rating", "AvgRating"),
    ], [
        ("Filter by neighbourhood", "ListingCount", "Neighbourhood", None, (1200, 22200, 29500, 45000)),
        ("Filter by room type", "ListingCount", "RoomType", None, (1200, 68200, 29500, 30600)),
        ("Calendar availability by month", "Availability", None, "Calendar", (31700, 22200, 67100, 37500)),
        ("Review activity by month", "ReviewCount", None, "Review", (31700, 61000, 67100, 37800)),
    ], "Unavailable nights can include reservations and host blocks. Calendar edge months are partial.",
        {"Filter by neighbourhood": "Neighbourhood", "Filter by room type": "RoomType"})

    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def package_workbook(extract):
    workbook = BUILD / f"{TITLE}.twb"
    build_workbook(workbook)
    with ZipFile(OUTPUT / f"{TITLE}.twbx", "w", ZIP_DEFLATED) as package:
        package.write(workbook, workbook.name)
        package.write(extract, EXTRACT)


if __name__ == "__main__":
    BUILD.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    extract = BUILD / "London Airbnb.hyper"
    build_extract(extract)
    package_workbook(extract)
