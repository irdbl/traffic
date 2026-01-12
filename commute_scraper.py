#!/usr/bin/env python3
"""
Commute-Focused Traffic Scraper

Optimized for Mon-Wed commuting:
- Scrapes every 2 minutes during commute windows (5-10 AM, 3-8 PM)
- Scrapes every 15 minutes during off-peak hours (for baseline comparison)
- Only runs Mon-Wed by default (use --all-days for all days)

Run as a background service or cron job.
"""

import sqlite3
import time
import requests
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

# Import from main scraper
sys.path.insert(0, str(Path(__file__).parent))
from scraper import (
    STATIC_URL, DATA_URL, HEADERS, DB_PATH,
    init_db, load_static_data, populate_sensors, fetch_live_data,
    record_speeds, record_incidents
)

# Scrape intervals
PEAK_INTERVAL = 120      # 2 minutes during commute hours
OFF_PEAK_INTERVAL = 900  # 15 minutes during off-peak

# Commute windows (PST hours, will convert to UTC internally)
MORNING_WINDOW = (5, 10)   # 5 AM - 10 AM PST
EVENING_WINDOW = (15, 20)  # 3 PM - 8 PM PST

# Commute days (0=Monday, 1=Tuesday, 2=Wednesday)
COMMUTE_DAYS = {0, 1, 2}


def get_pst_hour() -> tuple[int, int]:
    """Get current hour and day of week in PST."""
    utc_now = datetime.now(timezone.utc)
    # PST = UTC - 8 (simplified, ignoring DST for now)
    pst_hour = (utc_now.hour - 8) % 24
    # Adjust day of week if we crossed midnight
    pst_day = utc_now.weekday()
    if utc_now.hour < 8:
        pst_day = (pst_day - 1) % 7
    return pst_hour, pst_day


def is_commute_window() -> tuple[bool, str]:
    """Check if we're in a commute window. Returns (is_peak, window_name)."""
    hour, day = get_pst_hour()

    if day not in COMMUTE_DAYS:
        return False, "non-commute-day"

    if MORNING_WINDOW[0] <= hour < MORNING_WINDOW[1]:
        return True, "morning"
    elif EVENING_WINDOW[0] <= hour < EVENING_WINDOW[1]:
        return True, "evening"
    else:
        return False, "off-peak"


def scrape_with_timing(conn: sqlite3.Connection) -> dict:
    """Perform scrape and return results with timing info."""
    timestamp = datetime.now(timezone.utc).isoformat()

    start = time.time()
    data = fetch_live_data()
    fetch_time = time.time() - start

    total, valid = record_speeds(conn, data, timestamp)
    incident_count = record_incidents(conn, data, timestamp)

    return {
        "timestamp": timestamp,
        "total_sensors": total,
        "valid_readings": valid,
        "incidents": incident_count,
        "fetch_time_ms": int(fetch_time * 1000),
    }


def run_scraper(all_days: bool = False, verbose: bool = True):
    """Main scraper loop with adaptive timing."""
    print("Commute-Focused Traffic Scraper")
    print(f"Database: {DB_PATH}")
    print(f"Mode: {'All days' if all_days else 'Mon-Wed only'}")
    print(f"Peak interval: {PEAK_INTERVAL}s, Off-peak: {OFF_PEAK_INTERVAL}s")
    print()

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Load static data
    static = load_static_data()
    populate_sensors(conn, static)

    print("\nStarting adaptive scrape loop (Ctrl+C to stop)...\n")

    last_window = None

    try:
        while True:
            is_peak, window = is_commute_window()
            hour, day = get_pst_hour()
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

            # Skip non-commute days unless --all-days
            if not all_days and day not in COMMUTE_DAYS:
                if window != last_window:
                    print(f"[{day_names[day]}] Non-commute day, sleeping until midnight...")
                    last_window = window
                # Sleep until next day (roughly)
                time.sleep(3600)  # Check every hour
                continue

            # Determine interval
            interval = PEAK_INTERVAL if is_peak else OFF_PEAK_INTERVAL

            # Log window changes
            if window != last_window:
                emoji = "🚗" if window == "morning" else "🚙" if window == "evening" else "😴"
                print(f"\n{emoji} Entering {window} window (interval: {interval}s)\n")
                last_window = window

            try:
                result = scrape_with_timing(conn)
                if verbose or is_peak:
                    status = "🟢" if result["valid_readings"] > 6000 else "🟡"
                    print(f"[{result['timestamp'][11:19]}] {status} "
                          f"{result['valid_readings']}/{result['total_sensors']} speeds, "
                          f"{result['incidents']} incidents "
                          f"({result['fetch_time_ms']}ms)")
            except requests.RequestException as e:
                print(f"[ERROR] Request failed: {e}")
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Commute-focused traffic scraper")
    parser.add_argument("--all-days", action="store_true",
                       help="Scrape all days, not just Mon-Wed")
    parser.add_argument("--quiet", action="store_true",
                       help="Only log during peak hours")
    parser.add_argument("--once", action="store_true",
                       help="Scrape once and exit")

    args = parser.parse_args()

    if args.once:
        conn = sqlite3.connect(DB_PATH)
        init_db(conn)
        static = load_static_data()
        populate_sensors(conn, static)
        result = scrape_with_timing(conn)
        print(f"Scraped: {result}")
        conn.close()
    else:
        run_scraper(all_days=args.all_days, verbose=not args.quiet)


if __name__ == "__main__":
    main()
