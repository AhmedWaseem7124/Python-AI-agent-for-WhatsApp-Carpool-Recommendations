# Carpool AI

Local prototype that scrapes a WhatsApp Web carpool group, stores raw messages in SQLite, parses carpool details with rules and regex, geocodes locations with OpenStreetMap/Nominatim, and ranks the best matches in a Flask dashboard.

## Requirements

- Python 3.10 or newer
- Google Chrome installed locally
- Internet access for WhatsApp Web and OpenStreetMap geocoding

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
python app.py
```

4. Open `http://127.0.0.1:5000` in your browser.

## How It Works

- Enter your pickup location, drop location, and preferred time window in the dashboard.
- Set the WhatsApp group name in the same form.
- Click `Start scraper` to launch Selenium and log in to WhatsApp Web manually with the QR code.
- The scraper keeps polling the active group and stores new messages in SQLite.
- Open `Results` to rank the top 3 carpools.

## Notes

- The scraper uses WhatsApp Web, so the DOM selectors may need updates if WhatsApp changes its layout.
- Location matching is free and uses Nominatim through `geopy`.
- Duplicate messages are ignored by the SQLite unique constraint.