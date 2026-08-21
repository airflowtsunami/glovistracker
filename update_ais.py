import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


URL = (
    "https://aisvesseltracker.com/vessel/"
    "glovis-century-mmsi-441200000-imo-9590589"
)

OUTPUT = Path("ais.json")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def find(pattern, text, flags=re.I | re.S):
    match = re.search(pattern, text, flags)

    if not match:
        return None

    return match.group(1).strip()


def parse_voyage_radar(html):

    # ------------------------------------------------
    # Latitude / Longitude
    #
    # Voyage Radar currently exposes:
    #
    # Latitude 33.862400
    # Longitude 134.994670
    # ------------------------------------------------

    lat = find(
        r"Latitude\s*</?[^>]*>*\s*"
        r"([+-]?\d{1,2}\.\d+)",
        html
    )

    lng = find(
        r"Longitude\s*</?[^>]*>*\s*"
        r"([+-]?\d{1,3}\.\d+)",
        html
    )


    # Backup parser using visible text stripped
    # crudely from the HTML.

    plain = re.sub(
        r"<[^>]+>",
        " ",
        html
    )

    plain = re.sub(
        r"\s+",
        " ",
        plain
    )


    if not lat:

        lat = find(
            r"Latitude\s+"
            r"([+-]?\d{1,2}\.\d+)",
            plain
        )


    if not lng:

        lng = find(
            r"Longitude\s+"
            r"([+-]?\d{1,3}\.\d+)",
            plain
        )


    # Another backup based on the vessel description.

    if not lat or not lng:

        position = re.search(
            r"position\s+"
            r"([0-9.]+)°([NS]),\s*"
            r"([0-9.]+)°([EW])",
            plain,
            re.I
        )

        if position:

            raw_lat = float(
                position.group(1)
            )

            raw_lng = float(
                position.group(3)
            )

            lat = (
                -raw_lat
                if position.group(2).upper() == "S"
                else raw_lat
            )

            lng = (
                -raw_lng
                if position.group(4).upper() == "W"
                else raw_lng
            )


    if lat is None or lng is None:

        raise RuntimeError(
            "Could not extract latitude/longitude "
            "from Voyage Radar"
        )


    lat = float(lat)
    lng = float(lng)


    # Sanity check

    if not (-90 <= lat <= 90):

        raise RuntimeError(
            f"Invalid latitude: {lat}"
        )

    if not (-180 <= lng <= 180):

        raise RuntimeError(
            f"Invalid longitude: {lng}"
        )


    # ------------------------------------------------
    # Speed
    # ------------------------------------------------

    speed = find(
        r"Speed\s+"
        r"([0-9.]+)\s*kn",
        plain
    )

    if speed is None:

        speed = find(
            r"moving at\s+"
            r"([0-9.]+)\s+knots",
            plain
        )

    speed = (
        float(speed)
        if speed is not None
        else None
    )


    # ------------------------------------------------
    # Course over ground
    # ------------------------------------------------

    course = find(
        r"Course Over Ground\s*"
        r"\(COG\)\s*"
        r"([0-9.]+)°",
        plain
    )

    course = (
        float(course)
        if course is not None
        else None
    )


    # ------------------------------------------------
    # Heading
    # ------------------------------------------------

    heading = find(
        r"True Heading\s+"
        r"([0-9.]+)°",
        plain
    )

    heading = (
        float(heading)
        if heading is not None
        else None
    )


    # ------------------------------------------------
    # Water body
    # ------------------------------------------------

    water_body = find(
        r"Water Body\s+"
        r"(.+?)\s+"
        r"Last Update",
        plain
    )

    if water_body:

        water_body = (
            water_body
            .strip()
            .replace("  ", " ")
        )


    # ------------------------------------------------
    # Last AIS update time
    #
    # Current format:
    # 11 Aug 2026, 11:01 UTC
    # ------------------------------------------------

    reported = find(
        r"Last Update\s*"
        r"\(UTC\)\s*"
        r"(\d{1,2}\s+"
        r"[A-Za-z]{3}\s+"
        r"\d{4},?\s+"
        r"\d{1,2}:\d{2}\s+UTC)",
        plain
    )


    if not reported:

        reported = find(
            r"Position last updated\s+"
            r"(\d{1,2}\s+"
            r"[A-Za-z]{3}\s+"
            r"\d{4},?\s+"
            r"\d{1,2}:\d{2}\s+UTC)",
            plain
        )


    if not reported:

        raise RuntimeError(
            "Could not extract AIS timestamp"
        )


    # Normalize optional comma.

    reported_clean = (
        reported
        .replace(",", "")
        .strip()
    )


    reported_dt = datetime.strptime(
        reported_clean,
        "%d %b %Y %H:%M UTC"
    ).replace(
        tzinfo=timezone.utc
    )


    return {
        "vessel": "GLOVIS CENTURY",
        "imo": "9590589",
        "mmsi": "441200000",

        "lat": lat,
        "lng": lng,

        "time":
            reported_dt.isoformat()
            .replace("+00:00", "Z"),

        "reported":
            reported,

        "speed":
            speed,

        "course":
            course,

        "heading":
            heading,

        "waterBody":
            water_body,

        "source":
            "Voyage Radar",

        "source_url":
            URL,

        "checked_at":
            datetime.now(
                timezone.utc
            )
            .isoformat()
            .replace("+00:00", "Z")
    }


def read_existing():

    if not OUTPUT.exists():
        return None

    try:

        with OUTPUT.open(
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return None


def parse_iso(value):

    if not value:
        return None

    try:

        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00"
            )
        )

    except Exception:

        return None


def main():

    print(
        "Fetching:",
        URL
    )


    response = requests.get(
        URL,
        headers=HEADERS,
        timeout=30
    )


    print(
        "HTTP status:",
        response.status_code
    )


    response.raise_for_status()


    if len(response.text) < 1000:

        raise RuntimeError(
            "Voyage Radar response unexpectedly small"
        )


    new_data = parse_voyage_radar(
        response.text
    )


    existing = read_existing()


    new_time = parse_iso(
        new_data.get("time")
    )


    existing_time = (
        parse_iso(
            existing.get("time")
        )
        if existing
        else None
    )


    # ------------------------------------------------
    # Do not overwrite a newer position with an older
    # position if Voyage Radar briefly serves stale data.
    # ------------------------------------------------

    if (
        existing_time
        and new_time
        and new_time < existing_time
    ):

        print(
            "Voyage Radar returned an older fix."
        )

        print(
            "Existing:",
            existing_time
        )

        print(
            "Fetched:",
            new_time
        )

        print(
            "Keeping existing ais.json"
        )

        return


    with OUTPUT.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            new_data,
            f,
            indent=2,
            ensure_ascii=False
        )

        f.write("\n")


    print(
        json.dumps(
            new_data,
            indent=2
        )
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            f"AIS update failed: {exc}",
            file=sys.stderr
        )

        sys.exit(1)
