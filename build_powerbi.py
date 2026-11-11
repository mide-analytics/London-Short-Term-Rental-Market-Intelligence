"""Generate the London Power BI project from its prepared CSVs."""

import json
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "powerbi"
NAME = "London Short-Term Rental Market Intelligence"
MODEL = OUTPUT / f"{NAME}.SemanticModel"
REPORT = OUTPUT / f"{NAME}.Report"
DEFINITION = REPORT / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"


def save(path, value, schema=None):
    if schema:
        value = {"$schema": f"{SCHEMA}/{schema}/schema.json", **value}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def quoted(text):
    return '"' + text.replace('"', '""') + '"'


def lineage(name):
    return str(uuid5(NAMESPACE_URL, f"{NAME}/{name}"))


def import_table(name, filename, fields):
    source = quoted(str(ROOT / "data" / "processed" / filename))
    types = ", ".join(f'{{"{field}", {mtype}}}' for field, _, mtype in fields)
    columns = []
    for field, dtype, _ in fields:
        label = field.replace("_", " ").title().replace("Id", "ID").replace("Gbp", "GBP")
        if field == "neighbourhood_cleansed":
            label = "Neighbourhood"
        columns.append({
            "name": label, "sourceColumn": field, "dataType": dtype,
            "summarizeBy": "none", "lineageTag": lineage(f"{name}/{field}"),
            **({"isHidden": True} if field in {"listing_id", "host_id"} else {}),
            **({"formatString": "MMM yyyy"} if field == "month" else {}),
        })
    return {
        "name": name, "columns": columns, "lineageTag": lineage(name),
        "annotations": [{"name": "PBI_ResultType", "value": "Table"}],
        "partitions": [{"name": name, "mode": "import", "source": {
            "type": "m", "expression": [
                "let",
                f'    Source = Csv.Document(File.Contents({source}), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
                "    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
                f'    Typed = Table.TransformColumnTypes(Headers, {{{types}}}, "en-GB")',
                "in Typed",
            ],
        }}],
    }


TEXT = ("string", "type text")
INTEGER = ("int64", "Int64.Type")
DATE = ("dateTime", "type date")
DECIMAL = ("double", "type number")
CURRENCY = ("decimal", "Currency.Type")


def measure(name, expression, fmt="#,0"):
    return {"name": name, "expression": expression, "formatString": fmt}


def build_model():
    listings = import_table("Listings", "listings.csv", [
        ("listing_id", *TEXT), ("advertised_nightly_gbp", *CURRENCY), ("host_id", *TEXT),
        ("neighbourhood_cleansed", *TEXT), ("room_type", *TEXT),
        ("latitude", *DECIMAL), ("longitude", *DECIMAL), ("accommodates", *INTEGER),
        ("minimum_nights", *INTEGER), ("review_scores_rating", *DECIMAL),
        ("number_of_reviews", *INTEGER), ("host_listing_count", *INTEGER),
    ])
    listings["measures"] = [
        measure("Listing count", "COUNTROWS('Listings')"),
        measure("Median nightly price", "MEDIAN('Listings'[Advertised Nightly GBP])", "£#,0.00"),
        measure("Price coverage", "DIVIDE(COUNT('Listings'[Advertised Nightly GBP]), [Listing count])", "0.0%"),
        measure("Host count", "DISTINCTCOUNTNOBLANK('Listings'[Host ID])"),
        measure("Multi-listing hosts", "CALCULATE([Host count], KEEPFILTERS('Listings'[Host Listing Count] >= 2))"),
        measure("Multi-listing host share", "DIVIDE([Multi-listing hosts], [Host count])", "0.0%"),
        measure("Multi-listing host listings", "CALCULATE([Listing count], KEEPFILTERS('Listings'[Host Listing Count] >= 2))"),
        measure("Share of listings from multi-listing hosts", "DIVIDE([Multi-listing host listings], [Listing count])", "0.0%"),
        measure("Average listing rating", "AVERAGE('Listings'[Review Scores Rating])", "0.00"),
    ]
    calendar = import_table("Calendar Monthly", "calendar_monthly.csv", [
        ("listing_id", *TEXT), ("month", *DATE), ("observed_nights", *INTEGER), ("available_nights", *INTEGER),
    ])
    calendar["measures"] = [
        measure("Observed listing nights", "SUM('Calendar Monthly'[Observed Nights])"),
        measure("Available listing nights", "SUM('Calendar Monthly'[Available Nights])"),
        measure("Calendar availability", "DIVIDE([Available listing nights], [Observed listing nights])", "0.0%"),
    ]
    reviews = import_table("Reviews Monthly", "reviews_monthly.csv", [
        ("listing_id", *TEXT), ("month", *DATE), ("review_count", *INTEGER),
    ])
    reviews["measures"] = [measure("Review records", "SUM('Reviews Monthly'[Review Count])")]
    save(MODEL / "model.bim", {
        "name": NAME, "compatibilityLevel": 1600,
        "model": {
            "culture": "en-GB", "sourceQueryCulture": "en-GB",
            "defaultPowerBIDataSourceVersion": "powerBI_V3", "discourageImplicitMeasures": True,
            "annotations": [
                {"name": "PBI_QueryOrder", "value": json.dumps(["Listings", "Calendar Monthly", "Reviews Monthly"])},
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
            ],
            "tables": [listings, calendar, reviews],
            "relationships": [
                {"name": f"{table} to Listings", "fromTable": table, "fromColumn": "Listing ID",
                 "toTable": "Listings", "toColumn": "Listing ID", "crossFilteringBehavior": "oneDirection"}
                for table in ("Calendar Monthly", "Reviews Monthly")
            ],
        },
    })
    save(MODEL / "definition.pbism", {"version": "4.0", "settings": {}},
         "item/semanticModel/definitionProperties/1.0.0")


