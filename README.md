# SoCal Traffic Scraper

Collects historical traffic data from sigalert.com for Southern California highways.

## Features

- Scrapes 6,308 traffic sensors every 5 minutes
- Tracks speeds, incidents, and congestion patterns
- Runs free on GitHub Actions + Cloudflare R2

## Quick Start (Local)

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install requests

# Run scraper
.venv/bin/python scraper.py

```

## Cloud Deployment (Free)

See [cloud/README.md](cloud/README.md) for GitHub Actions + Cloudflare R2 setup.

## Files

| File | Purpose |
|------|---------|
| `scraper.py` | Main data collector (5 min intervals) |
| `commute_scraper.py` | Adaptive scraper (2 min peak, 15 min off-peak) |
| `analyze.py` | General data analysis utilities |
| `cloud/` | Serverless deployment for GitHub Actions + R2 |

## Data Format

See [DATA_FORMAT.md](DATA_FORMAT.md) for API documentation.

## License

MIT
