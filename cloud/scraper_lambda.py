#!/usr/bin/env python3
"""
Serverless Traffic Scraper for GitHub Actions + Cloudflare R2

Fetches traffic data and uploads to R2 as timestamped JSON.
Designed to run as a GitHub Action on a cron schedule.

Environment variables:
  R2_ACCOUNT_ID: Cloudflare account ID
  R2_ACCESS_KEY_ID: R2 access key
  R2_SECRET_ACCESS_KEY: R2 secret key
  R2_BUCKET_NAME: R2 bucket name (default: traffic-data)
"""

import json
import os
import urllib.request
from datetime import datetime, timezone

# URLs
STATIC_URL = "https://cdn-static.sigalert.com/240/Zip/RegionInfo/SoCalStatic.json"
DATA_URL = "https://www.sigalert.com/Data/SoCal/4~j/SoCalData.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.sigalert.com/",
}


def fetch_json(url: str) -> dict:
    """Fetch JSON from URL."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upload_to_r2(data: bytes, key: str):
    """Upload data to Cloudflare R2 using boto3."""
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )

    bucket = os.environ.get("R2_BUCKET_NAME", "traffic-data")
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/json")
    print(f"Uploaded to r2://{bucket}/{key}")


def scrape_and_upload():
    """Main scrape function."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now.strftime("%Y-%m-%d")
    hour_str = now.strftime("%H")

    print(f"Scraping at {timestamp}...")

    # Fetch live data
    cb = int(now.timestamp() * 1000) % 100000000
    data = fetch_json(f"{DATA_URL}?cb={cb}")

    # Extract just speeds and incidents (cameras are large and rarely needed)
    compact_data = {
        "t": timestamp,
        "s": [[s[0], s[2]] for s in data["speeds"]],  # [speed, incidents] only
        "i": [
            [i[1], i[3], i[4], i[8]]  # [id, location, description, start_time]
            for i in data.get("incidents", [])
            if len(i) >= 9
        ],
    }

    # Stats
    valid_speeds = sum(1 for s in compact_data["s"] if s[0] is not None)
    print(f"Valid speeds: {valid_speeds}/{len(compact_data['s'])}")
    print(f"Incidents: {len(compact_data['i'])}")

    # Compress and upload
    json_bytes = json.dumps(compact_data, separators=(",", ":")).encode("utf-8")
    print(f"Payload size: {len(json_bytes):,} bytes")

    # Key format: data/YYYY-MM-DD/HH/MMSS.json
    key = f"data/{date_str}/{hour_str}/{now.strftime('%M%S')}.json"

    if os.environ.get("R2_ACCOUNT_ID"):
        upload_to_r2(json_bytes, key)
    else:
        # Local mode - save to file
        out_dir = f"data/{date_str}/{hour_str}"
        os.makedirs(out_dir, exist_ok=True)
        out_path = f"{out_dir}/{now.strftime('%M%S')}.json"
        with open(out_path, "wb") as f:
            f.write(json_bytes)
        print(f"Saved locally to {out_path}")

    return compact_data


def main():
    """Entry point."""
    try:
        scrape_and_upload()
        print("Done!")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