def literal(value):
    return {"expr": {"Literal": {"Value": value}}}


def field(entity, property_name, kind="Column"):
    return {
        "field": {kind: {"Expression": {"SourceRef": {"Entity": entity}}, "Property": property_name}},
        "queryRef": f"{entity}.{property_name}",
        "nativeQueryRef": property_name,
    }


class Page:
    def __init__(self, title, subtitle):
        self.name = self.key(title)
        self.directory = DEFINITION / "pages" / self.name
        self.order = 0
        save(self.directory / "page.json", {
            "name": self.name, "displayName": title, "displayOption": "FitToPage",
            "width": 1280, "height": 720,
        }, "item/report/definition/page/2.3.1")
        self.text("Page heading", (24, 14, 1232, 70), [(title, "25pt", "#13332E"), (subtitle, "10pt", "#465C57")])

    @staticmethod
    def key(value):
        return sha256(value.encode()).hexdigest()[:20]

    def visual(self, title, box, visual_type, roles=None, objects=None, sort=None, caption=None):
        self.order += 1000
        x, y, width, height = box
        name = self.key(title)
        visual = {"visualType": visual_type}
        if visual_type != "textbox":
            visual["visualContainerObjects"] = {
                "title": [{"properties": {"show": literal("true"), "text": literal(f"'{caption or title}'")}}],
            }
            visual["drillFilterOtherVisuals"] = True
        if objects:
            visual["objects"] = objects
        if roles:
            visual["query"] = {"queryState": {role: {"projections": projections} for role, projections in roles.items()}}
        if sort:
            projection, direction = sort
            visual["query"]["sortDefinition"] = {"sort": [{"field": projection["field"], "direction": direction}]}
        save(self.directory / "visuals" / name / "visual.json", {
            "name": name, "position": {"x": x, "y": y, "width": width, "height": height,
                                       "z": self.order, "tabOrder": self.order},
            "visual": visual,
        }, "item/report/definition/visualContainer/2.14.0")

    def text(self, title, box, lines):
        paragraphs = [{"textRuns": [{"value": text, "textStyle": {"fontSize": size, "color": color}}]}
                      for text, size, color in lines]
        self.visual(title, box, "textbox", objects={"general": [{"properties": {"paragraphs": paragraphs}}]})

    def cards(self, measures):
        for index, (entity, metric) in enumerate(measures):
            self.visual(metric, (24 + 312 * index, 84, 296, 116), "card",
                        {"Values": [field(entity, metric, "Measure")]},
                        caption="Multi-listing supply share" if metric == "Share of listings from multi-listing hosts" else metric,
                        objects={
                            "labels": [{"properties": {"fontSize": literal("22D"),
                                                       "labelDisplayUnits": literal("1D")}}],
                            "categoryLabels": [{"properties": {"show": literal("false")}}],
                        })

    def slicers(self):
        for index, category in enumerate(("Neighbourhood", "Room Type")):
            self.visual(category, (24, 204 + 244 * index, 204, 228), "slicer",
                        {"Values": [field("Listings", category)]})

    def chart(self, title, box, visual_type, category, metric):
        self.visual(title, box, visual_type, {"Category": [category], "Y": [metric]},
                    sort=(category, "Ascending") if visual_type == "lineChart" else (metric, "Descending"))


