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


# Known last credible terrestrial AIS fix
# before MORNING CARA moved out of coastal AIS range.
SEED_RECORD = {
    "vessel": VESSEL,
    "imo": IMO,
    "mmsi": MMSI,
    "lat": 24.7002,
    "lng": 127.1542,
    "time": "2026-08-17T01:11:00Z",
    "reported": "2026-08-17T01:11:00Z",
    "speed": 17.6,
    "course": 142.0,
    "heading": 144.0,
    "waterBody": "East China Sea",
    "navigation_status": "Under way using engine",
    "port": None,
    "position_age": None,
    "source": "MarineRadar terrestrial AIS",
    "source_url": SOURCE_URL,
    "checked_at": None,
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-NZ,en;q=0.9",
}


def utc_now_iso():
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
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


def load_existing():
    if not OUTPUT_FILE.exists():
        return None

    try:
        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if str(data.get("imo", "")) != IMO:
            return None

        if str(data.get("mmsi", "")) != MMSI:
            return None

        return data

    except Exception:
        return None


def seed_record(checked_at):
    record = dict(SEED_RECORD)
    record["checked_at"] = checked_at
    return record


def fetch_page():
    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


def signed_coordinate(value, hemisphere):
    value = float(value)

    hemisphere = hemisphere.upper()

    if hemisphere in ("S", "W"):
        value *= -1

    return value


