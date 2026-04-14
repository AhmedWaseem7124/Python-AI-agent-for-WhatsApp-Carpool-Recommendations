from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


KNOWN_LOCATIONS = [
    "dha",
    "defence",
    "clifton",
    "iba",
    "gulshan",
    "pechs",
    "bahadurabad",
    "saddar",
    "korangi",
    "johar",
    "north nazimabad",
    "malir",
    "bahria town",
    "shahrah-e-faisal",
    "airport",
    "airport road",
    "university road",
]

LOCATION_DISPLAY_OVERRIDES = {
    "dha": "DHA",
    "iba": "IBA",
    "pechs": "PECHS",
}


@dataclass
class ParsedCarpool:
    sender: str
    ride_type: str | None
    pickup_location: str | None
    dropoff_location: str | None
    time_text: str | None
    time_minutes: int | None
    seats: int | None


def parse_carpool_message(sender: str, message_text: str) -> ParsedCarpool:
    template_data = _extract_template_fields(message_text)
    cleaned = _normalize(message_text)

    ride_type = template_data.get("ride_type") or _extract_ride_type(cleaned)

    pickup_location, dropoff_location = _extract_route(cleaned)
    if template_data["pickup_location"]:
        pickup_location = template_data["pickup_location"]
    if template_data["dropoff_location"]:
        dropoff_location = template_data["dropoff_location"]

    time_text, time_minutes = _extract_time(cleaned)
    if template_data["time_text"]:
        time_text, time_minutes = _extract_time(template_data["time_text"])
        if not time_text:
            time_text = template_data["time_text"]

    seats = _extract_seats(cleaned)
    if template_data["seats"] is not None:
        seats = template_data["seats"]

    return ParsedCarpool(
        sender=sender,
        ride_type=ride_type,
        pickup_location=pickup_location,
        dropoff_location=dropoff_location,
        time_text=time_text,
        time_minutes=time_minutes,
        seats=seats,
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _extract_seats(text: str) -> int | None:
    seat_match = re.search(r"\b(\d+)\s*(?:seats?|seat|pax|passengers?|people|persons?)\b", text, re.IGNORECASE)
    if seat_match:
        return int(seat_match.group(1))

    # Handle compact template values like "Seats: 2".
    direct_number_match = re.search(r"\bseats?\s*[:\-]?\s*(\d+)\b", text, re.IGNORECASE)
    if direct_number_match:
        return int(direct_number_match.group(1))

    word_match = re.search(
        r"\bseats?\s*[:\-]?\s*(one|two|three|four|five|six|seven|eight|nine|ten)\b",
        text,
        re.IGNORECASE,
    )
    if word_match:
        word_to_number = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        return word_to_number[word_match.group(1).lower()]

    return None


def _extract_template_fields(text: str) -> dict[str, object]:
    fields = {
        "ride_type": None,
        "pickup_location": None,
        "dropoff_location": None,
        "time_text": None,
        "seats": None,
    }

    ride_value = _extract_labeled_value(text, ["ride", "type"])
    to_value = _extract_labeled_value(text, ["to"])
    from_value = _extract_labeled_value(text, ["from"])
    time_value = _extract_labeled_value(text, ["time"])
    seats_value = _extract_labeled_value(text, ["seats"])

    if ride_value:
        fields["ride_type"] = _extract_ride_type(ride_value)
    if from_value:
        fields["pickup_location"] = _clean_location(from_value)
    if to_value:
        fields["dropoff_location"] = _clean_location(to_value)
    if time_value:
        fields["time_text"] = time_value.strip()
    if seats_value:
        fields["seats"] = _extract_seat_count_from_value(seats_value)

    return fields


def _extract_ride_type(text: str | None) -> str | None:
    if not text:
        return None

    lowered = text.lower()
    simplified = re.sub(r"[^a-z0-9/\s]", " ", lowered)
    simplified = re.sub(r"\s+", " ", simplified).strip()

    available_keywords = [
        "available",
        "seats available",
        "have seats",
        "offering ride",
        "looking for passengers",
        "passengers needed",
    ]
    required_keywords = [
        "required",
        "need ride",
        "looking for carpool",
        "need a ride",
        "looking for lift",
        "ride needed",
    ]

    has_available = any(keyword in simplified for keyword in available_keywords)
    has_required = any(keyword in simplified for keyword in required_keywords)

    # If both appear (for example, "Available/Required" template placeholder),
    # do not force a wrong type.
    if has_available and has_required:
        return None

    if has_available:
        return "available"
    if has_required:
        return "required"
    return None


def _extract_labeled_value(text: str, labels: list[str]) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        normalized_line = _strip_non_alnum_prefix(line).lower()
        for label in labels:
            if normalized_line.startswith(f"{label}:"):
                raw_value = line.split(":", 1)[1].strip()
                return raw_value if raw_value else None
    return None


def _strip_non_alnum_prefix(value: str) -> str:
    return re.sub(r"^[^A-Za-z0-9]+", "", value)


def _extract_seat_count_from_value(value: str) -> int | None:
    digit_match = re.search(r"\b(\d+)\b", value)
    if digit_match:
        return int(digit_match.group(1))

    word_to_number = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    word_match = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", value, re.IGNORECASE)
    if word_match:
        return word_to_number[word_match.group(1).lower()]

    return None


def _extract_time(text: str) -> tuple[str | None, int | None]:
    explicit_match = re.search(
        r"\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)\b",
        text,
        re.IGNORECASE,
    )
    if explicit_match:
        return _format_time_match(explicit_match)

    fuzzy_match = re.search(r"\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*ish\b", text, re.IGNORECASE)
    if fuzzy_match:
        hour = int(fuzzy_match.group("hour"))
        minute = int(fuzzy_match.group("minute") or 0)
        ampm = _infer_ampm_from_context(text, hour)
        time_minutes = _to_minutes(hour, minute, ampm)
        return f"{hour}:{minute:02d} {ampm.upper()}", time_minutes

    twenty_four_hour_match = re.search(r"\b(?P<hour>\d{1,2}):(?P<minute>\d{2})\b", text)
    if twenty_four_hour_match:
        hour = int(twenty_four_hour_match.group("hour"))
        minute = int(twenty_four_hour_match.group("minute"))
        if hour < 24 and minute < 60:
            ampm = "am" if hour < 12 else "pm"
            display_hour = hour % 12 or 12
            return f"{display_hour}:{minute:02d} {ampm.upper()}", hour * 60 + minute

    return None, None


def _format_time_match(match: re.Match[str]) -> tuple[str, int]:
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = match.group("ampm").lower()
    return f"{hour}:{minute:02d} {ampm.upper()}", _to_minutes(hour, minute, ampm)


def _infer_ampm_from_context(text: str, hour: int) -> str:
    lower_text = text.lower()
    if any(keyword in lower_text for keyword in ["evening", "night", "pm", "after office", "after work"]):
        return "pm"
    if any(keyword in lower_text for keyword in ["morning", "am", "breakfast"]):
        return "am"
    if 1 <= hour <= 4:
        return "am"
    return "pm" if 5 <= hour <= 11 else "am"


def _to_minutes(hour: int, minute: int, ampm: str) -> int:
    normalized_hour = hour % 12
    if ampm.lower() == "pm":
        normalized_hour += 12
    return normalized_hour * 60 + minute


def _extract_route(text: str) -> tuple[str | None, str | None]:
    patterns = [
        r"\bfrom\s+(?P<pickup>.+?)\s+(?:to|->|towards|for)\s+(?P<dropoff>.+?)(?=$|[,.;]|\bwith\b|\bleaving\b|\bat\b|\baround\b)",
        r"\b(?P<pickup>[A-Za-z0-9&\-/ ]+?)\s+(?:to|->|towards|for)\s+(?P<dropoff>[A-Za-z0-9&\-/ ]+?)(?=$|[,.;]|\bwith\b|\bleaving\b|\bat\b|\baround\b)",
        r"\bpickup\s+from\s+(?P<pickup>.+?)(?:\s+(?:to|->|towards|for)\s+(?P<dropoff>.+?))?(?=$|[,.;]|\bwith\b|\bleaving\b|\bat\b|\baround\b)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            pickup = _clean_location(match.groupdict().get("pickup"))
            dropoff = _clean_location(match.groupdict().get("dropoff"))
            if pickup or dropoff:
                return pickup, dropoff

    detected_locations = _detect_known_locations(text)
    if len(detected_locations) >= 2:
        return detected_locations[0], detected_locations[1]
    if len(detected_locations) == 1:
        return detected_locations[0], None

    return None, None


def _detect_known_locations(text: str) -> list[str]:
    lower_text = text.lower()
    matches: list[tuple[int, str]] = []

    for location in sorted(KNOWN_LOCATIONS, key=len, reverse=True):
        index = lower_text.find(location)
        if index != -1:
            matches.append((index, _title_case_location(location)))

    ordered = [location for _, location in sorted(matches, key=lambda item: item[0])]
    seen: set[str] = set()
    unique_locations: list[str] = []
    for location in ordered:
        key = location.lower()
        if key not in seen:
            seen.add(key)
            unique_locations.append(location)
    return unique_locations


def _clean_location(raw_value: Optional[str]) -> str | None:
    if not raw_value:
        return None

    text = raw_value.strip(" ,.-")
    text = re.sub(r"\b(around|approx|approximately|leaving|leaves|at|by|with|need|need a ride|ride|carpool)\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|ish)?)\b.*$", "", text, flags=re.IGNORECASE)
    text = text.strip(" ,.-")
    if not text:
        return None
    return _title_case_location(text)


def _title_case_location(value: str) -> str:
    lowered = value.strip()
    if lowered.lower() in LOCATION_DISPLAY_OVERRIDES:
        return LOCATION_DISPLAY_OVERRIDES[lowered.lower()]
    if lowered.lower() in {location.lower() for location in KNOWN_LOCATIONS}:
        for location in KNOWN_LOCATIONS:
            if lowered.lower() == location.lower():
                return location.title() if location.islower() else location
    return " ".join(part.capitalize() if part else part for part in lowered.split())
