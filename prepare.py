"""Prepare listing, calendar and review tables for the London dashboard."""

import csv
import gzip
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SOURCE = "https://data.insideairbnb.com/united-kingdom/england/london/2026-09-17"
FILES = ("data/listings.csv.gz", "data/calendar.csv.gz", "visualisations/reviews.csv")
LISTING_FIELDS = (
    "host_id", "neighbourhood_cleansed", "room_type", "latitude", "longitude",
    "accommodates", "minimum_nights", "review_scores_rating", "number_of_reviews",
)


def source_rows(filename):
    path = RAW / filename
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def positive_price(value):
    try:
        price = Decimal(value.strip().removeprefix("$").removeprefix("£").replace(",", ""))
        if price.is_finite() and price > 0:
            return price
    except InvalidOperation:
        pass
    return None


def write_csv(filename, fields, rows):
    target = PROCESSED / filename
    temporary = target.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)
    temporary.replace(target)


def prepare():
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    for remote in FILES:
        target = RAW / Path(remote).name
        if not target.exists():
            temporary = target.with_suffix(".download")
            urlretrieve(f"{SOURCE}/{remote}", temporary)
            temporary.replace(target)

    listings = {}
    prices = []
    hosts = Counter()
    neighbourhoods = Counter()
    room_types = Counter()
    for row in source_rows("listings.csv.gz"):
        listing_id = row["id"]
        if not listing_id or listing_id in listings:
            raise ValueError(f"Missing or duplicate listing ID: {listing_id!r}")
        price = positive_price(row["price"])
        if price is not None:
            prices.append(price)
        if row["host_id"]:
            hosts[row["host_id"]] += 1
        neighbourhoods[row["neighbourhood_cleansed"]] += 1
        room_types[row["room_type"]] += 1
        listings[listing_id] = (price, *(row[field] for field in LISTING_FIELDS))

    observed = Counter()
    available = Counter()
    calendar_dates = set()
    calendar_unmatched = 0
    for row in source_rows("calendar.csv.gz"):
        listing_id, date, flag = row["listing_id"], row["date"], row["available"]
        if listing_id not in listings:
            calendar_unmatched += 1
            continue
        if flag not in {"t", "f"}:
            raise ValueError(f"Unexpected calendar availability: {flag!r}")
        key = (listing_id, date[:7] + "-01")
        calendar_dates.add(date)
        observed[key] += 1
        if flag == "t":
            available[key] += 1

    reviews = Counter()
    review_dates = set()
    reviews_unmatched = 0
    for row in source_rows("reviews.csv"):
        listing_id, date = row["listing_id"], row["date"]
        if listing_id not in listings:
            reviews_unmatched += 1
            continue
        review_dates.add(date)
        reviews[listing_id, date[:7] + "-01"] += 1

    write_csv(
        "listings.csv",
        ("listing_id", "advertised_nightly_gbp", *LISTING_FIELDS, "host_listing_count"),
        ((key, *values, hosts.get(values[1])) for key, values in listings.items()),
    )
    write_csv(
        "calendar_monthly.csv", ("listing_id", "month", "observed_nights", "available_nights"),
        ((*key, nights, available[key]) for key, nights in observed.items()),
    )
    write_csv(
        "reviews_monthly.csv", ("listing_id", "month", "review_count"),
        ((*key, count) for key, count in reviews.items()),
    )
    profile = {
        "source": SOURCE,
        "listings": len(listings),
        "neighbourhoods": neighbourhoods,
        "room_types": room_types,
        "hosts": len(hosts),
        "listings_missing_host": len(listings) - hosts.total(),
        "multi_listing_hosts": sum(count >= 2 for count in hosts.values()),
        "listings_with_valid_price": len(prices),
        "median_advertised_nightly_gbp": str(median(prices)) if prices else None,
        "calendar_matched_rows": observed.total(),
        "calendar_unmatched_rows": calendar_unmatched,
        "calendar_date_range": [min(calendar_dates), max(calendar_dates)] if calendar_dates else [],
        "calendar_available_nights": available.total(),
        "reviews_matched_rows": reviews.total(),
        "reviews_unmatched_rows": reviews_unmatched,
        "review_date_range": [min(review_dates), max(review_dates)] if review_dates else [],
    }
    (PROCESSED / "profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    prepare()
