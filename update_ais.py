import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


# ============================================================
# VESSEL
# ============================================================

VESSEL = "MORNING CARA"
IMO = "9574092"
MMSI = "441148000"

OUTPUT_FILE = Path("ais.json")


# ============================================================
# SOURCES
# ============================================================

VESSELFINDER_URL = (
    "https://www.vesselfinder.com/vessels/details/9574092"
)

MARINERADAR_URL = (
    "https://www.marineradar.com/vessel/"
    "mmsi-441148000/morning-cara"
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-NZ,en;q=0.9",
    "Cache-Control": "no-cache",
}


# ============================================================
# OPTIONAL MANUAL FIX
#
# Normally leave this as None.
#
# If you have an exact position from another source which the
# scraper is temporarily failing to obtain, enter it here.
#
# IMPORTANT:
# timestamp MUST be the actual UTC/GMT time of the fix.
#
# Example:
#
# MANUAL_FIX = {
#     "lat": -34.117220,
#     "lng": 173.561701,
#     "time": "2026-08-28T06:50:00Z",
#     "source": "Manual AIS fix",
# }
#
# Once an online source produces anything newer, that source
# automatically wins.
# ============================================================

MANUAL_FIX = None


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().isoformat().replace("+00:00", "Z")


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
        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def to_iso_z(dt):
    if dt is None:
        return None

    return (
        dt.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def valid_lat_lng(lat, lng):
    if lat is None or lng is None:
        return False

    return (
        -90 <= lat <= 90
        and -180 <= lng <= 180
    )


# ============================================================
# LOAD/SAVE EXISTING AIS.JSON
# ============================================================

def load_existing():
    if not OUTPUT_FILE.exists():
        return None

    try:
        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        # Prevent accidentally carrying over another ship.
        if str(data.get("imo", "")) != IMO:
            return None

        return data

    except Exception as exc:
        print("Could not read existing ais.json:", exc)
        return None


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


# ============================================================
# HTTP
# ============================================================

def fetch_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# GENERIC TIME PARSING
# ============================================================

def extract_absolute_time(text):
    """
    Find an actual UTC/GMT timestamp.

    Supports things such as:

        2026-08-28T06:50:00Z
        2026-08-28T06:50:00+00:00
        28 Aug 2026 06:50 UTC
        28 Aug 2026 06:50 GMT
        Aug 28, 2026 06:50 UTC
    """

    # ISO Z
    match = re.search(
        r'20\d{2}-\d{2}-\d{2}'
        r'T\d{2}:\d{2}:\d{2}'
        r'(?:\.\d+)?Z',
        text,
        re.IGNORECASE,
    )

    if match:
        return parse_iso_utc(match.group(0))

    # ISO with +00:00
    match = re.search(
        r'20\d{2}-\d{2}-\d{2}'
        r'T\d{2}:\d{2}:\d{2}'
        r'(?:\.\d+)?\+00:00',
        text,
        re.IGNORECASE,
    )

    if match:
        return parse_iso_utc(match.group(0))

    # 28 Aug 2026 06:50 GMT
    match = re.search(
        r'(\d{1,2})\s+'
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        r'\s+(20\d{2})'
        r'.{0,60}?'
        r'(\d{1,2}:\d{2})'
        r'\s*(?:UTC|GMT)',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        dt = datetime.strptime(
            (
                f"{match.group(1)} "
                f"{match.group(2)} "
                f"{match.group(3)} "
                f"{match.group(4)}"
            ),
            "%d %b %Y %H:%M",
        )

        return dt.replace(tzinfo=timezone.utc)

    # Aug 28, 2026 06:50 UTC
    match = re.search(
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        r'\s+(\d{1,2}),?\s+(20\d{2})'
        r'.{0,60}?'
        r'(\d{1,2}:\d{2})'
        r'\s*(?:UTC|GMT)',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        dt = datetime.strptime(
            (
                f"{match.group(2)} "
                f"{match.group(1)} "
                f"{match.group(3)} "
                f"{match.group(4)}"
            ),
            "%d %b %Y %H:%M",
        )

        return dt.replace(tzinfo=timezone.utc)

    return None


# ============================================================
# RELATIVE TIME
# ============================================================

def relative_time_to_datetime(text, checked_dt):
    """
    Converts:

       1 min ago
       13 minutes ago
       2 hours ago
       42 hours ago

    into an approximate timestamp.

    We deliberately mark these as approximate later.
    """

    match = re.search(
        r'(\d+)\s*'
        r'(second|seconds|sec|secs|'
        r'minute|minutes|min|mins|'
        r'hour|hours|hr|hrs)'
        r'\s+ago',
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()

    from datetime import timedelta

    if unit in ("second", "seconds", "sec", "secs"):
        return checked_dt - timedelta(seconds=amount)

    if unit in ("minute", "minutes", "min", "mins"):
        return checked_dt - timedelta(minutes=amount)

    if unit in ("hour", "hours", "hr", "hrs"):
        return checked_dt - timedelta(hours=amount)

    return None


# ============================================================
# COORDINATE EXTRACTION
# ============================================================

def extract_decimal_coordinates(text):
    """
    Handles common formats such as:

       -34.117220, 173.561701

       34.117220° S, 173.561701° E

       Latitude -34.117220
       Longitude 173.561701

       "lat":-34.117220,"lon":173.561701
    """

    patterns = [

        # Explicit latitude / longitude
        (
            r'latitude'
            r'[^0-9+\-]{0,30}'
            r'([-+]?\d{1,2}(?:\.\d+)?)'
            r'.{0,150}?'
            r'longitude'
            r'[^0-9+\-]{0,30}'
            r'([-+]?\d{1,3}(?:\.\d+)?)'
        ),

        # JSON lat/lon
        (
            r'["\']?lat(?:itude)?["\']?'
            r'\s*[:=]\s*'
            r'["\']?'
            r'([-+]?\d{1,2}(?:\.\d+)?)'
            r'["\']?'
            r'.{0,100}?'
            r'["\']?(?:lon|lng|longitude)["\']?'
            r'\s*[:=]\s*'
            r'["\']?'
            r'([-+]?\d{1,3}(?:\.\d+)?)'
        ),

        # Plain signed pair
        (
            r'([-+]?\d{1,2}\.\d{3,})'
            r'\s*[,;/]\s*'
            r'([-+]?\d{1,3}\.\d{3,})'
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if not match:
            continue

        lat = parse_float(match.group(1))
        lng = parse_float(match.group(2))

        if valid_lat_lng(lat, lng):
            return lat, lng

    # Hemisphere format
    match = re.search(
        r'(\d{1,2}(?:\.\d+)?)'
        r'\s*°?\s*([NS])'
        r'.{0,100}?'
        r'(\d{1,3}(?:\.\d+)?)'
        r'\s*°?\s*([EW])',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:

        lat = float(match.group(1))
        lat_hemi = match.group(2).upper()

        lng = float(match.group(3))
        lng_hemi = match.group(4).upper()

        if lat_hemi == "S":
            lat *= -1

        if lng_hemi == "W":
            lng *= -1

        if valid_lat_lng(lat, lng):
            return lat, lng

    return None, None


def extract_degree_minute_coordinates(text):
    """
    Example:

       Latitude 34° 7.033' S
       Longitude 173° 33.702' E
    """

    pattern = (
        r'Latitude\s*'
        r'(\d{1,2})°\s*'
        r'(\d+(?:\.\d+)?)'
        r'[\'′]?\s*'
        r'([NS])'
        r'.{0,150}?'
        r'Longitude\s*'
        r'(\d{1,3})°\s*'
        r'(\d+(?:\.\d+)?)'
        r'[\'′]?\s*'
        r'([EW])'
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return None, None

    lat_deg = float(match.group(1))
    lat_min = float(match.group(2))
    lat_hemi = match.group(3).upper()

    lng_deg = float(match.group(4))
    lng_min = float(match.group(5))
    lng_hemi = match.group(6).upper()

    lat = lat_deg + (lat_min / 60.0)
    lng = lng_deg + (lng_min / 60.0)

    if lat_hemi == "S":
        lat *= -1

    if lng_hemi == "W":
        lng *= -1

    if not valid_lat_lng(lat, lng):
        return None, None

    return lat, lng


def extract_coordinates(text):

    lat, lng = extract_degree_minute_coordinates(text)

    if valid_lat_lng(lat, lng):
        return lat, lng

    return extract_decimal_coordinates(text)


# ============================================================
# SPEED / COURSE
# ============================================================

def extract_speed(text):

    patterns = [
        r'(?:current\s+)?speed'
        r'[^0-9]{0,30}'
        r'([0-9]+(?:\.[0-9]+)?)\s*(?:kn|knots)',

        r'sailing\s+at\s+(?:a\s+speed\s+of\s+)?'
        r'([0-9]+(?:\.[0-9]+)?)\s*(?:kn|knots)',

        r'([0-9]+(?:\.[0-9]+)?)\s*(?:kn|knots)',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(match.group(1))

    return None


def extract_course(text):

    patterns = [
        r'course(?:\s+over\s+ground)?'
        r'[^0-9]{0,30}'
        r'([0-9]+(?:\.[0-9]+)?)\s*°',

        r'["\']?(?:cog|course)["\']?'
        r'\s*[:=]\s*'
        r'["\']?'
        r'([0-9]+(?:\.[0-9]+)?)',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            return parse_float(match.group(1))

    return None


def extract_heading(text):

    match = re.search(
        r'heading'
        r'[^0-9]{0,30}'
        r'([0-9]+(?:\.[0-9]+)?)\s*°',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        return parse_float(match.group(1))

    return None


# ============================================================
# NAV STATUS
# ============================================================

def extract_navigation_status(text):

    statuses = [
        "Under way using engine",
        "Moored",
        "At anchor",
        "Not under command",
        "Restricted manoeuverability",
        "Constrained by her draught",
    ]

    lower = text.lower()

    for status in statuses:

        if status.lower() in lower:
            return status

    return None


# ============================================================
# SOURCE: MARINERADAR
# ============================================================

def get_marineradar(checked_dt):

    print()
    print("Checking MarineRadar...")

    try:
        html = fetch_page(MARINERADAR_URL)

        lat, lng = extract_coordinates(html)
        fix_time = extract_absolute_time(html)

        if not valid_lat_lng(lat, lng):
            raise RuntimeError(
                "could not extract coordinates"
            )

        if fix_time is None:
            raise RuntimeError(
                "could not extract an exact AIS timestamp"
            )

        record = {
            "lat": lat,
            "lng": lng,
            "time_dt": fix_time,
            "speed": extract_speed(html),
            "course": extract_course(html),
            "heading": extract_heading(html),
            "navigation_status":
                extract_navigation_status(html),
            "waterBody": "",
            "source": "MarineRadar terrestrial AIS",
            "source_url": MARINERADAR_URL,
            "approximate_time": False,
        }

        print(
            "MarineRadar:",
            round(lat, 6),
            round(lng, 6),
            to_iso_z(fix_time),
        )

        return record

    except Exception as exc:

        print(
            "MarineRadar unavailable/unusable:",
            exc,
        )

        return None


# ============================================================
# SOURCE: VESSELFINDER
# ============================================================

def get_vesselfinder(checked_dt):

    print()
    print("Checking VesselFinder...")

    try:
        html = fetch_page(VESSELFINDER_URL)

        lat, lng = extract_coordinates(html)

        if not valid_lat_lng(lat, lng):
            raise RuntimeError(
                "position coordinates are not exposed "
                "in the public HTML"
            )

        # Prefer an exact timestamp.
        fix_time = extract_absolute_time(html)
        approximate = False

        # VesselFinder sometimes exposes only:
        # "Position received 42 hours ago"
        #
        # This is less precise but still useful for
        # comparison when an exact timestamp isn't present.
        if fix_time is None:

            received_match = re.search(
                r'Position\s+received'
                r'.{0,100}?'
                r'(\d+\s*'
                r'(?:seconds?|secs?|'
                r'minutes?|mins?|'
                r'hours?|hrs?)'
                r'\s+ago)',
                html,
                re.IGNORECASE | re.DOTALL,
            )

            if received_match:

                fix_time = relative_time_to_datetime(
                    received_match.group(1),
                    checked_dt,
                )

                approximate = True

        if fix_time is None:
            raise RuntimeError(
                "could not determine position timestamp"
            )

        record = {
            "lat": lat,
            "lng": lng,
            "time_dt": fix_time,
            "speed": extract_speed(html),
            "course": extract_course(html),
            "heading": extract_heading(html),
            "navigation_status":
                extract_navigation_status(html),
            "waterBody": "",
            "source": "VesselFinder AIS",
            "source_url": VESSELFINDER_URL,
            "approximate_time": approximate,
        }

        print(
            "VesselFinder:",
            round(lat, 6),
            round(lng, 6),
            to_iso_z(fix_time),
            "(approx)" if approximate else "",
        )

        return record

    except Exception as exc:

        print(
            "VesselFinder unavailable/unusable:",
            exc,
        )

        return None


# ============================================================
# OPTIONAL MANUAL FIX
# ============================================================

def get_manual_fix():

    if not MANUAL_FIX:
        return None

    try:

        lat = float(MANUAL_FIX["lat"])
        lng = float(MANUAL_FIX["lng"])

        fix_time = parse_iso_utc(
            MANUAL_FIX["time"]
        )

        if not valid_lat_lng(lat, lng):
            raise ValueError(
                "invalid latitude/longitude"
            )

        if fix_time is None:
            raise ValueError(
                "invalid manual timestamp"
            )

        record = {
            "lat": lat,
            "lng": lng,
            "time_dt": fix_time,
            "speed": MANUAL_FIX.get("speed"),
            "course": MANUAL_FIX.get("course"),
            "heading": MANUAL_FIX.get("heading"),
            "navigation_status":
                MANUAL_FIX.get(
                    "navigation_status"
                ),
            "waterBody":
                MANUAL_FIX.get(
                    "waterBody",
                    "",
                ),
            "source":
                MANUAL_FIX.get(
                    "source",
                    "Manual AIS fix",
                ),
            "source_url":
                MANUAL_FIX.get(
                    "source_url",
                    "",
                ),
            "approximate_time": False,
        }

        print()
        print(
            "Manual candidate:",
            lat,
            lng,
            to_iso_z(fix_time),
        )

        return record

    except Exception as exc:

        print(
            "Manual fix ignored:",
            exc,
        )

        return None


# ============================================================
# SANITY CHECK
# ============================================================

def plausible_for_current_voyage(candidate):
    """
    Basic protection against a completely erroneous AIS result.

    MORNING CARA is currently approaching New Zealand from
    Asia across the Pacific.

    For now, reject clearly impossible Atlantic/African/
    American positions.

    This deliberately allows a broad area:
       latitude  -60 to +45
       longitude 100E to 180E
       OR western Pacific across the dateline to 180W

    Remove/adjust this after the Auckland voyage if you use
    this tracker for a future voyage.
    """

    lat = candidate["lat"]
    lng = candidate["lng"]

    if not valid_lat_lng(lat, lng):
        return False

    # Broad Asia -> South Pacific -> NZ corridor.
    in_latitude = -60 <= lat <= 45

    # 100E through 180E
    east_pacific = 100 <= lng <= 180

    # Immediately east of the international date line.
    west_longitudes = -180 <= lng <= -150

    return (
        in_latitude
        and (
            east_pacific
            or west_longitudes
        )
    )


# ============================================================
# BUILD FINAL JSON RECORD
# ============================================================

def build_output(candidate, checked_at):

    fix_time = to_iso_z(
        candidate["time_dt"]
    )

    return {
        "vessel": VESSEL,
        "imo": IMO,
        "mmsi": MMSI,

        "lat": round(
            candidate["lat"],
            6,
        ),

        "lng": round(
            candidate["lng"],
            6,
        ),

        "time": fix_time,
        "reported": fix_time,

        "speed":
            candidate.get("speed"),

        "course":
            candidate.get("course"),

        "heading":
            candidate.get("heading"),

        "waterBody":
            candidate.get(
                "waterBody",
                "",
            ),

        "navigation_status":
            candidate.get(
                "navigation_status"
            ),

        "port": None,

        "position_age": None,

        "source":
            candidate["source"],

        "source_url":
            candidate.get(
                "source_url",
                "",
            ),

        "timestamp_approximate":
            candidate.get(
                "approximate_time",
                False,
            ),

        "checked_at": checked_at,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    checked_dt = utc_now()
    checked_at = to_iso_z(checked_dt)

    print("=" * 60)
    print(VESSEL, "AIS update")
    print("Checked:", checked_at)
    print("=" * 60)

    existing = load_existing()

    candidates = []

    # --------------------------------------------------------
    # ONLINE SOURCES
    # --------------------------------------------------------

    vessel_finder = get_vesselfinder(
        checked_dt
    )

    if vessel_finder:
        candidates.append(
            vessel_finder
        )

    marine_radar = get_marineradar(
        checked_dt
    )

    if marine_radar:
        candidates.append(
            marine_radar
        )

    # --------------------------------------------------------
    # OPTIONAL MANUAL CANDIDATE
    # --------------------------------------------------------

    manual = get_manual_fix()

    if manual:
        candidates.append(
            manual
        )

    # --------------------------------------------------------
    # REMOVE IMPOSSIBLE / BAD POSITIONS
    # --------------------------------------------------------

    valid_candidates = []

    for candidate in candidates:

        if plausible_for_current_voyage(
            candidate
        ):
            valid_candidates.append(
                candidate
            )

        else:
            print()
            print(
                "REJECTED implausible position:",
                candidate["source"],
                candidate["lat"],
                candidate["lng"],
                to_iso_z(
                    candidate["time_dt"]
                ),
            )

    # --------------------------------------------------------
    # IF NOTHING FOUND
    # --------------------------------------------------------

    if not valid_candidates:

        print()
        print(
            "No valid new AIS candidates."
        )

        if existing:

            existing["checked_at"] = (
                checked_at
            )

            save_record(existing)

            print(
                "Kept existing position:",
                existing.get("lat"),
                existing.get("lng"),
                existing.get("time"),
            )

            print(
                "Updated checked_at only."
            )

            return

        raise RuntimeError(
            "No valid AIS position available "
            "and there is no existing ais.json"
        )

    # --------------------------------------------------------
    # NEWEST SOURCE WINS
    # --------------------------------------------------------

    newest = max(
        valid_candidates,
        key=lambda item:
            item["time_dt"],
    )

    newest_time = newest["time_dt"]

    existing_time = None

    if existing:
        existing_time = parse_iso_utc(
            existing.get("time")
        )

    print()
    print("-" * 60)

    print(
        "Best candidate:",
        newest["source"],
    )

    print(
        "Position:",
        round(newest["lat"], 6),
        round(newest["lng"], 6),
    )

    print(
        "AIS time:",
        to_iso_z(newest_time),
    )

    # --------------------------------------------------------
    # ONLY REPLACE POSITION IF NEWER
    # --------------------------------------------------------

    if (
        existing_time is not None
        and newest_time <= existing_time
    ):

        print()
        print(
            "Candidate is not newer than "
            "existing ais.json."
        )

        print(
            "Existing:",
            to_iso_z(existing_time),
        )

        print(
            "Candidate:",
            to_iso_z(newest_time),
        )

        # Important:
        # update the check time without
        # replacing the good existing fix.
        existing["checked_at"] = (
            checked_at
        )

        save_record(existing)

        print(
            "Kept existing AIS position."
        )

        return

    # --------------------------------------------------------
    # SAVE NEW FIX
    # --------------------------------------------------------

    record = build_output(
        newest,
        checked_at,
    )

    save_record(record)

    print()
    print(
        "NEW AIS FIX SAVED"
    )

    print(
        json.dumps(
            record,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()