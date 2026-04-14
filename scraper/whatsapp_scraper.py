from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver import ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from database.db import DatabaseManager
from parser.message_parser import parse_carpool_message


logger = logging.getLogger(__name__)


class WhatsAppScraper:
    """Automates WhatsApp Web and persists newly discovered carpool messages."""

    def __init__(self, database: DatabaseManager, poll_interval_seconds: int = 20) -> None:
        self.database = database
        self.poll_interval_seconds = poll_interval_seconds

    def build_driver(self) -> webdriver.Chrome:
        options = ChromeOptions()
        profile_path = (Path(__file__).resolve().parent.parent / ".selenium_whatsapp_profile").resolve()
        profile_path.mkdir(parents=True, exist_ok=True)

        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--remote-debugging-port=0")
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--profile-directory=Default")
        options.page_load_strategy = "eager"
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Let Selenium Manager resolve a ChromeDriver matching installed Chrome.
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                driver = webdriver.Chrome(options=options)
                driver.set_page_load_timeout(120)
                return driver
            except Exception as exc:
                last_error = exc
                logger.warning("Chrome startup attempt %s failed: %s", attempt, exc)
                time.sleep(2)

        raise RuntimeError(f"Could not start Chrome WebDriver after retries: {last_error}")

    def run(self, group_name: str, stop_event: threading.Event) -> None:
        driver = None
        stage = "initializing driver"
        try:
            driver = self.build_driver()
            stage = "waiting for WhatsApp login"
            self._open_whatsapp_web(driver)
            stage = "opening target group chat"
            opened_group = self._open_group_chat(driver, group_name)
            if not opened_group:
                logger.warning(
                    "Could not auto-open group '%s'. Continuing with currently open chat.",
                    group_name,
                )

            while not stop_event.is_set():
                processed_count = self.scrape_visible_messages(driver)
                logger.info("Scraper cycle complete. New messages processed: %s", processed_count)
                stop_event.wait(self.poll_interval_seconds)
        except TimeoutException as exc:
            logger.exception("WhatsApp Web scraper timed out during stage: %s", stage)
            raise RuntimeError(
                f"Timeout during {stage}. Keep WhatsApp Web open and manually open the target group once, then retry."
            ) from exc
        except WebDriverException as exc:
            logger.exception("WhatsApp Web scraper failed.")
            raise RuntimeError(f"WebDriver error ({exc.__class__.__name__}): {exc}") from exc
        except Exception as exc:
            logger.exception("Unexpected scraper error.")
            raise RuntimeError(f"Unexpected scraper error: {exc}") from exc
        finally:
            if driver is not None:
                driver.quit()

    def scrape_visible_messages(self, driver: webdriver.Chrome) -> int:
        message_nodes = driver.find_elements(By.CSS_SELECTOR, "div.copyable-text[data-pre-plain-text]")
        new_messages = 0
        if not message_nodes:
            logger.info("No visible message nodes found in the current chat yet.")

        for node in message_nodes:
            try:
                pre_plain_text = node.get_attribute("data-pre-plain-text") or ""
                message_text = node.text.strip()
                sender, timestamp = _parse_pre_plain_text(pre_plain_text)
                if not timestamp or not message_text:
                    continue

                if not sender:
                    sender = "Unknown"

                message_id, inserted = self.database.insert_message(sender, message_text, timestamp)
                if not inserted:
                    continue

                parsed = parse_carpool_message(sender=sender, message_text=message_text)
                if not _has_useful_fields(parsed):
                    continue

                self.database.insert_carpool(
                    sender=parsed.sender,
                    ride_type=parsed.ride_type,
                    pickup_location=parsed.pickup_location,
                    dropoff_location=parsed.dropoff_location,
                    time_text=parsed.time_text,
                    seats=parsed.seats,
                    raw_message_id=message_id,
                )
                new_messages += 1
            except Exception:
                logger.exception("Failed to process one WhatsApp message node.")

        return new_messages

    def _open_whatsapp_web(self, driver: webdriver.Chrome) -> None:
        try:
            driver.get("https://web.whatsapp.com")
        except TimeoutException:
            # Continue if top-level page load takes too long; WhatsApp UI may still be usable.
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
        logger.info("Waiting for WhatsApp Web login. Scan the QR code if prompted.")
        login_ready_selectors = [
            (By.ID, "pane-side"),
            (By.XPATH, "//div[@id='side']//div[@role='textbox' and @contenteditable='true']"),
            (By.XPATH, "//div[@aria-label='Search input textbox' and @contenteditable='true']"),
        ]

        WebDriverWait(driver, 300).until(
            EC.any_of(*[EC.presence_of_element_located(selector) for selector in login_ready_selectors])
        )
        logger.info("WhatsApp Web appears logged in and ready.")

    def _open_group_chat(self, driver: webdriver.Chrome, group_name: str) -> bool:
        try:
            search_box = self._find_search_box(driver)
            search_box.click()
            search_box.send_keys(Keys.CONTROL, "a")
            search_box.send_keys(group_name)
            time.sleep(2)

            possible_matches = driver.find_elements(By.XPATH, f"//span[@title={_xpath_literal(group_name)}]")
            if possible_matches:
                possible_matches[0].click()
                logger.info("Opened WhatsApp group: %s", group_name)
                return True

            search_box.send_keys(Keys.ENTER)
            logger.info("Tried enter fallback for group: %s", group_name)
            return True
        except TimeoutException:
            logger.warning("Timed out trying to locate the group search box.")
            return False

    def _find_search_box(self, driver: webdriver.Chrome):
        selectors = [
            (By.XPATH, "//div[@id='side']//div[@role='textbox' and @contenteditable='true']"),
            (By.XPATH, "//div[@aria-label='Search input textbox' and @contenteditable='true']"),
            (By.XPATH, "//div[@role='textbox' and @contenteditable='true']"),
            (By.XPATH, "//div[@id='side']//div[@contenteditable='true']"),
        ]
        for by, value in selectors:
            try:
                return WebDriverWait(driver, 45).until(EC.presence_of_element_located((by, value)))
            except TimeoutException:
                continue
        raise TimeoutException("Could not find the WhatsApp search box.")


