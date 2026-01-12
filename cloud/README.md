# Cloud Deployment (Free Tier)

## Architecture

```
GitHub Actions (cron every 5 min)
        │
        ▼
  scraper_lambda.py
        │
        ▼
  Cloudflare R2 (storage)
        │
        ▼
  download_data.py → local SQLite → commute.py
```

**Cost: $0** (within free tiers)

## Setup

### 1. Create Cloudflare R2 Bucket

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → R2
2. Create bucket named `traffic-data`
3. Go to R2 → Manage R2 API Tokens → Create API Token
4. Save: Account ID, Access Key ID, Secret Access Key

### 2. Configure GitHub Secrets

In your repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `R2_ACCOUNT_ID` | Your Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret |
| `R2_BUCKET_NAME` | `traffic-data` |

### 3. Push to GitHub

```bash
cd /Users/k/git/traffic
git init
git add .
git commit -m "Traffic scraper"
git remote add origin https://github.com/YOU/traffic.git
git push -u origin main
```

The scraper will start running automatically on schedule.

### 4. Download Data for Analysis

```bash
# Set up local env vars (or use .env file)
export R2_ACCOUNT_ID="your-account-id"
export R2_ACCESS_KEY_ID="your-key"
export R2_SECRET_ACCESS_KEY="your-secret"
export R2_BUCKET_NAME="traffic-data"

# Download last 7 days
.venv/bin/pip install boto3
.venv/bin/python cloud/download_data.py --days 7

# Run commute analysis
.venv/bin/python commute.py
```

## Free Tier Limits

| Service | Limit | Our Usage |
|---------|-------|-----------|
| GitHub Actions | 2000 min/month (private) | ~600 min/month (5 min × 180 runs/day × 0.5 min each) |
| Cloudflare R2 | 10 GB storage | ~1.5 GB/month |
| Cloudflare R2 | 10M Class B ops | ~5k/month |

## Data Format

Each scrape creates a compact JSON file:

```
r2://traffic-data/data/2026-01-15/14/3000.json
                       └─ date    └─ hour └─ MMSS
```

```json
{
  "t": "2026-01-15T14:30:00Z",
  "s": [[65, []], [45, [[1, 12345]]], ...],  // [speed, incidents] × 6308
  "i": [[12345, "I-405 at Culver", "crash", "2026-01-15T14:20:00"], ...]
}
```

## Alternative: Run Locally Only

If you don't want cloud storage, just run locally:

```bash
# Start scraper (runs continuously)
.venv/bin/python scraper.py

# Or use launchd (macOS)
cp com.traffic.commute-scraper.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.traffic.commute-scraper.plist
```
