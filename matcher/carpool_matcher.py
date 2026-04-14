from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
import re
from typing import Any

from database.db import DatabaseManager


@dataclass
class MatchResult:
    carpool: dict[str, Any]
    score: float
    pickup_match_score: float
    drop_match_score: float
    time_difference_minutes: float


class CarpoolMatcher:
    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def find_best_matches(
        self,
        pickup_location: str,
        dropoff_location: str,
        time_start: str,
        time_end: str,
        user_intent: str = "looking_for_carpool",
        limit: int = 3,
        candidate_limit: int = 50,
        w1: float = 1.0,
        w2: float = 1.0,
        w3: float = 0.4,
    ) -> list[dict[str, Any]]:
        carpools = self.database.get_recent_carpools(limit=candidate_limit)
        pickup_options = _split_location_options(pickup_location)
        dropoff_options = _split_location_options(dropoff_location)
        preferred_minutes = self._preferred_minutes(time_start, time_end)
        window_bounds = self._window_bounds(time_start, time_end)
        target_ride_type = _target_ride_type_for_intent(user_intent)

        ranked_matches = self._collect_matches(
            carpools=carpools,
            pickup_options=pickup_options,
            dropoff_options=dropoff_options,
            preferred_minutes=preferred_minutes,
            window_bounds=window_bounds,
            target_ride_type=target_ride_type,
            weights=(w1, w2, w3),
            strict_route_filter=True,
        )

        # Fallback pass: if strict filtering yields nothing, relax route filtering.
        if not ranked_matches:
            ranked_matches = self._collect_matches(
                carpools=carpools,
                pickup_options=pickup_options,
                dropoff_options=dropoff_options,
                preferred_minutes=preferred_minutes,
                window_bounds=window_bounds,
                target_ride_type=target_ride_type,
                weights=(w1, w2, w3),
                strict_route_filter=False,
            )

        # Last-resort fallback: relax ride-type filter only if still empty.
        if not ranked_matches and target_ride_type is not None:
            ranked_matches = self._collect_matches(
                carpools=carpools,
                pickup_options=pickup_options,
                dropoff_options=dropoff_options,
                preferred_minutes=preferred_minutes,
                window_bounds=window_bounds,
                target_ride_type=None,
                weights=(w1, w2, w3),
                strict_route_filter=False,
            )

        ranked_matches.sort(key=lambda item: item.score)
        return [self._serialize_match(match) for match in ranked_matches[:limit]]

    def _collect_matches(
        self,
        carpools: list[dict[str, Any]],
        pickup_options: list[str],
        dropoff_options: list[str],
        preferred_minutes: int | None,
        window_bounds: tuple[int | None, int | None],
        target_ride_type: str | None,
        weights: tuple[float, float, float],
        strict_route_filter: bool,
    ) -> list[MatchResult]:
        ranked_matches: list[MatchResult] = []
        for carpool in carpools:
            if target_ride_type is not None:
                ride_type = str(carpool.get("ride_type") or "").strip().lower()
                if ride_type and ride_type != target_ride_type:
                    continue

            match = self._score_carpool(
                carpool=carpool,
                pickup_options=pickup_options,
                dropoff_options=dropoff_options,
                preferred_minutes=preferred_minutes,
                window_bounds=window_bounds,
                weights=weights,
                strict_route_filter=strict_route_filter,
            )
            if match is not None:
                ranked_matches.append(match)

        return ranked_matches

    def _score_carpool(
        self,
        carpool: dict[str, Any],
        pickup_options: list[str],
        dropoff_options: list[str],
        preferred_minutes: int | None,
        window_bounds: tuple[int | None, int | None],
        weights: tuple[float, float, float],
        strict_route_filter: bool,
    ) -> MatchResult | None:
        pickup_text = str(carpool.get("pickup_location") or "")
        dropoff_text = str(carpool.get("dropoff_location") or "")

        pickup_cost = _location_match_cost(pickup_options, pickup_text)
        dropoff_cost = _location_match_cost(dropoff_options, dropoff_text)
        time_difference = self._time_difference_minutes(carpool.get("time"), preferred_minutes, window_bounds)

        route_cost = pickup_cost + dropoff_cost
        # Drop unrelated routes so exact/near-exact options surface first.
        if strict_route_filter and route_cost > 1.4:
            return None

        # Keep route as the dominant factor; time refines ranking among route matches.
        time_cost = time_difference / 30.0

        score = (
            (weights[0] * pickup_cost + weights[1] * dropoff_cost) * 100.0
            + weights[2] * time_cost
        )

        return MatchResult(
            carpool=carpool,
            score=score,
            pickup_match_score=1.0 - min(pickup_cost, 1.0),
            drop_match_score=1.0 - min(dropoff_cost, 1.0),
            time_difference_minutes=time_difference,
        )

    def _preferred_minutes(self, time_start: str, time_end: str) -> int | None:
        start_minutes = _parse_time_to_minutes(time_start)
        end_minutes = _parse_time_to_minutes(time_end)

        if start_minutes is None and end_minutes is None:
            return None
        if start_minutes is not None and end_minutes is not None:
            return (start_minutes + end_minutes) // 2
        return start_minutes if start_minutes is not None else end_minutes

    def _window_bounds(self, time_start: str, time_end: str) -> tuple[int | None, int | None]:
        return _parse_time_to_minutes(time_start), _parse_time_to_minutes(time_end)

    def _time_difference_minutes(
        self,
        carpool_time: Any,
        preferred_minutes: int | None,
        window_bounds: tuple[int | None, int | None],
    ) -> float:
        if preferred_minutes is None or carpool_time is None:
            return 0.0

        carpool_minutes = _parse_time_to_minutes(str(carpool_time))
        if carpool_minutes is None:
            return 60.0

        start, end = window_bounds
        if start is not None and end is not None:
            if start <= carpool_minutes <= end:
                return 0.0
            return float(min(abs(carpool_minutes - start), abs(carpool_minutes - end)))

        return abs(carpool_minutes - preferred_minutes)

    def _serialize_match(self, match: MatchResult) -> dict[str, Any]:
        return {
            **match.carpool,
            "score": round(match.score, 3),
            "pickup_match_percent": round(match.pickup_match_score * 100.0, 1),
            "drop_match_percent": round(match.drop_match_score * 100.0, 1),
            "time_difference_minutes": round(match.time_difference_minutes, 1),
        }


