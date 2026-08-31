import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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

MARITIME_OPTIMA_URL = (
    "https://maritimeoptima.com/public/vessels/pages/"
    "imo:9574092/mmsi:441148000/MORNING_CARA.html"
)

MARINERADAR_URL = (
    "https://www.marineradar.com/vessel/"
    "mmsi-441148000/morning-cara"
)


POAL_ARRIVALS_URL = (
    "https://www.poal.co.nz/operations/schedules/arrivals"
)

NZ_TZ = ZoneInfo("Pacific/Auckland")


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-NZ,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


# ============================================================
# MANUAL FALLBACK
#
# Leave as None normally.
#
# If you know an exact AIS position which is newer than all
# scraped sources, enter it here.
#
# IMPORTANT:
# time MUST be the actual GMT/UTC timestamp of the position.
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
# The manual fix does NOT permanently override online data.
# Any newer online fix automatically wins.
# ============================================================

MANUAL_FIX = None


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def to_iso_z(dt):
    if dt is None:
        return None

    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def valid_lat_lng(lat, lng):
    return (
        lat is not None
        and lng is not None
        and -90 <= lat <= 90
        and -180 <= lng <= 180
    )


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


# ============================================================
# HTTP FETCH
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
# AIS.JSON
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

        if str(data.get("imo", "")) != IMO:
            print("Existing ais.json belongs to another vessel.")
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
# TIME PARSING
# ============================================================

