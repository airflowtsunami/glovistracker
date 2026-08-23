import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests


IMO = "9590589"
MMSI = "441200000"
VESSEL = "GLOVIS CENTURY"

VESSELFINDER_URL = (
    "https://www.vesselfinder.com/vessels/details/9590589"
)

VOYAGE_RADAR_URL = (
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


# --------------------------------------------------
# Known port coordinates
#
# These are used only when VesselFinder says the ship
# has actually arrived/moored at the named port.
# --------------------------------------------------

KNOWN_PORTS = {
    "suva": {
        "lat": -18.1416,
        "lng": 178.4419,
    },
    "auckland": {
        "lat": -36.8406,
        "lng": 174.7850,
    },
}


def find(pattern, text, flags=re.I | re.S):
    match = re.search(pattern, text, flags)

    if not match:
        return None

    return match.group(1).strip()


def fetch(url):
    print("Fetching:", url)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    print("HTTP status:", response.status_code)

    response.raise_for_status()

    if len(response.text) < 500:
        raise RuntimeError(
            f"Response unexpectedly small from {url}"
        )

    return response.text


def strip_html(html):
    text = re.sub(
        r"<script.*?</script>",
        " ",
        html,
        flags=re.I | re.S,
    )

    text = re.sub(
        r"<style.*?</style>",
        " ",
        text,
        flags=re.I | re.S,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


# --------------------------------------------------
# VesselFinder
# --------------------------------------------------

def parse_vesselfinder(html):

    plain = strip_html(html)

    result = {
        "source": "VesselFinder",
        "source_url": VESSELFINDER_URL,
        "navigation_status": None,
        "port": None,
        "arrival_time": None,
        "position_age_text": None,
        "lat": None,
        "lng": None,
    }


    # ----------------------------------------------
    # Navigation status
    # Example:
    # Navigation Status Moored
    # ----------------------------------------------

    nav = find(
        r"Navigation Status\s+"
        r"([A-Za-z ]+?)\s+"
        r"(?:Position received|IMO|AIS Type)",
        plain,
    )

    if nav:
        result["navigation_status"] = nav.strip()


    # ----------------------------------------------
    # Position age
    #
    # Example:
    # Position received 2 hours ago
    # ----------------------------------------------

    age = find(
        r"Position received\s+"
        r"(.+?)\s+"
        r"(?:IMO\s*/\s*MMSI|IMO)",
        plain,
    )

    if age:
        result["position_age_text"] = age.strip()


    # ----------------------------------------------
    # Arrived port
    #
    # Example:
    # arrived at the port of Suva, Fiji
    # ----------------------------------------------

    port = find(
        r"arrived at the port of\s+"
        r"([A-Za-z .'-]+?)(?:,\s*[A-Za-z ]+)?\s+on\s+",
        plain,
    )

    if port:
        result["port"] = port.strip()


    # ----------------------------------------------
    # Actual arrival time
    #
    # Example:
    # ATA: Aug 22, 19:55 UTC
    # ----------------------------------------------

    ata = find(
        r"ATA:\s*"
        r"([A-Za-z]{3}\s+"
        r"\d{1,2},\s+"
        r"\d{1,2}:\d{2}\s+UTC)",
        plain,
    )

    if ata:

        year = datetime.now(timezone.utc).year

        dt = datetime.strptime(
            f"{ata} {year}",
            "%b %d, %H:%M UTC %Y",
        ).replace(
            tzinfo=timezone.utc
        )

        result["arrival_time"] = (
            dt.isoformat()
            .replace("+00:00", "Z")
        )


    # ----------------------------------------------
    # Attempt to find embedded coordinates
    #
    # VesselFinder sometimes changes its HTML, so we
    # try several common JSON/JS forms.
    # ----------------------------------------------

    lat_patterns = [
        r'"lat"\s*:\s*(-?\d{1,2}\.\d+)',
        r'"latitude"\s*:\s*(-?\d{1,2}\.\d+)',
        r'\blat\s*[:=]\s*(-?\d{1,2}\.\d+)',
    ]

    lng_patterns = [
        r'"lon"\s*:\s*(-?\d{1,3}\.\d+)',
        r'"lng"\s*:\s*(-?\d{1,3}\.\d+)',
        r'"longitude"\s*:\s*(-?\d{1,3}\.\d+)',
        r'\b(?:lon|lng)\s*[:=]\s*(-?\d{1,3}\.\d+)',
    ]

    for pattern in lat_patterns:
        value = find(pattern, html)
        if value is not None:
            result["lat"] = float(value)
            break

    for pattern in lng_patterns:
        value = find(pattern, html)
        if value is not None:
            result["lng"] = float(value)
            break


    return result


# --------------------------------------------------
# Voyage Radar fallback
# --------------------------------------------------

def parse_voyage_radar(html):

    plain = strip_html(html)

    lat = find(
        r"Latitude\s+"
        r"([+-]?\d{1,2}\.\d+)",
        plain,
    )

    lng = find(
        r"Longitude\s+"
        r"([+-]?\d{1,3}\.\d+)",
        plain,
    )


    if not lat or not lng:

        position = re.search(
            r"position\s+"
            r"([0-9.]+)°([NS]),\s*"
            r"([0-9.]+)°([EW])",
            plain,
            re.I,
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
            "Could not extract coordinates "
            "from Voyage Radar"
        )


    lat = float(lat)
    lng = float(lng)


    speed = find(
        r"Speed\s+"
        r"([0-9.]+)\s*kn",
        plain,
    )

    if speed is None:
        speed = find(
            r"moving at\s+"
            r"([0-9.]+)\s+knots",
            plain,
        )

    speed = (
        float(speed)
        if speed is not None
        else None
    )


    course = find(
        r"Course Over Ground\s*"
        r"\(COG\)\s*"
        r"([0-9.]+)°",
        plain,
    )

    course = (
        float(course)
        if course is not None
        else None
    )


    heading = find(
        r"True Heading\s+"
        r"([0-9.]+)°",
        plain,
    )

    heading = (
        float(heading)
        if heading is not None
        else None
    )


    water_body = find(
        r"Water Body\s+"
        r"(.+?)\s+"
        r"Last Update",
        plain,
    )


    reported = find(
        r"Last Update\s*"
        r"\(UTC\)\s*"
        r"(\d{1,2}\s+"
        r"[A-Za-z]{3}\s+"
        r"\d{4},?\s+"
        r"\d{1,2}:\d{2}\s+UTC)",
        plain,
    )


    if not reported:

        reported = find(
            r"Position last updated\s+"
            r"(\d{1,2}\s+"
            r"[A-Za-z]{3}\s+"
            r"\d{4},?\s+"
            r"\d{1,2}:\d{2}\s+UTC)",
            plain,
        )


    if not reported:
        raise RuntimeError(
            "Could not extract Voyage Radar timestamp"
        )


    reported_clean = (
        reported
        .replace(",", "")
        .strip()
    )


    reported_dt = datetime.strptime(
        reported_clean,
        "%d %b %Y %H:%M UTC",
    ).replace(
        tzinfo=timezone.utc
    )


    return {
        "lat": lat,
        "lng": lng,
        "time": (
            reported_dt.isoformat()
            .replace("+00:00", "Z")
        ),
        "reported": reported,
        "speed": speed,
        "course": course,
        "heading": heading,
        "waterBody": water_body,
    }


def parse_iso(value):

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
    except Exception:
        return None


def read_existing():

    if not OUTPUT.exists():
        return None

    try:
        with OUTPUT.open(
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except Exception:
        return None


def main():

    now = datetime.now(timezone.utc)

    # ==============================================
    # 1. Fetch VesselFinder
    # ==============================================

    vf_html = fetch(
        VESSELFINDER_URL
    )

    vf = parse_vesselfinder(
        vf_html
    )

    print(
        "VesselFinder status:",
        json.dumps(
            vf,
            indent=2,
        )
    )


    # ==============================================
    # 2. Decide whether VesselFinder gives us an
    #    authoritative port position
    # ==============================================

    lat = vf.get("lat")
    lng = vf.get("lng")

    time_value = None

    speed = None
    course = None
    heading = None
    water_body = None

    source_note = "VesselFinder"


    port_name = (
        vf.get("port") or ""
    ).lower()

    nav_status = (
        vf.get("navigation_status") or ""
    ).lower()


    # If VesselFinder explicitly says the vessel has
    # arrived / is moored at a known port, use the
    # port coordinates rather than an old offshore fix.

    if (
        port_name in KNOWN_PORTS
        and (
            "moor" in nav_status
            or vf.get("arrival_time")
        )
    ):

        lat = KNOWN_PORTS[
            port_name
        ]["lat"]

        lng = KNOWN_PORTS[
            port_name
        ]["lng"]

        time_value = (
            vf.get("arrival_time")
            or now.isoformat()
            .replace("+00:00", "Z")
        )

        speed = 0.0

        source_note = (
            "VesselFinder port status"
        )

        water_body = (
            vf.get("port")
        )

        print(
            f"VesselFinder confirms vessel "
            f"at {vf.get('port')}."
        )


    # ==============================================
    # 3. If no usable coordinates from VesselFinder,
    #    try Voyage Radar.
    # ==============================================

    if lat is None or lng is None:

        print(
            "VesselFinder did not expose coordinates."
        )

        print(
            "Checking Voyage Radar as coordinate fallback."
        )

        vr_html = fetch(
            VOYAGE_RADAR_URL
        )

        vr = parse_voyage_radar(
            vr_html
        )

        vr_time = parse_iso(
            vr.get("time")
        )

        age = (
            now - vr_time
            if vr_time
            else None
        )

        print(
            "Voyage Radar fix age:",
            age,
        )


        # If Voyage Radar position is fresh enough,
        # use it.

        if (
            age is not None
            and age <= timedelta(hours=6)
        ):

            lat = vr["lat"]
            lng = vr["lng"]

            time_value = vr["time"]

            speed = vr["speed"]
            course = vr["course"]
            heading = vr["heading"]
            water_body = vr["waterBody"]

            source_note = (
                "Voyage Radar"
            )


        else:

            # --------------------------------------
            # Voyage Radar is stale.
            #
            # If VesselFinder says the ship is at a
            # known port, use that port instead.
            # Otherwise fail rather than publishing
            # an old position as current.
            # --------------------------------------

            if (
                port_name in KNOWN_PORTS
                and vf.get("arrival_time")
            ):

                lat = KNOWN_PORTS[
                    port_name
                ]["lat"]

                lng = KNOWN_PORTS[
                    port_name
                ]["lng"]

                time_value = (
                    vf.get("arrival_time")
                )

                speed = 0.0

                water_body = (
                    vf.get("port")
                )

                source_note = (
                    "VesselFinder confirmed port position"
                )

            else:

                raise RuntimeError(
                    "No fresh AIS coordinates available. "
                    "Voyage Radar fallback is stale."
                )


    # ==============================================
    # 4. Final JSON
    # ==============================================

    if not time_value:

        time_value = (
            vf.get("arrival_time")
            or now.isoformat()
            .replace("+00:00", "Z")
        )


    new_data = {

        "vessel": VESSEL,

        "imo": IMO,
        "mmsi": MMSI,

        "lat": float(lat),
        "lng": float(lng),

        "time": time_value,

        "reported": (
            vf.get("arrival_time")
            or time_value
        ),

        "speed": speed,
        "course": course,
        "heading": heading,

        "waterBody": water_body,

        "navigation_status":
            vf.get("navigation_status"),

        "port":
            vf.get("port"),

        "position_age":
            vf.get("position_age_text"),

        "source":
            source_note,

        "source_url":
            VESSELFINDER_URL,

        "checked_at":
            now.isoformat()
            .replace("+00:00", "Z"),
    }


    # ==============================================
    # 5. Don't replace a newer real fix with an
    #    older one.
    # ==============================================

    existing = read_existing()

    if existing:

        existing_time = parse_iso(
            existing.get("time")
        )

        new_time = parse_iso(
            new_data.get("time")
        )


        if (
            existing_time
            and new_time
            and new_time < existing_time
        ):

            print(
                "New data timestamp is older "
                "than existing ais.json."
            )

            print(
                "Existing:",
                existing_time,
            )

            print(
                "New:",
                new_time,
            )

            print(
                "Keeping existing ais.json"
            )

            return


    # ==============================================
    # 6. Write output
    # ==============================================

    with OUTPUT.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            new_data,
            f,
            indent=2,
            ensure_ascii=False,
        )

        f.write("\n")


    print(
        json.dumps(
            new_data,
            indent=2,
        )
    )


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print(
            f"AIS update failed: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)