def build_report():
    save(OUTPUT / f"{NAME}.pbip", {
        "version": "1.0", "artifacts": [{"report": {"path": REPORT.name}}],
        "settings": {"enableAutoRecovery": True},
    }, "pbip/pbipProperties/1.0.0")
    save(REPORT / "definition.pbir", {
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{MODEL.name}"}},
    }, "item/report/definitionProperties/2.0.0")
    save(DEFINITION / "version.json", {"version": "2.0.0"}, "item/report/definition/versionMetadata/1.0.0")
    theme = "Fluent2-CY26SU10"
    save(DEFINITION / "report.json", {
        "themeCollection": {"baseTheme": {
            "name": theme, "type": "SharedResources",
            "reportVersionAtImport": {"visual": "2.14.0", "report": "3.4.0", "page": "2.3.1"},
        }},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": theme, "path": f"BaseThemes/{theme}.json", "type": "BaseTheme"}]}],
    }, "item/report/definition/report/3.3.0")

    area = field("Listings", "Neighbourhood")
    room = field("Listings", "Room Type")
    count = field("Listings", "Listing count", "Measure")
    price = field("Listings", "Median nightly price", "Measure")

    overview = Page("London market overview", "Inside Airbnb London · 17 September 2026 snapshot")
    overview.cards([("Listings", metric) for metric in
                    ("Listing count", "Median nightly price", "Price coverage", "Host count")])
    overview.slicers()
    overview.chart("Listing supply by neighbourhood", (244, 204, 555, 472), "barChart", area, count)
    overview.chart("Listing supply by room type", (815, 204, 441, 225), "barChart", room, count)
    overview.chart("Median advertised nightly price by room type", (815, 445, 441, 231), "barChart", room, price)

    hosts = Page("Host concentration", "Multi-listing hosts have at least two listings across the London snapshot.")
    hosts.cards([("Listings", metric) for metric in
                 ("Host count", "Multi-listing hosts", "Multi-listing host share",
                  "Share of listings from multi-listing hosts")])
    hosts.slicers()
    hosts.chart("Multi-listing host listings by neighbourhood", (244, 204, 555, 472), "barChart", area,
                field("Listings", "Multi-listing host listings", "Measure"))
    hosts.chart("Multi-listing host share by room type", (815, 204, 441, 472), "barChart", room,
                field("Listings", "Multi-listing host share", "Measure"))

    activity = Page("Calendar and reviews", "Availability reflects the forward calendar at scrape time. Reviews cover listings in this snapshot.")
    activity.cards([("Calendar Monthly", "Calendar availability"), ("Calendar Monthly", "Observed listing nights"),
                    ("Reviews Monthly", "Review records"), ("Listings", "Average listing rating")])
    activity.slicers()
    activity.chart("Calendar availability by month", (244, 204, 1012, 225), "lineChart",
                   field("Calendar Monthly", "Month"), field("Calendar Monthly", "Calendar availability", "Measure"))
    activity.chart("Review records by month", (244, 445, 1012, 231), "lineChart",
                   field("Reviews Monthly", "Month"), field("Reviews Monthly", "Review records", "Measure"))
    activity.text("Availability interpretation", (244, 680, 1012, 30),
                  [("Unavailable nights can include reservations and host blocks. First and last calendar months are partial.", "10pt", "#465C57")])

    save(DEFINITION / "pages" / "pages.json", {
        "pageOrder": [page.name for page in (overview, hosts, activity)], "activePageName": overview.name,
    }, "item/report/definition/pagesMetadata/1.1.0")


if __name__ == "__main__":
    build_model()
    build_report()