def extract_absolute_time(text):
    """
    Recognises things such as:

      2026-08-28T06:50:00Z
      2026-08-28T06:50:00+00:00
      28 Aug 2026 06:50 UTC
      28 Aug 2026 06:50 GMT
      Aug 28, 2026 06:50 UTC
    """

    # ISO Z
    match = re.search(
        r'(20\d{2}-\d{2}-\d{2}'
        r'T\d{2}:\d{2}:\d{2}'
        r'(?:\.\d+)?Z)',
        text,
        re.IGNORECASE,
    )

    if match:
        return parse_iso_utc(match.group(1))

    # ISO +00:00
    match = re.search(
        r'(20\d{2}-\d{2}-\d{2}'
        r'T\d{2}:\d{2}:\d{2}'
        r'(?:\.\d+)?\+00:00)',
        text,
        re.IGNORECASE,
    )

    if match:
        return parse_iso_utc(match.group(1))

    # 28 Aug 2026 06:50 UTC / GMT
    match = re.search(
        r'(\d{1,2})\s+'
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        r'\s+(20\d{2})'
        r'.{0,40}?'
        r'(\d{1,2}:\d{2})'
        r'\s*(?:UTC|GMT)',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        try:
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

        except ValueError:
            pass

    # Aug 28, 2026 06:50 UTC / GMT
    match = re.search(
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        r'\s+(\d{1,2}),?\s+(20\d{2})'
        r'.{0,40}?'
        r'(\d{1,2}:\d{2})'
        r'\s*(?:UTC|GMT)',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        try:
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

        except ValueError:
            pass

    return None


def relative_time_to_datetime(text, checked_dt):
    """
    Converts:

      2 min ago
      35 minutes ago
      1 hour ago
      4 hours ago
    """

    match = re.search(
        r'(\d+)\s*'
        r'(seconds?|secs?|'
        r'minutes?|mins?|'
        r'hours?|hrs?)'
        r'\s+ago',
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if unit.startswith("sec"):
        return checked_dt - timedelta(seconds=amount)

    if unit.startswith("min"):
        return checked_dt - timedelta(minutes=amount)

    if unit.startswith("hour") or unit.startswith("hr"):
        return checked_dt - timedelta(hours=amount)

    return None


# ============================================================
# COORDINATE EXTRACTION
# ============================================================

def decimal_from_degrees_minutes(
    degrees,
    minutes,
    hemisphere,
):
    value = float(degrees) + float(minutes) / 60

    if hemisphere.upper() in ("S", "W"):
        value *= -1

    return value


def extract_coordinates(text):
    """
    Tries several common representations.
    """

    # --------------------------------------------------------
    # Latitude 34° 7.033' S Longitude 173° 33.702' E
    # --------------------------------------------------------

    match = re.search(
        r'Latitude\s*'
        r'(\d{1,2})\s*°\s*'
        r'(\d+(?:\.\d+)?)'
        r'\s*[\'′]?\s*([NS])'
        r'.{0,150}?'
        r'Longitude\s*'
        r'(\d{1,3})\s*°\s*'
        r'(\d+(?:\.\d+)?)'
        r'\s*[\'′]?\s*([EW])',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        lat = decimal_from_degrees_minutes(
            match.group(1),
            match.group(2),
            match.group(3),
        )

        lng = decimal_from_degrees_minutes(
            match.group(4),
            match.group(5),
            match.group(6),
        )

        if valid_lat_lng(lat, lng):
            return lat, lng

    # --------------------------------------------------------
    # Latitude -34.117220 Longitude 173.561701
    # --------------------------------------------------------

    match = re.search(
        r'Latitude'
        r'[^0-9+\-]{0,30}'
        r'([-+]?\d{1,2}(?:\.\d+)?)'
        r'.{0,100}?'
        r'Longitude'
        r'[^0-9+\-]{0,30}'
        r'([-+]?\d{1,3}(?:\.\d+)?)',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        lat = parse_float(match.group(1))
        lng = parse_float(match.group(2))

        if valid_lat_lng(lat, lng):
            return lat, lng

    # --------------------------------------------------------
    # 34.117 S, 173.561 E
    # --------------------------------------------------------

    match = re.search(
        r'(\d{1,2}(?:\.\d+)?)'
        r'\s*°?\s*([NS])'
        r'\s*[,;/]?\s*'
        r'(\d{1,3}(?:\.\d+)?)'
        r'\s*°?\s*([EW])',
        text,
        re.IGNORECASE,
    )

    if match:
        lat = float(match.group(1))
        lng = float(match.group(3))

        if match.group(2).upper() == "S":
            lat *= -1

        if match.group(4).upper() == "W":
            lng *= -1

        if valid_lat_lng(lat, lng):
            return lat, lng

    # --------------------------------------------------------
    # JSON: lat/lon
    # --------------------------------------------------------

    json_patterns = [
        (
            r'["\']lat["\']\s*:\s*'
            r'["\']?([-+]?\d{1,2}\.\d+)["\']?'
            r'.{0,100}?'
            r'["\'](?:lon|lng)["\']\s*:\s*'
            r'["\']?([-+]?\d{1,3}\.\d+)["\']?'
        ),
        (
            r'["\']latitude["\']\s*:\s*'
            r'["\']?([-+]?\d{1,2}\.\d+)["\']?'
            r'.{0,100}?'
            r'["\']longitude["\']\s*:\s*'
            r'["\']?([-+]?\d{1,3}\.\d+)["\']?'
        ),
    ]

    for pattern in json_patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            lat = parse_float(match.group(1))
            lng = parse_float(match.group(2))

            if valid_lat_lng(lat, lng):
                return lat, lng

    # --------------------------------------------------------
    # JS: lat = x, lon = y
    # --------------------------------------------------------

    match = re.search(
        r'\blat(?:itude)?\s*[=:]\s*'
        r'["\']?([-+]?\d{1,2}\.\d+)'
        r'.{0,100}?'
        r'\b(?:lon|lng|longitude)\s*[=:]\s*'
        r'["\']?([-+]?\d{1,3}\.\d+)',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        lat = parse_float(match.group(1))
        lng = parse_float(match.group(2))

        if valid_lat_lng(lat, lng):
            return lat, lng

    # --------------------------------------------------------
    # Plain decimal pair.
    #
    # Require 4+ decimal places to reduce accidental matches.
    # --------------------------------------------------------

    matches = re.findall(
        r'([-+]?\d{1,2}\.\d{4,})'
        r'\s*[,;/]\s*'
        r'([-+]?\d{1,3}\.\d{4,})',
        text,
    )

    for lat_text, lng_text in matches:
        lat = parse_float(lat_text)
        lng = parse_float(lng_text)

        if valid_lat_lng(lat, lng):
            return lat, lng

    return None, None


# ============================================================
# SPEED / COURSE / HEADING
# ============================================================

def extract_speed(text):
    patterns = [
        r'speed'
        r'[^0-9]{0,30}'
        r'([0-9]+(?:\.[0-9]+)?)'
        r'\s*(?:kn|kts|knots)',

        r'sailing\s+at\s+'
        r'(?:a\s+speed\s+of\s+)?'
        r'([0-9]+(?:\.[0-9]+)?)'
        r'\s*(?:kn|kts|knots)',
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
        r'course'
        r'[^0-9]{0,30}'
        r'([0-9]+(?:\.[0-9]+)?)\s*°',

        r'["\']cog["\']'
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
            value = parse_float(match.group(1))

            if value is not None and 0 <= value <= 360:
                return value

    return None


def extract_heading(text):
    match = re.search(
        r'heading'
        r'[^0-9]{0,30}'
        r'([0-9]+(?:\.[0-9]+)?)'
        r'\s*°',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        value = parse_float(match.group(1))

        if value is not None and 0 <= value <= 360:
            return value

    return None


# ============================================================
# NAVIGATION STATUS
# ============================================================

def extract_navigation_status(text):
    statuses = [
        "Under way using engine",
        "Under way",
        "Moored",
        "At anchor",
        "Not under command",
        "Restricted manoeuverability",
        "Constrained by her draught",
    ]

    text_lower = text.lower()

    for status in statuses:
        if status.lower() in text_lower:
            return status

    return None


# ============================================================
# SOURCE-SPECIFIC TIMESTAMP EXTRACTION
# ============================================================

def extract_vesselfinder_time(
    text,
    checked_dt,
):
    """
    VesselFinder often displays:

       Position received | 2 min ago
    """

    match = re.search(
        r'Position\s+received'
        r'.{0,120}?'
        r'(\d+\s*'
        r'(?:seconds?|secs?|'
        r'minutes?|mins?|'
        r'hours?|hrs?)'
        r'\s+ago)',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        return (
            relative_time_to_datetime(
                match.group(1),
                checked_dt,
            ),
            True,
        )

    exact = extract_absolute_time(text)

    if exact:
        return exact, False

    return None, False


def extract_marineradar_time(text):
    """
    Prefer MarineRadar's actual AIS last-updated timestamp.
    """

    patterns = [
        (
            r'AIS\s+last\s+updated'
            r'.{0,40}?'
            r'(20\d{2}-\d{2}-\d{2}'
            r'T\d{2}:\d{2}:\d{2}Z)'
        ),

        (
            r'most\s+recent\s+report'
            r'.{0,250}?'
            r'(\d{1,2}\s+'
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
            r'\s+20\d{2}'
            r'.{0,30}?'
            r'\d{1,2}:\d{2}'
            r'\s*(?:UTC|GMT))'
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            parsed = extract_absolute_time(
                match.group(1)
            )

            if parsed:
                return parsed

    return extract_absolute_time(text)


# ============================================================
# VESSELFINDER
# ============================================================

def get_vesselfinder(checked_dt):
    print()
    print("Checking VesselFinder...")

    try:
        html = fetch_page(
            VESSELFINDER_URL
        )

        lat, lng = extract_coordinates(
            html
        )

        if not valid_lat_lng(lat, lng):
            raise RuntimeError(
                "fresh position exists but exact "
                "coordinates were not exposed in "
                "the downloaded page"
            )

        fix_time, approximate = (
            extract_vesselfinder_time(
                html,
                checked_dt,
            )
        )

        if fix_time is None:
            raise RuntimeError(
                "position timestamp not found"
            )

        result = {
            "lat": lat,
            "lng": lng,
            "time_dt": fix_time,
            "speed": extract_speed(html),
            "course": extract_course(html),
            "heading": extract_heading(html),
            "navigation_status":
                extract_navigation_status(html),
            "source": "VesselFinder AIS",
            "source_url": VESSELFINDER_URL,
            "timestamp_approximate":
                approximate,
        }

        print(
            "VesselFinder candidate:",
            round(lat, 6),
            round(lng, 6),
            to_iso_z(fix_time),
        )

        return result

    except Exception as exc:
        print(
            "VesselFinder skipped:",
            exc,
        )

        return None


# ============================================================
# MARINERADAR
# ============================================================

def get_marineradar():
    print()
    print("Checking MarineRadar...")

    try:
        html = fetch_page(
            MARINERADAR_URL
        )

        lat, lng = extract_coordinates(
            html
        )

        if not valid_lat_lng(lat, lng):
            raise RuntimeError(
                "coordinates not found"
            )

        fix_time = extract_marineradar_time(
            html
        )

        if fix_time is None:
            raise RuntimeError(
                "exact AIS timestamp not found"
            )

        result = {
            "lat": lat,
            "lng": lng,
            "time_dt": fix_time,
            "speed": extract_speed(html),
            "course": extract_course(html),
            "heading": extract_heading(html),
            "navigation_status":
                extract_navigation_status(html),
            "source":
                "MarineRadar terrestrial AIS",
            "source_url":
                MARINERADAR_URL,
            "timestamp_approximate":
                False,
        }

        print(
            "MarineRadar candidate:",
            round(lat, 6),
            round(lng, 6),
            to_iso_z(fix_time),
        )

        return result

    except Exception as exc:
        print(
            "MarineRadar skipped:",
            exc,
        )

        return None


# ============================================================
# MARITIME OPTIMA
#
# Public page is useful for confirming freshness/location area
# but generally does NOT expose exact lat/lng.
#
# It therefore does not create a candidate unless coordinates
# happen to be present in the returned HTML.
# ============================================================

def get_maritime_optima(
    checked_dt,
):
    print()
    print("Checking Maritime Optima...")

    try:
        html = fetch_page(
            MARITIME_OPTIMA_URL
        )

        lat, lng = extract_coordinates(
            html
        )

        match = re.search(
            r'AIS\s+data\s+received\s+'
            r'(\d+\s*'
            r'(?:seconds?|secs?|'
            r'minutes?|mins?|'
            r'hours?|hrs?)'
            r'\s+ago)',
            html,
            re.IGNORECASE,
        )

        fix_time = None

        if match:
            fix_time = (
                relative_time_to_datetime(
                    match.group(1),
                    checked_dt,
                )
            )

        location_text = None

        location_match = re.search(
            r'is\s+currently\s+in\s+'
            r'(.*?),\s*based\s+on\s+AIS',
            html,
            re.IGNORECASE,
        )

        if location_match:
            location_text = (
                re.sub(
                    r'<[^>]+>',
                    '',
                    location_match.group(1),
                )
                .strip()
            )

        print(
            "Maritime Optima reports:",
            location_text or "location unknown",
            to_iso_z(fix_time)
            if fix_time
            else "timestamp unavailable",
        )

        if not valid_lat_lng(lat, lng):
            print(
                "Maritime Optima has no public "
                "exact coordinates; using it only "
                "as corroboration."
            )
            return None

        if fix_time is None:
            return None

        return {
            "lat": lat,
            "lng": lng,
            "time_dt": fix_time,
            "speed": extract_speed(html),
            "course": extract_course(html),
            "heading": extract_heading(html),
            "navigation_status":
                extract_navigation_status(html),
            "source":
                "Maritime Optima AIS",
            "source_url":
                MARITIME_OPTIMA_URL,
            "timestamp_approximate":
                True,
        }

    except Exception as exc:
        print(
            "Maritime Optima skipped:",
            exc,
        )

        return None


# ============================================================
# MANUAL FIX
# ============================================================

def get_manual_fix():
    if not MANUAL_FIX:
        return None

    print()
    print("Checking manual AIS candidate...")

    try:
        lat = float(
            MANUAL_FIX["lat"]
        )

        lng = float(
            MANUAL_FIX["lng"]
        )

        fix_time = parse_iso_utc(
            MANUAL_FIX["time"]
        )

        if not valid_lat_lng(lat, lng):
            raise RuntimeError(
                "invalid coordinates"
            )

        if fix_time is None:
            raise RuntimeError(
                "invalid timestamp"
            )

        return {
            "lat": lat,
            "lng": lng,
            "time_dt": fix_time,
            "speed":
                MANUAL_FIX.get("speed"),
            "course":
                MANUAL_FIX.get("course"),
            "heading":
                MANUAL_FIX.get("heading"),
            "navigation_status":
                MANUAL_FIX.get(
                    "navigation_status"
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
            "timestamp_approximate":
                False,
        }

    except Exception as exc:
        print(
            "Manual candidate invalid:",
            exc,
        )

        return None


# ============================================================
# VOYAGE SANITY CHECK
#
# MORNING CARA is currently on Shanghai -> Auckland.
#
# This broad box protects you from garbage fixes on a totally
# different side of the planet.
#
# It allows:
#
#    East Asia
#    Western Pacific
#    South Pacific
#    New Zealand
#
# including either side of the international date line.
#
# Once the Auckland voyage finishes, you can loosen/remove
# this if you want to track the next voyage.
# ============================================================

def plausible_for_current_voyage(
    candidate,
):
    lat = candidate["lat"]
    lng = candidate["lng"]

    if not valid_lat_lng(lat, lng):
        return False

    if not (-60 <= lat <= 45):
        return False

    # 100E -> date line
    if 100 <= lng <= 180:
        return True

    # immediately east of date line
    if -180 <= lng <= -140:
        return True

    return False


# ============================================================
# CANDIDATE AGE PROTECTION
# ============================================================

def candidate_not_in_future(
    candidate,
    now,
):
    """
    Permit a little clock skew but reject absurd future fixes.
    """

    return (
        candidate["time_dt"]
        <= now + timedelta(minutes=10)
    )


# ============================================================
# PORTS OF AUCKLAND ETA
# ============================================================

def parse_poal_local_datetime(value):
    """
    POAL arrival times are displayed in Auckland local time.
    Convert them to UTC for ais.json.
    """
    if not value:
        return None

    value = re.sub(r"\s+", " ", str(value)).strip()

    for fmt in (
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
    ):
        try:
            local_dt = datetime.strptime(value, fmt).replace(
                tzinfo=NZ_TZ
            )
            return local_dt.astimezone(timezone.utc)
        except ValueError:
            pass

    return None


def strip_html_to_text(html):
    """
    Lightweight HTML-to-text conversion with no extra dependency.
    """
    text = re.sub(
        r"(?is)<script\b.*?</script>",
        " ",
        html,
    )
    text = re.sub(
        r"(?is)<style\b.*?</style>",
        " ",
        text,
    )
    text = re.sub(
        r"(?s)<[^>]+>",
        " ",
        text,
    )
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def get_poal_eta():
    """
    Get MORNING CARA's current Ports of Auckland expected arrival.

    POAL defines the 'Arrival' field for expected arrivals as
    pilot boarding time. POAL also says pilot station -> berth
    is approximately 1.5 hours, so both times are returned.
    """
    print()
    print("Checking Ports of Auckland ETA...")

    result = {
        "poal_eta": None,
        "poal_pilot_boarding_eta": None,
        "poal_berth_eta": None,
        "poal_wharf": None,
        "poal_vessel_ref": None,
        "poal_schedule_updated_at": None,
        "poal_source_url": POAL_ARRIVALS_URL,
    }

    try:
        html = fetch_page(POAL_ARRIVALS_URL)
        text = strip_html_to_text(html)

        updated_match = re.search(
            r"Last updated:\s*"
            r"(\d{1,2}\s+"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+20\d{2}\s+\d{1,2}:\d{2})",
            text,
            re.IGNORECASE,
        )

        if updated_match:
            updated_dt = parse_poal_local_datetime(
                updated_match.group(1)
            )
            result["poal_schedule_updated_at"] = to_iso_z(
                updated_dt
            )

        # Match the MORNING CARA row by vessel name + IMO.
        row_match = re.search(
            r"MORNING\s+CARA\s+"
            r"(.*?)"
            r"\b9574092\b"
            r"(.*?)"
            r"(?="
            r"\b[A-Z][A-Z0-9 .()'\-]{2,}\s+\|?"
            r"|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        # On the current POAL page the flattened row is:
        # MORNING CARA ... Bledisloe West (B3) MOC4487 9574092
        # OO635 OO635 Refer to Line Refer to Line
        # 2 Sep 2026 18:00 4 Sep 2026 23:04 ...
        #
        # Rather than relying on the end-of-row expression above,
        # use a bounded slice beginning at MORNING CARA if needed.
        start = re.search(
            r"\bMORNING\s+CARA\b",
            text,
            re.IGNORECASE,
        )

        if not start:
            raise RuntimeError(
                "MORNING CARA not found on POAL arrivals page"
            )

        vessel_slice = text[
            start.start():
            start.start() + 1400
        ]

        if "9574092" not in vessel_slice:
            raise RuntimeError(
                "MORNING CARA row found but IMO 9574092 was not nearby"
            )

        eta_match = re.search(
            r"\b9574092\b"
            r".{0,500}?"
            r"(\d{1,2}\s+"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+20\d{2}\s+\d{1,2}:\d{2})",
            vessel_slice,
            re.IGNORECASE | re.DOTALL,
        )

        if not eta_match:
            raise RuntimeError(
                "POAL arrival time not found in MORNING CARA row"
            )

        pilot_dt = parse_poal_local_datetime(
            eta_match.group(1)
        )

        if pilot_dt is None:
            raise RuntimeError(
                "POAL arrival time could not be parsed"
            )

        berth_dt = pilot_dt + timedelta(
            minutes=90
        )

        result["poal_eta"] = to_iso_z(
            pilot_dt
        )
        result["poal_pilot_boarding_eta"] = to_iso_z(
            pilot_dt
        )
        result["poal_berth_eta"] = to_iso_z(
            berth_dt
        )

        wharf_match = re.search(
            r"MORNING\s+CARA\s+"
            r".{0,250}?"
            r"([A-Za-z][A-Za-z ]+\([A-Z0-9]+\))"
            r".{0,80}?"
            r"(MOC\d+)"
            r".{0,80}?"
            r"\b9574092\b",
            vessel_slice,
            re.IGNORECASE | re.DOTALL,
        )

        if wharf_match:
            result["poal_wharf"] = re.sub(
                r"\s+",
                " ",
                wharf_match.group(1),
            ).strip()

            result["poal_vessel_ref"] = (
                wharf_match.group(2).upper()
            )

        print(
            "POAL pilot boarding ETA:",
            result["poal_pilot_boarding_eta"],
        )
        print(
            "POAL approximate berth ETA:",
            result["poal_berth_eta"],
        )

        if result["poal_wharf"]:
            print(
                "POAL wharf:",
                result["poal_wharf"],
            )

        return result

    except Exception as exc:
        print(
            "Ports of Auckland ETA skipped:",
            exc,
        )
        return None


# ============================================================
# OUTPUT RECORD
# ============================================================

def build_output(
    candidate,
    checked_at,
    poal=None,
):
    fix_iso = to_iso_z(
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

        "time": fix_iso,
        "reported": fix_iso,

        "speed":
            candidate.get("speed"),

        "course":
            candidate.get("course"),

        "heading":
            candidate.get("heading"),

        "navigation_status":
            candidate.get(
                "navigation_status"
            ),

        "waterBody":
            candidate.get(
                "waterBody",
                "",
            ),

        "port": None,

        "source":
            candidate["source"],

        "source_url":
            candidate.get(
                "source_url",
                "",
            ),

        "timestamp_approximate":
            candidate.get(
                "timestamp_approximate",
                False,
            ),

        "checked_at":
            checked_at,

        "poal_eta":
            (poal or {}).get("poal_eta"),

        "poal_pilot_boarding_eta":
            (poal or {}).get(
                "poal_pilot_boarding_eta"
            ),

        "poal_berth_eta":
            (poal or {}).get(
                "poal_berth_eta"
            ),

        "poal_wharf":
            (poal or {}).get("poal_wharf"),

        "poal_vessel_ref":
            (poal or {}).get(
                "poal_vessel_ref"
            ),

        "poal_schedule_updated_at":
            (poal or {}).get(
                "poal_schedule_updated_at"
            ),

        "poal_source_url":
            (poal or {}).get(
                "poal_source_url",
                POAL_ARRIVALS_URL,
            ),
    }


def apply_poal_to_record(record, poal):
    if record is None:
        return None

    # A failed POAL fetch must not erase the last good schedule.
    if not poal:
        return record

    record["poal_eta"] = (
        poal.get("poal_eta")
        if poal.get("poal_eta") is not None
        else record.get("poal_eta")
    )
    record["poal_pilot_boarding_eta"] = (
        poal.get("poal_pilot_boarding_eta")
        if poal.get("poal_pilot_boarding_eta") is not None
        else record.get("poal_pilot_boarding_eta")
    )
    record["poal_berth_eta"] = (
        poal.get("poal_berth_eta")
        if poal.get("poal_berth_eta") is not None
        else record.get("poal_berth_eta")
    )
    record["poal_wharf"] = (
        poal.get("poal_wharf")
        if poal.get("poal_wharf") is not None
        else record.get("poal_wharf")
    )
    record["poal_vessel_ref"] = (
        poal.get("poal_vessel_ref")
        if poal.get("poal_vessel_ref") is not None
        else record.get("poal_vessel_ref")
    )
    record["poal_schedule_updated_at"] = (
        poal.get("poal_schedule_updated_at")
        if poal.get("poal_schedule_updated_at") is not None
        else record.get("poal_schedule_updated_at")
    )
    record["poal_source_url"] = (
        (poal or {}).get(
            "poal_source_url",
            record.get(
                "poal_source_url",
                POAL_ARRIVALS_URL,
            ),
        )
    )
    return record


# ============================================================
# MAIN
# ============================================================

def main():
    checked_dt = utc_now()
    checked_at = to_iso_z(
        checked_dt
    )

    print("=" * 65)
    print(VESSEL)
    print("IMO:", IMO)
    print("MMSI:", MMSI)
    print("Checked:", checked_at)
    print("=" * 65)

    existing = load_existing()

    # POAL schedule is independent of AIS freshness.
    # Fetch it every run so an ETA change is saved even when
    # no newer vessel position is available.
    poal = get_poal_eta()

    candidates = []

    # --------------------------------------------------------
    # FETCH ALL SOURCES
    # --------------------------------------------------------

    source_functions = [
        lambda: get_vesselfinder(
            checked_dt
        ),
        lambda: get_maritime_optima(
            checked_dt
        ),
        get_marineradar,
        get_manual_fix,
    ]

    for source_function in source_functions:
        try:
            candidate = (
                source_function()
            )

            if candidate:
                candidates.append(
                    candidate
                )

        except Exception as exc:
            print(
                "Unexpected source error:",
                exc,
            )

    # --------------------------------------------------------
    # VALIDATE CANDIDATES
    # --------------------------------------------------------

    valid_candidates = []

    for candidate in candidates:
        source = candidate["source"]

        if not candidate_not_in_future(
            candidate,
            checked_dt,
        ):
            print()
            print(
                "REJECTED future timestamp:",
                source,
                to_iso_z(
                    candidate["time_dt"]
                ),
            )
            continue

        if not plausible_for_current_voyage(
            candidate
        ):
            print()
            print(
                "REJECTED implausible position:",
                source,
                candidate["lat"],
                candidate["lng"],
                to_iso_z(
                    candidate["time_dt"]
                ),
            )
            continue

        valid_candidates.append(
            candidate
        )

    # --------------------------------------------------------
    # NO VALID SCRAPED POSITIONS
    # --------------------------------------------------------

    if not valid_candidates:
        print()
        print(
            "No valid fresh AIS candidate "
            "was obtained."
        )

        if existing:
            existing["checked_at"] = (
                checked_at
            )

            apply_poal_to_record(
                existing,
                poal,
            )

            save_record(existing)

            print(
                "Existing AIS position retained:"
            )

            print(
                existing.get("lat"),
                existing.get("lng"),
                existing.get("time"),
            )

            return

        raise RuntimeError(
            "No AIS position could be "
            "obtained and ais.json does "
            "not already exist."
        )

    # --------------------------------------------------------
    # SHOW ALL VALID CANDIDATES
    # --------------------------------------------------------

    print()
    print("=" * 65)
    print("VALID AIS CANDIDATES")
    print("=" * 65)

    for candidate in sorted(
        valid_candidates,
        key=lambda x: x["time_dt"],
        reverse=True,
    ):
        print(
            candidate["source"],
            "|",
            round(
                candidate["lat"],
                6,
            ),
            round(
                candidate["lng"],
                6,
            ),
            "|",
            to_iso_z(
                candidate["time_dt"]
            ),
            "| approx:"
            if candidate.get(
                "timestamp_approximate"
            )
            else "| exact:",
            candidate.get(
                "timestamp_approximate",
                False,
            ),
        )

    # --------------------------------------------------------
    # NEWEST TIMESTAMP WINS
    # --------------------------------------------------------

    newest = max(
        valid_candidates,
        key=lambda item:
            item["time_dt"],
    )

    newest_time = (
        newest["time_dt"]
    )

    print()
    print("=" * 65)

    print(
        "WINNER:",
        newest["source"],
    )

    print(
        "POSITION:",
        round(
            newest["lat"],
            6,
        ),
        round(
            newest["lng"],
            6,
        ),
    )

    print(
        "TIME:",
        to_iso_z(
            newest_time
        ),
    )

    # --------------------------------------------------------
    # CHECK AGAINST EXISTING AIS.JSON
    # --------------------------------------------------------

    existing_time = None

    if existing:
        existing_time = parse_iso_utc(
            existing.get("time")
        )

    if (
        existing_time is not None
        and newest_time <= existing_time
    ):
        print()
        print(
            "Best scraped candidate is "
            "not newer than ais.json."
        )

        print(
            "Existing:",
            to_iso_z(
                existing_time
            ),
        )

        print(
            "Candidate:",
            to_iso_z(
                newest_time
            ),
        )

        existing["checked_at"] = (
            checked_at
        )

        apply_poal_to_record(
            existing,
            poal,
        )

        save_record(existing)

        print()
        print(
            "Kept existing position."
        )

        return

    # --------------------------------------------------------
    # SAVE NEW POSITION
    # --------------------------------------------------------

    record = build_output(
        newest,
        checked_at,
        poal,
    )

    if not poal and existing:
        for key in (
            "poal_eta",
            "poal_pilot_boarding_eta",
            "poal_berth_eta",
            "poal_wharf",
            "poal_vessel_ref",
            "poal_schedule_updated_at",
            "poal_source_url",
        ):
            if existing.get(key) is not None:
                record[key] = existing.get(key)

    save_record(record)

    print()
    print("=" * 65)
    print("NEW AIS POSITION SAVED")
    print("=" * 65)

    print(
        json.dumps(
            record,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
