import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


VESSEL = "MORNING CARA"
IMO = "9574092"
MMSI = "441148000"

SOURCE_URL = (
    "https://www.marineradar.com/vessel/"
    "mmsi-441148000/morning-cara"
)

OUTPUT_FILE = Path("ais.json")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-NZ,en;q=0.9",
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_existing():
    if not OUTPUT_FILE.exists():
        return None

    try:
        with OUTPUT_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Do not reuse old GLOVIS CENTURY data.
        if str(data.get("imo", "")) != IMO:
            return None

        return data

    except Exception:
        return None


def parse_iso_utc(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except Exception:
        return None


def fetch_page():
    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


def extract_position(html):
    """
    MarineRadar currently exposes text such as:

    Latitude 24° 42.012' N · Longitude 127° 9.252' E

    and elsewhere:

    24.7002° N, 127.1542° E
    """

    # Prefer decimal-degree coordinates.
    decimal_patterns = [
        r'([-+]?\d{1,2}\.\d+)\s*°?\s*N'
        r'.{0,100}?'
        r'([-+]?\d{1,3}\.\d+)\s*°?\s*E',

        r'latitude[^0-9\-+]*([-+]?\d{1,2}\.\d+)'
        r'.{0,100}?'
        r'longitude[^0-9\-+]*([-+]?\d{1,3}\.\d+)',
    ]

    for pattern in decimal_patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            lat = float(match.group(1))
            lng = float(match.group(2))

            # The current vessel is north/east at the
            # known public fix.
            return lat, lng

    # Fallback for degree/minute format.
    dm_pattern = (
        r'Latitude\s*'
        r'(\d{1,2})°\s*'
        r'(\d+(?:\.\d+)?)\'?\s*'
        r'([NS])'
        r'.{0,100}?'
        r'Longitude\s*'
        r'(\d{1,3})°\s*'
        r'(\d+(?:\.\d+)?)\'?\s*'
        r'([EW])'
    )

    match = re.search(
        dm_pattern,
        html,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        lat_deg = float(match.group(1))
        lat_min = float(match.group(2))
        lat_hemi = match.group(3).upper()

        lng_deg = float(match.group(4))
        lng_min = float(match.group(5))
        lng_hemi = match.group(6).upper()

        lat = lat_deg + lat_min / 60.0
        lng = lng_deg + lng_min / 60.0

        if lat_hemi == "S":
            lat *= -1

        if lng_hemi == "W":
            lng *= -1

        return lat, lng

    return None, None


def extract_ais_time(html):
    """
    Tries to find ISO timestamp first.

    Current public MarineRadar data includes:
    2026-08-17T01:11:00Z
    """

    patterns = [
        r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',

        r'(\d{1,2})\s+'
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        r'\s+(20\d{2})'
        r'.{0,40}?'
        r'(\d{2}:\d{2})'
        r'\s*UTC',
    ]

    match = re.search(
        patterns[0],
        html,
        re.IGNORECASE,
    )

    if match:
        return match.group(0)

    match = re.search(
        patterns[1],
        html,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        day = int(match.group(1))
        month_text = match.group(2)
        year = int(match.group(3))
        time_text = match.group(4)

        parsed = datetime.strptime(
            f"{day} {month_text} {year} {time_text}",
            "%d %b %Y %H:%M",
        ).replace(tzinfo=timezone.utc)

        return parsed.isoformat().replace("+00:00", "Z")

    return None


def extract_speed(html):
    patterns = [
        r'Current speed[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*kn',
        r'([0-9]+(?:\.[0-9]+)?)\s*kn\s*(?:Speed|Current speed)',
        r'([0-9]+(?:\.[0-9]+)?)\s*kn',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(match.group(1))

    return None


def extract_course(html):
    patterns = [
        r'Course(?: over ground)?[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*°',
        r'([0-9]+(?:\.[0-9]+)?)\s*°\s*/\s*[0-9.]+\s*°',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(match.group(1))

    return None


def extract_heading(html):
    patterns = [
        r'Heading[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*°',
        r'[0-9.]+\s*°\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*°',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(match.group(1))

    return None


def extract_navigation_status(html):
    statuses = [
        "Under way using engine",
        "Moored",
        "At anchor",
        "Not under command",
        "Restricted manoeuverability",
        "Constrained by her draught",
    ]

    for status in statuses:
        if status.lower() in html.lower():
            return status

    return None


def extract_water_body(html):
    known_areas = [
        "Papua New Guinean Exclusive Economic Zone",
        "Philippine Sea",
        "East China Sea",
        "South Pacific Ocean",
        "Tasman Sea",
    ]

    lower_html = html.lower()

    for area in known_areas:
        if area.lower() in lower_html:
            return area

    return ""


def build_record(html, checked_at):
    lat, lng = extract_position(html)

    ais_time = extract_ais_time(html)

    speed = extract_speed(html)
    course = extract_course(html)
    heading = extract_heading(html)

    nav_status = extract_navigation_status(html)
    water_body = extract_water_body(html)

    if (
        lat is None
        or lng is None
        or ais_time is None
    ):
        raise RuntimeError(
            "Could not parse an exact AIS position/time "
            "from MarineRadar"
        )

    return {
        "vessel": VESSEL,
        "imo": IMO,
        "mmsi": MMSI,

        "lat": round(lat, 6),
        "lng": round(lng, 6),

        "time": ais_time,
        "reported": ais_time,

        "speed": speed,
        "course": course,
        "heading": heading,

        "waterBody": water_body,

        "navigation_status": nav_status,

        "port": None,

        "position_age": None,

        "source": "MarineRadar terrestrial AIS",
        "source_url": SOURCE_URL,

        # This is the important field your HTML reads.
        "checked_at": checked_at,
    }


def save_record(record):
    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            record,
            f,
            indent=2,
            ensure_ascii=False,
        )

        f.write("\n")


def main():
    checked_at = utc_now_iso()

    existing = load_existing()

    try:
        html = fetch_page()

        fresh = build_record(
            html,
            checked_at,
        )

        fresh_time = parse_iso_utc(
            fresh["time"]
        )

        existing_time = (
            parse_iso_utc(
                existing.get("time")
            )
            if existing
            else None
        )

        /*
        Python doesn't support C-style comments.
        */

    except Exception as exc:
        print(
            "Could not retrieve/parse fresh AIS:",
            exc,
        )

        if existing:
            # Even if there is no newer AIS fix,
            # record that we checked the source now.
            existing["checked_at"] = checked_at
            existing["source_url"] = SOURCE_URL

            save_record(existing)

            print(
                "No newer exact AIS fix found."
            )

            print(
                "Updated checked_at:",
                checked_at,
            )

            print(
                json.dumps(
                    existing,
                    indent=2,
                )
            )

            return

        raise


if __name__ == "__main__":
    main()
