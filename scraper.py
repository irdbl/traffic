#!/usr/bin/env python3
"""
Sigalert Traffic Data Scraper
Collects historical traffic speed data from sigalert.com for Southern California.

Data Structure:
- SoCalStatic.json: Static metadata (sensor names, positions, road sections)
- SoCalData.json: Live data (speeds, incidents, cameras)

Speed array format: [speed_mph, null, [incident_refs], camera_id?]
- speed_mph: Current speed at sensor (null if no data)
- incident_refs: List of [type, incident_id] pairs (type 1 = active incident)

Incident format: [road_section_id, incident_id, time_str, location, description,
                  severity?, x, y, start_time, update_time]
"""

import json
import sqlite3
import time
import requests
from datetime import datetime
from pathlib import Path

# Configuration
STATIC_URL = "https://cdn-static.sigalert.com/240/Zip/RegionInfo/SoCalStatic.json"
DATA_URL = "https://www.sigalert.com/Data/SoCal/4~j/SoCalData.json"
DB_PATH = Path(__file__).parent / "traffic.db"
SCRAPE_INTERVAL = 300  # 5 minutes

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.sigalert.com/",
}


def init_db(conn: sqlite3.Connection):
    """Initialize database schema."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sensors (
            idx INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            road_section_id INTEGER,
            direction TEXT,
            route TEXT
        );

        CREATE TABLE IF NOT EXISTS road_sections (
            id INTEGER PRIMARY KEY,
            direction TEXT,
            route TEXT,
            start_idx INTEGER,
            end_idx INTEGER
        );

        CREATE TABLE IF NOT EXISTS speed_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            sensor_idx INTEGER NOT NULL,
            speed_mph INTEGER,
            has_incident INTEGER DEFAULT 0,
            incident_ids TEXT,
            FOREIGN KEY (sensor_idx) REFERENCES sensors(idx)
        );

        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY,
            road_section_id INTEGER,
            time_str TEXT,
            location TEXT,
            description TEXT,
            severity INTEGER,
            x INTEGER,
            y INTEGER,
            start_time TEXT,
            update_time TEXT,
            first_seen TEXT,
            last_seen TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON speed_readings(timestamp);
        CREATE INDEX IF NOT EXISTS idx_readings_sensor ON speed_readings(sensor_idx);
        CREATE INDEX IF NOT EXISTS idx_readings_ts_sensor ON speed_readings(timestamp, sensor_idx);
    """)
    conn.commit()


def load_static_data() -> dict:
    """Fetch and return static metadata."""
    print("Fetching static data...")
    resp = requests.get(STATIC_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def populate_sensors(conn: sqlite3.Connection, static_data: dict):
    """Populate sensors table from static data."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sensors")
    if cursor.fetchone()[0] > 0:
        print("Sensors already populated, skipping...")
        return

    print("Populating sensors...")
    sensor_names = static_data["sensorNames"]
    road_sections = static_data["roadSections"]

    # Build index -> road section mapping
    idx_to_section = {}
    for section in road_sections:
        section_id, direction, route, start_idx, end_idx = section
        for idx in range(start_idx, end_idx + 1):
            idx_to_section[idx] = (section_id, direction, route)

    # Populate road_sections table
    for section in road_sections:
        section_id, direction, route, start_idx, end_idx = section
        cursor.execute("""
            INSERT OR REPLACE INTO road_sections (id, direction, route, start_idx, end_idx)
            VALUES (?, ?, ?, ?, ?)
        """, (section_id, direction, route, start_idx, end_idx))

    # Populate sensors table
    for idx, name in enumerate(sensor_names):
        section_info = idx_to_section.get(idx, (None, None, None))
        cursor.execute("""
            INSERT OR REPLACE INTO sensors (idx, name, road_section_id, direction, route)
            VALUES (?, ?, ?, ?, ?)
        """, (idx, name, section_info[0], section_info[1], section_info[2]))

    conn.commit()
    print(f"Populated {len(sensor_names)} sensors and {len(road_sections)} road sections")


def fetch_live_data() -> dict:
    """Fetch current traffic data."""
    cb = int(time.time() * 1000) % 100000000
    url = f"{DATA_URL}?cb={cb}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def record_speeds(conn: sqlite3.Connection, data: dict, timestamp: str):
    """Record speed readings to database."""
    cursor = conn.cursor()
    speeds = data["speeds"]

    batch = []
    for idx, entry in enumerate(speeds):
        speed = entry[0]  # Can be None
        incidents = entry[2] if len(entry) > 2 else []
        has_incident = 1 if incidents else 0
        incident_ids = json.dumps([i[1] for i in incidents]) if incidents else None

        batch.append((timestamp, idx, speed, has_incident, incident_ids))

    cursor.executemany("""
        INSERT INTO speed_readings (timestamp, sensor_idx, speed_mph, has_incident, incident_ids)
        VALUES (?, ?, ?, ?, ?)
    """, batch)
    conn.commit()

    # Count non-null speeds
    valid_speeds = sum(1 for s in speeds if s[0] is not None)
    return len(speeds), valid_speeds


def record_incidents(conn: sqlite3.Connection, data: dict, timestamp: str):
    """Record/update incidents."""
    cursor = conn.cursor()
    incidents = data.get("incidents", [])

    for inc in incidents:
        if len(inc) < 10:
            continue
        road_section_id, incident_id, time_str, location, desc, severity, x, y, start_time, update_time = inc[:10]

        # Check if incident exists
        cursor.execute("SELECT first_seen FROM incidents WHERE id = ?", (incident_id,))
        row = cursor.fetchone()

        if row:
            # Update existing
            cursor.execute("""
                UPDATE incidents SET
                    description = ?, update_time = ?, last_seen = ?
                WHERE id = ?
            """, (desc, update_time, timestamp, incident_id))
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO incidents
                (id, road_section_id, time_str, location, description, severity, x, y, start_time, update_time, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (incident_id, road_section_id, time_str, location, desc, severity, x, y, start_time, update_time, timestamp, timestamp))

    conn.commit()
    return len(incidents)


def scrape_once(conn: sqlite3.Connection) -> dict:
    """Perform a single scrape cycle."""
    timestamp = datetime.utcnow().isoformat() + "Z"

    data = fetch_live_data()
    total, valid = record_speeds(conn, data, timestamp)
    incident_count = record_incidents(conn, data, timestamp)

    return {
        "timestamp": timestamp,
        "total_sensors": total,
        "valid_readings": valid,
        "incidents": incident_count,
    }


def main():
    """Main scraper loop."""
    print(f"Sigalert Traffic Scraper")
    print(f"Database: {DB_PATH}")
    print(f"Interval: {SCRAPE_INTERVAL}s")
    print()

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Load and populate static data
    static_data = load_static_data()
    populate_sensors(conn, static_data)

    print("\nStarting scrape loop (Ctrl+C to stop)...\n")

    try:
        while True:
            try:
                result = scrape_once(conn)
                print(f"[{result['timestamp']}] {result['valid_readings']}/{result['total_sensors']} speeds, {result['incidents']} incidents")
            except requests.RequestException as e:
                print(f"[ERROR] Request failed: {e}")
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")

            time.sleep(SCRAPE_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
