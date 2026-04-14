# Carpool AI

Carpool AI is a local Python prototype that reads WhatsApp Web group messages, extracts carpool offers/requests, and recommends the best matching rides based on pickup, dropoff, time window, and ride intent.

This project uses only free/open-source tooling and runs entirely on your machine.

## Highlights

- WhatsApp Web scraping with Selenium
- Manual QR login with persistent browser profile (no repeated login every run)
- SQLite storage for messages and parsed carpool records
- Rule-based parser for noisy text and structured templates
- Ride type support:
	- `available` = driver has seats
	- `required` = rider needs a carpool
- Text/time-based matching (no kilometer-distance scoring)
- Multi-option pickup/drop preferences in one input
- Candidate limit for speed (latest 50 posts)

## Tech Stack

- Python 3.10+
- Flask (web app)
- Selenium (WhatsApp Web automation)
- SQLite (local database)
- Regex + keyword NLP (parser)

## Project Structure

```
carpool_ai/
|
|-- app.py
|-- scraper/
|   `-- whatsapp_scraper.py
|-- parser/
|   `-- message_parser.py
|-- matcher/
|   `-- carpool_matcher.py
|-- database/
|   `-- db.py
|-- templates/
|   |-- index.html
|   `-- results.html
|-- static/
|   `-- styles.css
|-- requirements.txt
`-- README.md
```

## Installation

1. Open terminal in project folder.
2. (Recommended) create virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open:

`http://127.0.0.1:5000`

## Usage Flow

1. On dashboard, set:
	 - WhatsApp group name
	 - Pickup options (single or multiple)
	 - Drop options (single or multiple)
	 - Time window
	 - Intent:
		 - `Looking for carpool` (matches ride type `available`)
		 - `Looking for passengers` (matches ride type `required`)
		 - `Show all ride types`
2. Click **Start scraper**.
3. Chrome opens WhatsApp Web.
4. Login via QR (first time), then keep target group chat open.
5. Scraper stores new messages continuously.
6. Open **Results** to see best matches.

## Input Format Support

The parser supports both free-text and template-style posts.

Example template:

```
Ride: Available
To: P-11A
From: Clifton Teen Talwar
Via: Shahrah-e-Faisal
Time: 8:30 PM
Seats: 2
```

Notes:

- If a user sends `Ride: Available/Required` unchanged, ride type is treated as unknown.
- Best results are achieved when users choose one type explicitly.

## Matching Logic (Current)

Matching is intentionally route-first and fast.

- Candidate pool: latest 50 parsed carpool posts
- Pickup/drop match: text similarity using normalized strings, token overlap, and fuzzy similarity
- Time fit: lower penalty when message time is inside or near the preferred window
- Ride intent filter:
	- looking for carpool -> available
	- looking for passengers -> required

Fallback behavior:

- If strict route filtering returns nothing, matcher relaxes filters to avoid empty results.

## Multi-Option Preferences

You can provide multiple pickup/drop alternatives in one field.

Supported separators:

- comma `,`
- semicolon `;`
- pipe `|`
- newline
- slash `/`
- word `or`

Example:

`Clifton, Ayesha Manzil, Sohrab Goth`

## Database Overview

### messages

- id
- sender
- message_text
- timestamp

### carpools

- id
- sender
- ride_type
- pickup_location
- dropoff_location
- time
- seats
- raw_message_id

Duplicate raw messages are ignored using a unique constraint on `(sender, message_text, timestamp)`.

## Troubleshooting

### App does not start

- Ensure dependencies are installed in the same Python environment:

```bash
python -m pip show Flask selenium webdriver-manager
```

### WhatsApp window does not open

- Make sure Chrome is installed and not blocked by policy.
- Close all old Python sessions, then run app again.
- Click Start scraper once and wait 15-30 seconds.

### Repeated QR login

- Browser profile is persisted under `.selenium_whatsapp_profile`.
- Do not delete this folder if you want to keep session.

### Best matches empty but available carpools visible

- Save preferences again on dashboard.
- Use hard refresh (`Ctrl+Shift+R`) on results page.
- Ensure pickup/drop options are not too restrictive.
- Try intent = `Show all ride types` to verify filtering.

### Slower performance

- Keep candidate limit small (currently 50).
- Avoid opening too many chats/tabs in the Selenium browser.

## Current Limitations

- WhatsApp Web DOM can change and may require selector updates.
- Parser is rule-based; very unusual phrasing may parse partially.
- Unknown ride types are still stored, but intent filters may skip them depending on preference.

## Future Improvements

- Dedicated background geocode queue (optional)
- Better transliteration/abbreviation normalization for local place names
- Admin tools to edit/correct parsed records from UI
- Unit tests for parser and matcher modules