class ScrapingManager:
    """Runs the WhatsApp scraper in a background daemon thread."""

    def __init__(self, database: DatabaseManager) -> None:
        self.database = database
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_group_name: str | None = None
        self._last_started_at: str | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, group_name: str) -> bool:
        with self._lock:
            if self.is_running:
                return False

            self._stop_event.clear()
            self._last_error = None
            self._last_group_name = group_name
            self._last_started_at = datetime.now().isoformat(timespec="seconds")
            self._thread = threading.Thread(
                target=self._run,
                args=(group_name,),
                daemon=True,
                name="WhatsAppScraperThread",
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self, group_name: str) -> None:
        scraper = WhatsAppScraper(self.database)
        try:
            scraper.run(group_name=group_name, stop_event=self._stop_event)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("Scraper background thread ended with an error.")

    def status_snapshot(self) -> dict[str, str | bool | None]:
        return {
            "is_running": self.is_running,
            "last_error": self._last_error,
            "last_group_name": self._last_group_name,
            "last_started_at": self._last_started_at,
        }


def _parse_pre_plain_text(value: str) -> tuple[str | None, str | None]:
    if not value:
        return None, None

    # WhatsApp can include directional marker characters around metadata.
    cleaned = value.replace("\u200e", "").replace("\u200f", "").strip()

    if "[" in cleaned and "]" in cleaned:
        start_index = cleaned.find("[")
        end_index = cleaned.find("]", start_index + 1)
        if end_index != -1:
            timestamp = cleaned[start_index + 1 : end_index].strip() or None
            remainder = cleaned[end_index + 1 :].strip()

            # Typical format: "Sender:". Keep a safe fallback for unexpected strings.
            sender_candidate = remainder[:-1].strip() if remainder.endswith(":") else remainder
            sender = sender_candidate or None
            return sender, timestamp

    match = re.search(r"\[(?P<timestamp>[^\]]+)\]", cleaned)
    if not match:
        return None, None

    timestamp = match.group("timestamp").strip() or None
    tail = cleaned[match.end() :].strip()
    sender = tail[:-1].strip() if tail.endswith(":") else (tail or None)
    return sender, timestamp


def _has_useful_fields(parsed) -> bool:
    return any(
        [
            parsed.pickup_location,
            parsed.dropoff_location,
            parsed.time_text,
            parsed.seats is not None,
        ]
    )


def _xpath_literal(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"

    pieces: list[str] = []
    parts = value.split('"')
    for index, part in enumerate(parts):
        if part:
            pieces.append(f'"{part}"')
        if index < len(parts) - 1:
            pieces.append("'\"'")

    return "concat(" + ", ".join(pieces) + ")"