def extract_position(html):
    """
    Accepts examples such as:

    24.7002° N, 127.1542° E

    or

    22.4338° N, 17.6229° W
    """

    patterns = [
        (
            r'([-+]?\d{1,2}(?:\.\d+)?)\s*°?\s*([NS])'
            r'.{0,100}?'
            r'([-+]?\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])'
        ),
        (
            r'Latitude\s*'
            r'(\d{1,2})°\s*'
            r'(\d+(?:\.\d+)?)\'?\s*'
            r'([NS])'
            r'.{0,100}?'
            r'Longitude\s*'
            r'(\d{1,3})°\s*'
            r'(\d+(?:\.\d+)?)\'?\s*'
            r'([EW])'
        ),
    ]

    # Decimal degrees.
    match = re.search(
        patterns[0],
        html,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        lat = signed_coordinate(
            match.group(1),
            match.group(2),
        )

        lng = signed_coordinate(
            match.group(3),
            match.group(4),
        )

        return lat, lng

    # Degrees + minutes.
    match = re.search(
        patterns[1],
        html,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        lat_deg = float(match.group(1))
        lat_min = float(match.group(2))
        lat_hemi = match.group(3)

        lng_deg = float(match.group(4))
        lng_min = float(match.group(5))
        lng_hemi = match.group(6)

        lat = lat_deg + lat_min / 60.0
        lng = lng_deg + lng_min / 60.0

        if lat_hemi.upper() == "S":
            lat *= -1

        if lng_hemi.upper() == "W":
            lng *= -1

        return lat, lng

    return None, None


def extract_ais_time(html):
    # ISO UTC timestamp.
    match = re.search(
        r'20\d{2}-\d{2}-\d{2}T'
        r'\d{2}:\d{2}:\d{2}(?:\.\d+)?Z',
        html,
        re.IGNORECASE,
    )

    if match:
        return match.group(0)

    # Human-readable UTC timestamp.
    match = re.search(
        (
            r'(\d{1,2})\s+'
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
            r'\s+(20\d{2})'
            r'.{0,40}?'
            r'(\d{2}:\d{2})'
            r'\s*UTC'
        ),
        html,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        parsed = datetime.strptime(
            (
                f"{match.group(1)} "
                f"{match.group(2)} "
                f"{match.group(3)} "
                f"{match.group(4)}"
            ),
            "%d %b %Y %H:%M",
        ).replace(tzinfo=timezone.utc)

        return (
            parsed
            .isoformat()
            .replace("+00:00", "Z")
        )

    return None


def extract_speed(html):
    patterns = [
        r'Current speed[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*kn',
        r'([0-9]+(?:\.[0-9]+)?)\s*kn',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(
                match.group(1)
            )

    return None


def extract_course(html):
    patterns = [
        (
            r'Course(?: over ground)?'
            r'[^0-9]*'
            r'([0-9]+(?:\.[0-9]+)?)\s*°'
        ),
        (
            r'([0-9]+(?:\.[0-9]+)?)'
            r'\s*°\s*/'
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(
                match.group(1)
            )

    return None


def extract_heading(html):
    patterns = [
        (
            r'Heading[^0-9]*'
            r'([0-9]+(?:\.[0-9]+)?)\s*°'
        ),
        (
            r'[0-9.]+\s*°\s*/\s*'
            r'([0-9]+(?:\.[0-9]+)?)\s*°'
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(
                match.group(1)
            )

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

    lower_html = html.lower()

    for status in statuses:
        if status.lower() in lower_html:
            return status

    return None


def plausible_position(lat, lng):
    """
    MORNING CARA should currently be on the
    Asia -> SW Pacific -> NZ voyage.

    Reject obviously unrelated Atlantic positions.
    """

    if lat is None or lng is None:
        return False

    # Broad Asia / western Pacific / NZ corridor.
    if not (-50 <= lat <= 40):
        return False

    if not (100 <= lng <= 190):
        return False

    return True


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

    if existing is None:
        existing = seed_record(
            checked_at
        )

    try:
        html = fetch_page()

        lat, lng = extract_position(
            html
        )

        ais_time = extract_ais_time(
            html
        )

        print(
            "MarineRadar parsed position:",
            lat,
            lng,
        )

        print(
            "MarineRadar parsed AIS time:",
            ais_time,
        )

        # Only replace the stored fix if we have:
        # 1. a plausible coordinate, AND
        # 2. a genuine AIS timestamp.
        if (
            plausible_position(lat, lng)
            and ais_time
        ):
            fresh_time = parse_iso_utc(
                ais_time
            )

            existing_time = parse_iso_utc(
                existing.get("time")
            )

            if (
                fresh_time
                and (
                    existing_time is None
                    or fresh_time > existing_time
                )
            ):
                existing["lat"] = round(
                    lat,
                    6,
                )

                existing["lng"] = round(
                    lng,
                    6,
                )

                existing["time"] = ais_time
                existing["reported"] = ais_time

                speed = extract_speed(
                    html
                )

                course = extract_course(
                    html
                )

                heading = extract_heading(
                    html
                )

                navigation_status = (
                    extract_navigation_status(
                        html
                    )
                )

                if speed is not None:
                    existing["speed"] = speed

                if course is not None:
                    existing["course"] = course

                if heading is not None:
                    existing["heading"] = heading

                if navigation_status:
                    existing[
                        "navigation_status"
                    ] = navigation_status

                existing["source"] = (
                    "MarineRadar terrestrial AIS"
                )

                print(
                    "Saved newer credible AIS fix."
                )

            else:
                print(
                    "No newer AIS timestamp found."
                )

        else:
            print(
                "MarineRadar position/time not "
                "credible enough to overwrite "
                "the stored AIS fix."
            )

        # Always record that the public source
        # was checked on this workflow run.
        existing["checked_at"] = checked_at
        existing["source_url"] = SOURCE_URL

        save_record(
            existing
        )

        print(
            json.dumps(
                existing,
                indent=2,
            )
        )

    except Exception as exc:
        # Do NOT fail GitHub Actions simply because
        # the public AIS site is unavailable or
        # changed its HTML.
        print(
            "AIS source check failed:",
            exc,
        )

        existing["checked_at"] = checked_at
        existing["source_url"] = SOURCE_URL

        save_record(
            existing
        )

        print(
            "Kept existing MORNING CARA fix "
            "and updated checked_at."
        )

        print(
            json.dumps(
                existing,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
