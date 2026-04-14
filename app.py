import logging
import os

from flask import Flask, flash, redirect, render_template, request, session, url_for

from database.db import DatabaseManager

_matcher_import_error = None
_scraper_import_error = None

try:
    from matcher.carpool_matcher import CarpoolMatcher
except ModuleNotFoundError as exc:
    CarpoolMatcher = None
    _matcher_import_error = str(exc)

try:
    from scraper.whatsapp_scraper import ScrapingManager
except ModuleNotFoundError as exc:
    ScrapingManager = None
    _scraper_import_error = str(exc)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "carpool-ai-dev-secret")

database = DatabaseManager()


class _FallbackScrapingManager:
    is_running = False

    def start(self, group_name: str) -> bool:
        return False

    def status_snapshot(self) -> dict:
        return {
            "is_running": False,
            "last_error": "Selenium runtime is not loaded.",
            "last_group_name": None,
            "last_started_at": None,
        }


class _FallbackMatcher:
    def find_best_matches(self, **kwargs):
        return []


matcher = CarpoolMatcher(database) if CarpoolMatcher else _FallbackMatcher()
scraping_manager = ScrapingManager(database) if ScrapingManager else _FallbackScrapingManager()


def _ensure_runtime_components() -> tuple[bool, str | None]:
    """Try to lazily load optional modules so restarts are not required after installs."""

    global CarpoolMatcher, ScrapingManager
    global matcher, scraping_manager
    global _matcher_import_error, _scraper_import_error

    if CarpoolMatcher is None:
        try:
            from matcher.carpool_matcher import CarpoolMatcher as ImportedMatcher

            CarpoolMatcher = ImportedMatcher
            matcher = CarpoolMatcher(database)
            _matcher_import_error = None
        except ModuleNotFoundError as exc:
            _matcher_import_error = str(exc)

    if ScrapingManager is None:
        try:
            from scraper.whatsapp_scraper import ScrapingManager as ImportedScrapingManager

            ScrapingManager = ImportedScrapingManager
            scraping_manager = ScrapingManager(database)
            _scraper_import_error = None
        except ModuleNotFoundError as exc:
            _scraper_import_error = str(exc)

    if ScrapingManager is None:
        return False, _scraper_import_error
    return True, None


def _get_preferences() -> dict:
    """Read the current dashboard settings from the session."""

    if "user_intent" not in session:
        session["user_intent"] = "looking_for_carpool"

    return {
        "pickup_location": session.get("pickup_location", ""),
        "dropoff_location": session.get("dropoff_location", ""),
        "time_start": session.get("time_start", ""),
        "time_end": session.get("time_end", ""),
        "user_intent": session.get("user_intent", "looking_for_carpool"),
        "group_name": session.get("group_name", os.environ.get("WHATSAPP_GROUP_NAME", "Carpool Group")),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        session["pickup_location"] = request.form.get("pickup_location", "").strip()
        session["dropoff_location"] = request.form.get("dropoff_location", "").strip()
        session["time_start"] = request.form.get("time_start", "").strip()
        session["time_end"] = request.form.get("time_end", "").strip()
        session["user_intent"] = request.form.get("user_intent", "looking_for_carpool").strip() or "looking_for_carpool"
        session["group_name"] = request.form.get("group_name", "").strip() or os.environ.get(
            "WHATSAPP_GROUP_NAME", "Carpool Group"
        )
        flash("Preferences saved.", "success")
        return redirect(url_for("index"))

    preferences = _get_preferences()
    carpools = database.get_recent_carpools(limit=50)
    return render_template(
        "index.html",
        preferences=preferences,
        carpools=carpools,
        scraper_running=scraping_manager.is_running,
        scraper_status=scraping_manager.status_snapshot(),
    )


@app.route("/scrape", methods=["POST"])
def scrape():
    preferences = _get_preferences()
    group_name = request.form.get("group_name", "").strip() or preferences["group_name"]

    components_ready, error_message = _ensure_runtime_components()
    if not components_ready:
        details = f" ({error_message})" if error_message else ""
        flash(f"Selenium runtime is unavailable. Install dependencies and restart if needed{details}", "info")
        return redirect(url_for("index"))

    started = scraping_manager.start(group_name=group_name)

    if started:
        flash(f"Scraper started for group: {group_name}. If browser takes time, wait 15-30 seconds.", "success")
    else:
        status = scraping_manager.status_snapshot()
        if status.get("last_error"):
            flash(f"Scraper failed: {status.get('last_error')}", "info")
        else:
            flash("Scraper is already running.", "info")

    return redirect(url_for("index"))


@app.route("/results", methods=["GET"])
def results():
    preferences = _get_preferences()
    _ensure_runtime_components()
    if CarpoolMatcher is None:
        details = f" ({_matcher_import_error})" if _matcher_import_error else ""
        flash(f"Matcher runtime is unavailable. Install dependencies to compute ranked matches{details}", "info")
        return render_template(
            "results.html",
            preferences=preferences,
            matches=[],
            carpools=database.get_recent_carpools(limit=50),
        )

    matches = matcher.find_best_matches(
        pickup_location=preferences["pickup_location"],
        dropoff_location=preferences["dropoff_location"],
        time_start=preferences["time_start"],
        time_end=preferences["time_end"],
        user_intent=preferences["user_intent"],
        limit=10,
        candidate_limit=50,
    )
    carpools = database.get_recent_carpools(limit=50)

    return render_template(
        "results.html",
        preferences=preferences,
        matches=matches,
        match_count=len(matches),
        carpools=carpools,
    )


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)