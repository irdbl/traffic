#!/usr/bin/env python3
"""
Download traffic data from R2 and import into local SQLite database.

Usage:
    python cloud/download_data.py                    # Download last 7 days
    python cloud/download_data.py --days 30          # Download last 30 days
    python cloud/download_data.py --date 2026-01-15  # Download specific date

Environment variables:
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper import init_db, load_static_data, populate_sensors, DB_PATH


def get_s3_client():
    """Get boto3 S3 client for R2."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def list_objects(s3, bucket: str, prefix: str) -> list:
    """List all objects with given prefix."""
    objects = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            objects.append(obj["Key"])

    return objects


def download_and_import(s3, bucket: str, key: str, conn: sqlite3.Connection) -> int:
    """Download a single file and import into database."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
    except Exception as e:
        print(f"  Error downloading {key}: {e}")
        return 0

    timestamp = data["t"]
    speeds = data["s"]
    incidents = data.get("i", [])

    # Insert speed readings
    cursor = conn.cursor()
    batch = []
    for idx, entry in enumerate(speeds):
        speed = entry[0]
        incident_list = entry[1] if len(entry) > 1 else []
        has_incident = 1 if incident_list else 0
        incident_ids = json.dumps([i[1] for i in incident_list]) if incident_list else None
        batch.append((timestamp, idx, speed, has_incident, incident_ids))

    cursor.executemany("""
        INSERT OR IGNORE INTO speed_readings (timestamp, sensor_idx, speed_mph, has_incident, incident_ids)
        VALUES (?, ?, ?, ?, ?)
    """, batch)

    # Insert/update incidents
    for inc in incidents:
        if len(inc) >= 4:
            inc_id, location, desc, start_time = inc[:4]
            cursor.execute("""
                INSERT OR REPLACE INTO incidents
                (id, location, description, start_time, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (inc_id, location, desc, start_time, timestamp, timestamp))

    conn.commit()
    return len(batch)


def main():
    parser = argparse.ArgumentParser(description="Download R2 data to local SQLite")
    parser.add_argument("--days", type=int, default=7, help="Download last N days")
    parser.add_argument("--date", type=str, help="Download specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    # Initialize database
    print(f"Database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Ensure sensors are populated
    static = load_static_data()
    populate_sensors(conn, static)

    # Get R2 client
    s3 = get_s3_client()
    bucket = os.environ.get("R2_BUCKET_NAME", "traffic-data")

    # Determine dates to download
    if args.date:
        dates = [args.date]
    else:
        today = datetime.now(timezone.utc).date()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]

    total_readings = 0

    for date_str in dates:
        prefix = f"data/{date_str}/"
        print(f"\nDownloading {date_str}...")

        keys = list_objects(s3, bucket, prefix)
        print(f"  Found {len(keys)} files")

        for key in keys:
            count = download_and_import(s3, bucket, key, conn)
            total_readings += count

        print(f"  Imported readings for {date_str}")

    print(f"\nTotal readings imported: {total_readings:,}")

    # Show stats
    cursor = conn.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM speed_readings")
    count, min_ts, max_ts = cursor.fetchone()
    print(f"Database now has {count:,} readings from {min_ts} to {max_ts}")

    conn.close()


if __name__ == "__main__":
    main()
