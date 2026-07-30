# V13 Withings integration

## What V13 adds

### Body Composition & Nutrition
- Direct Withings muscle mass (kg)
- Direct Withings muscle mass %
- Visceral fat index
- Water %
- BMR
- Selectable trends for muscle mass, visceral fat, hydration, BMR,
  vascular age, pulse-wave velocity, nerve-health score and metabolic age
- Additional metric table
- Future-ready fields for intracellular/extracellular water

### Recovery & Data Quality
- Withings blood pressure:
  - systolic
  - diastolic
  - pulse when recorded in the same BPM measurement
  - latest date
  - BP trend chart

## Two data modes

### 1. Local direct mode — works immediately
The dashboard uses:
`private/withings_token.json`

When the access token expires, it refreshes it automatically and writes the
rotated refresh token back to the local token file.

This is appropriate for local testing.

### 2. Persistent database mode — recommended for Streamlit Cloud
Set:
`WITHINGS_DATABASE_URL`

The dashboard then reads Withings measurements only from the database.
It does not perform OAuth token refresh itself.

The separate `withings_sync_service.py` owns the OAuth state, stores every
rotated refresh token in the database, and syncs measurements.

This solves the Streamlit Cloud persistence problem.

## Persistent sync setup

Install the service dependencies:

`pip install -r withings_sync_service_requirements.txt`

Set `WITHINGS_DATABASE_URL` to a persistent PostgreSQL database.

Run once:

`py .\withings_sync_service.py bootstrap`

Then perform the first historical sync:

`py .\withings_sync_service.py sync`

After this, add the same `WITHINGS_DATABASE_URL` to Streamlit Cloud secrets.

### Webhook deployment
Run the service on a small always-on HTTPS host:

`uvicorn withings_sync_service:app --host 0.0.0.0 --port 8000`

Set `WITHINGS_WEBHOOK_SECRET` on that host.

Your public callback URL should be:

`https://YOUR-SERVICE/withings?token=YOUR_SECRET`

Then subscribe both Withings metric categories:

`py .\withings_sync_service.py subscribe "https://YOUR-SERVICE/withings?token=YOUR_SECRET"`

The service subscribes:
- appli 1: weight/body-composition metrics
- appli 4: blood pressure / heart rate

A scheduled `sync` run is still useful as a fallback because Withings recommends
using `lastupdate` to catch changes that a webhook might miss.

## Body Scan readiness
The database schema preserves:
- type 168 extracellular water
- type 169 intracellular water
- type 173 segmental fat-free mass
- type 174 segmental fat mass
- type 175 segmental muscle mass
- type 158/159 left/right nerve-health score
- type 196 Nerve Response Score
- type 229 electrochemical skin conductance

So a future Body Scan can be added without redesigning the sync layer.
