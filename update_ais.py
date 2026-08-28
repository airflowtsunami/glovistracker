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
DEBUG_HTML_FILE = Path("marineradar_debug.html")


# Known last credible terrestrial AIS fix before MORNING CARA
# moved out of coastal AIS range.
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
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
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
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def load_existing():
    if not OUTPUT_FILE.exists():
        return None

    try:
        with OUTPUT_FILE.open("r", encoding="utf-8") as f:
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
    if hemisphere.upper() in ("S", "W"):
        value *= -1
    return value


def normalise_iso(dt):
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def plausible_position(lat, lng):
    """
    MORNING CARA is expected on the Asia -> SW Pacific -> NZ corridor.
    Keep this deliberately broad, but reject unrelated Atlantic fixes.
    """
    if lat is None or lng is None:
        return False
    if not (-50 <= lat <= 40):
        return False
    if not (100 <= lng <= 190):
        return False
    return True


def extract_position_candidates(html):
    """Return every coordinate pair found, including its position in the HTML."""
    candidates = []

    decimal_pattern = re.compile(
        r'([-+]?\d{1,2}(?:\.\d+)?)\s*°?\s*([NS])'
        r'.{0,140}?'
        r'([-+]?\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])',
        re.IGNORECASE | re.DOTALL,
    )

    for match in decimal_pattern.finditer(html):
        try:
            lat = signed_coordinate(match.group(1), match.group(2))
            lng = signed_coordinate(match.group(3), match.group(4))
            candidates.append({
                "lat": lat,
                "lng": lng,
                "index": match.start(),
                "raw": match.group(0),
                "format": "decimal",
            })
        except Exception:
            pass

    dms_pattern = re.compile(
        r'Latitude\s*'
        r'(\d{1,2})°\s*'
        r'(\d+(?:\.\d+)?)\'?\s*'
        r'([NS])'
        r'.{0,140}?'
        r'Longitude\s*'
        r'(\d{1,3})°\s*'
        r'(\d+(?:\.\d+)?)\'?\s*'
        r'([EW])',
        re.IGNORECASE | re.DOTALL,
    )

    for match in dms_pattern.finditer(html):
        try:
            lat = float(match.group(1)) + float(match.group(2)) / 60.0
            lng = float(match.group(4)) + float(match.group(5)) / 60.0
            if match.group(3).upper() == "S":
                lat *= -1
            if match.group(6).upper() == "W":
                lng *= -1

            candidates.append({
                "lat": lat,
                "lng": lng,
                "index": match.start(),
                "raw": match.group(0),
                "format": "degrees_minutes",
            })
        except Exception:
            pass

    # De-duplicate near-identical matches that may occur in repeated markup.
    deduped = []
    seen = set()
    for c in sorted(candidates, key=lambda x: x["index"]):
        key = (round(c["lat"], 6), round(c["lng"], 6), c["index"] // 50)
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped


def extract_time_candidates(html):
    """Return every recognisable AIS-like timestamp with its HTML position."""
    candidates = []

    iso_pattern = re.compile(
        r'20\d{2}-\d{2}-\d{2}T'
        r'\d{2}:\d{2}:\d{2}(?:\.\d+)?Z',
        re.IGNORECASE,
    )

    for match in iso_pattern.finditer(html):
        dt = parse_iso_utc(match.group(0))
        if dt:
            candidates.append({
                "time": normalise_iso(dt),
                "dt": dt,
                "index": match.start(),
                "raw": match.group(0),
            })

    human_pattern = re.compile(
        r'(\d{1,2})\s+'
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
        r'(20\d{2})'
        r'.{0,40}?'
        r'(\d{2}:\d{2})\s*UTC',
        re.IGNORECASE | re.DOTALL,
    )

    for match in human_pattern.finditer(html):
        try:
            dt = datetime.strptime(
                f"{match.group(1)} {match.group(2)} "
                f"{match.group(3)} {match.group(4)}",
                "%d %b %Y %H:%M",
            ).replace(tzinfo=timezone.utc)

            candidates.append({
                "time": normalise_iso(dt),
                "dt": dt,
                "index": match.start(),
                "raw": match.group(0),
            })
        except Exception:
            pass

    # De-duplicate identical timestamp occurrences close together.
    deduped = []
    seen = set()
    for c in sorted(candidates, key=lambda x: x["index"]):
        key = (c["time"], c["index"] // 50)
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped


def context_window(html, index, radius=1800):
    start = max(0, index - radius)
    end = min(len(html), index + radius)
    return html[start:end]


def pair_position_and_time_candidates(html):
    """
    Pair each plausible position with the nearest timestamp in the page.

    This avoids the old behaviour of taking the first coordinate anywhere in
    the HTML and independently taking the first timestamp anywhere in the HTML.
    """
    positions = extract_position_candidates(html)
    times = extract_time_candidates(html)

    print(f"Found {len(positions)} coordinate candidate(s).")
    for i, p in enumerate(positions, 1):
        print(
            f"  position {i}: {p['lat']:.6f}, {p['lng']:.6f} "
            f"plausible={plausible_position(p['lat'], p['lng'])} "
            f"html_index={p['index']}"
        )

    print(f"Found {len(times)} timestamp candidate(s).")
    for i, t in enumerate(times, 1):
        print(
            f"  time {i}: {t['time']} html_index={t['index']}"
        )

    pairs = []

    for p in positions:
        if not plausible_position(p["lat"], p["lng"]):
            continue
        if not times:
            continue

        nearest_time = min(
            times,
            key=lambda t: abs(t["index"] - p["index"]),
        )
        distance = abs(nearest_time["index"] - p["index"])

        # A very distant timestamp is more likely to belong to unrelated page
        # metadata than to the coordinate block we found.
        if distance > 5000:
            print(
                "Skipping plausible coordinate because nearest timestamp is "
                f"too far away in HTML ({distance} chars): "
                f"{p['lat']:.6f}, {p['lng']:.6f}"
            )
            continue

        pairs.append({
            "lat": p["lat"],
            "lng": p["lng"],
            "position_index": p["index"],
            "time": nearest_time["time"],
            "dt": nearest_time["dt"],
            "time_index": nearest_time["index"],
            "html_distance": distance,
            "context": context_window(html, p["index"]),
        })

    # Prefer newest timestamp; for equal timestamps, prefer the tighter HTML pair.
    pairs.sort(
        key=lambda x: (x["dt"], -x["html_distance"]),
        reverse=True,
    )

    print(f"Built {len(pairs)} plausible coordinate/time pair(s).")
    for i, p in enumerate(pairs, 1):
        print(
            f"  pair {i}: {p['time']} | "
            f"{p['lat']:.6f}, {p['lng']:.6f} | "
            f"distance={p['html_distance']} chars"
        )

    return pairs


def extract_speed(text):
    patterns = [
        r'Current speed[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*kn',
        r'([0-9]+(?:\.[0-9]+)?)\s*kn',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return parse_float(match.group(1))
    return None


def extract_course(text):
    patterns = [
        r'Course(?: over ground)?[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*°',
        r'([0-9]+(?:\.[0-9]+)?)\s*°\s*/',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return parse_float(match.group(1))
    return None


def extract_heading(text):
    patterns = [
        r'Heading[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*°',
        r'[0-9.]+\s*°\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*°',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return parse_float(match.group(1))
    return None


def extract_navigation_status(text):
    statuses = [
        "Under way using engine",
        "Moored",
        "At anchor",
        "Not under command",
        "Restricted manoeuverability",
        "Constrained by her draught",
    ]
    lower_text = text.lower()
    for status in statuses:
        if status.lower() in lower_text:
            return status
    return None


def save_record(record):
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
        f.write("\n")


def save_debug_html(html):
    try:
        DEBUG_HTML_FILE.write_text(html, encoding="utf-8")
        print(f"Saved fetched MarineRadar HTML to {DEBUG_HTML_FILE}")
    except Exception as exc:
        print("Could not save debug HTML:", exc)


def main():
    checked_at = utc_now_iso()

    existing = load_existing()
    if existing is None:
        existing = seed_record(checked_at)

    try:
        html = fetch_page()
        save_debug_html(html)

        pairs = pair_position_and_time_candidates(html)

        existing_time = parse_iso_utc(existing.get("time"))
        selected = pairs[0] if pairs else None

        if selected:
            print(
                "Selected MarineRadar candidate:",
                selected["lat"],
                selected["lng"],
                selected["time"],
            )

            fresh_time = selected["dt"]

            if existing_time is None or fresh_time > existing_time:
                existing["lat"] = round(selected["lat"], 6)
                existing["lng"] = round(selected["lng"], 6)
                existing["time"] = selected["time"]
                existing["reported"] = selected["time"]

                # Only read ancillary values from the HTML near the selected
                # coordinate, rather than from unrelated parts of the page.
                context = selected["context"]
                speed = extract_speed(context)
                course = extract_course(context)
                heading = extract_heading(context)
                navigation_status = extract_navigation_status(context)

                if speed is not None:
                    existing["speed"] = speed
                if course is not None:
                    existing["course"] = course
                if heading is not None:
                    existing["heading"] = heading
                if navigation_status:
                    existing["navigation_status"] = navigation_status

                existing["source"] = "MarineRadar terrestrial AIS"
                print("Saved newer credible AIS fix.")
            else:
                print(
                    "Newest plausible MarineRadar candidate is not newer than "
                    f"the stored fix ({existing.get('time')})."
                )
        else:
            print(
                "No plausible MarineRadar coordinate/timestamp pair was found. "
                "Kept the stored AIS fix."
            )

        # Always record that MarineRadar was checked.
        existing["checked_at"] = checked_at
        existing["source_url"] = SOURCE_URL
        save_record(existing)

        print(json.dumps(existing, indent=2))

    except Exception as exc:
        # Do not fail GitHub Actions simply because the public AIS site is
        # unavailable or changes its HTML.
        print("AIS source check failed:", exc)

        existing["checked_at"] = checked_at
        existing["source_url"] = SOURCE_URL
        save_record(existing)

        print("Kept existing MORNING CARA fix and updated checked_at.")
        print(json.dumps(existing, indent=2))


if __name__ == "__main__":
    main()