def _split_location_options(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []

    parts = [
        part.strip()
        for part in re.split(r"[,;|\n]+|\s*/\s*|\s+or\s+", raw_value, flags=re.IGNORECASE)
        if part.strip()
    ]
    if not parts:
        return []
    return parts


def _location_match_cost(options: list[str], carpool_location: str) -> float:
    if not options:
        return 0.0
    if not carpool_location:
        return 1.5

    location_norm = _normalize_location(carpool_location)
    if not location_norm:
        return 1.5

    best_cost = 2.0
    for option in options:
        option_norm = _normalize_location(option)
        if not option_norm:
            continue

        if option_norm == location_norm:
            return 0.0

        if option_norm in location_norm or location_norm in option_norm:
            best_cost = min(best_cost, 0.1)
            continue

        similarity = SequenceMatcher(None, option_norm, location_norm).ratio()

        option_tokens = set(option_norm.split())
        location_tokens = set(location_norm.split())
        token_overlap = (len(option_tokens & location_tokens) / len(option_tokens | location_tokens)) if (option_tokens | location_tokens) else 0.0

        combined_similarity = max(similarity, token_overlap)
        best_cost = min(best_cost, 1.0 - combined_similarity)

    if best_cost == 2.0:
        return 1.5
    return best_cost


def _normalize_location(value: str) -> str:
    cleaned = value.lower().strip()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Normalize common abbreviations for stronger matching.
    replacements = {
        "defence": "dha",
        "phase": "ph",
        "univ": "university",
        "uni": "university",
    }
    words = [replacements.get(word, word) for word in cleaned.split()]
    return " ".join(words)


def _parse_time_to_minutes(value: str | None) -> int | None:
    if not value:
        return None

    cleaned = value.strip().lower()
    if not cleaned:
        return None

    time_formats = ["%H:%M", "%I:%M %p", "%I %p", "%H"]
    from datetime import datetime

    for time_format in time_formats:
        try:
            parsed = datetime.strptime(cleaned, time_format)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue

    return None


def _target_ride_type_for_intent(user_intent: str | None) -> str | None:
    normalized = (user_intent or "").strip().lower()
    if normalized == "looking_for_carpool":
        return "available"
    if normalized == "looking_for_passengers":
        return "required"
    return None
