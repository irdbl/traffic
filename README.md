# SoCal Traffic Scraper

Collects historical traffic data from sigalert.com for Southern California highways. Designed for commute analysis between Culver City and Port of Long Beach.

## Features

- Scrapes 6,308 traffic sensors every 5 minutes
- Tracks speeds, incidents, and congestion patterns
- Analyzes optimal departure times for your commute
- Runs free on GitHub Actions + Cloudflare R2

## Quick Start (Local)

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install requests

# Run scraper
.venv/bin/python scraper.py

# Check commute conditions
.venv/bin/python commute.py
```

## Cloud Deployment (Free)

See [cloud/README.md](cloud/README.md) for GitHub Actions + Cloudflare R2 setup.

## Commute Routes Analyzed

**Culver City → Port of Long Beach (Morning)**
- 405 S → 710 S (direct)
- 405 S → 105 E → 710 S (avoids interchange)
- 10 E → 110 S → 710 S (downtown route)

**Port of Long Beach → Culver City (Evening)**
- Same routes in reverse

## Files

| File | Purpose |
|------|---------|
| `scraper.py` | Main data collector (5 min intervals) |
| `commute_scraper.py` | Adaptive scraper (2 min peak, 15 min off-peak) |
| `commute.py` | Commute time analysis and recommendations |
| `analyze.py` | General data analysis utilities |
| `cloud/` | Serverless deployment for GitHub Actions + R2 |

## Data Format

See [DATA_FORMAT.md](DATA_FORMAT.md) for API documentation.

## License

MIT
