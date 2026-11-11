# London Short-Term Rental Market Intelligence

This portfolio project uses Inside Airbnb’s 17 September 2026 London snapshot to examine listing supply, advertised prices, host concentration, calendar availability and review activity across London neighbourhoods.

## View the dashboards

Open any screenshot directly on GitHub. Interactive browser viewing is planned for a later step.

| Dashboard | Power BI | Tableau |
| --- | --- | --- |
| London market overview | [View screenshot](docs/screenshots/powerbi-market-overview.png) | [View screenshot](docs/screenshots/tableau-market-overview.png) |
| Host concentration | [View screenshot](docs/screenshots/powerbi-host-concentration.png) | [View screenshot](docs/screenshots/tableau-host-concentration.png) |
| Calendar and reviews | [View screenshot](docs/screenshots/powerbi-calendar-reviews.png) | [View screenshot](docs/screenshots/tableau-calendar-reviews.png) |

[Read the full case study](docs/case-study.md) for findings, methodology, and data limitations.

| Input | Grain | Use |
| --- | --- | --- |
| Detailed listings | Listing at scrape | Neighbourhood, room type, advertised nightly price, host ID and rating |
| Detailed calendar | Listing and date | Available listing nights and observed calendar nights by month |
| Summary reviews | Review date and listing | Historical monthly review activity for listings in the snapshot |

Source and attribution: [Inside Airbnb, Get the Data](https://insideairbnb.com/get-the-data/). See [Inside Airbnb’s data assumptions](https://insideairbnb.com/data-assumptions/) for the limits of scraped listings and calendars.

## Dashboard measures

- Listing supply counts distinct listing IDs in the snapshot. A host with at least two distinct London listings in the snapshot is a multi-listing host.
- Median advertised price uses positive, parseable listing prices in GBP. Inside Airbnb defines the field in local currency, and the London export uses a dollar-sign prefix. The script removes the prefix without currency conversion. Show price coverage with the median. [Inside Airbnb Data Dictionary](https://docs.google.com/spreadsheets/d/1iWCNJcSutYqpULSQHlNyGInUvHg2BoUGoNRIGa6Szc4/edit?usp=sharing)
- Calendar availability divides available listing nights by observed listing nights. A host block and a reservation can both appear unavailable. The calendar is a forward view at scrape time, with partial months at the edges.
- Review activity counts review records by review month for matched listings. Ratings are listing-level scores as of the scrape. Historical reviews cover listings present in the current snapshot and cannot measure market-wide historical demand.

## Reproduce the dashboard inputs

Run `python prepare.py` from this directory. The script downloads the pinned files into `data/raw` and writes dashboard tables and a quality profile into `data/processed`. It reuses existing downloads on subsequent runs.

The snapshot contains 91,954 listings and 51,348 hosts. Of those listings, 59,905 (65.1%) have a usable advertised price. The median among priced listings is £175. The preparation matched all 33,563,890 calendar records and 2,323,969 review records to snapshot listings.

## Power BI report

After preparing the CSVs, run `python build_powerbi.py` to configure the local data paths. Then open `powerbi/London Short-Term Rental Market Intelligence.pbip` in Power BI Desktop. The report has three pages: London market overview, Host concentration, and Calendar and reviews. Each page has neighbourhood and room type slicers.

The Listings table filters both monthly tables through one-to-many relationships on text listing IDs. The calendar and review charts use their respective month fields. If you move the project folder, run `python build_powerbi.py` before opening the project to regenerate the CSV paths. The script rewrites the model and report definitions, so use it on a clean copy if you have made edits in Desktop. The local model cache is excluded from Git. On a fresh copy, apply the relationship refresh first if Desktop prompts for it, then refresh the data.

### Desktop verification

All three pages were refreshed and checked in Power BI Desktop. The report showed 10,384 multi-listing hosts, accounting for 20.2% of hosts and 55.5% of listings. The calendar marked 42.3% of observed listing nights available. Selecting Private room on Calendar and reviews changed both monthly charts and reduced the observed nights to 11,122,543 and the review count to 1,011,846. The report was saved with the filter cleared.

## Tableau workbook

After preparing the CSVs, install `tableauhyperapi` and run `python build_tableau.py`. Then open the generated `tableau/London Short-Term Rental Market Intelligence.twbx` in Tableau Desktop. The packaged workbook includes its Hyper extract. Select a neighbourhood or room-type bar to filter the dashboard and press Esc to clear the selection.

The extract preserves listing-level rows for median prices and distinct host counts. Calendar and review rows are aggregated by month, neighbourhood and room type, which preserves totals at the dashboard's filter grain. The workbook uses separate date fields for the two trends.

All three dashboards were checked in Tableau Desktop. The headline totals matched Power BI, including the Private room selection on Calendar and reviews (40.5% availability, 11,122,543 observed nights, and 1,011,846 reviews). Selecting Camden also updated both monthly charts.
