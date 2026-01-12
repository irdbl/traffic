#!/usr/bin/env python3
"""
Traffic Data Analysis Utilities

Example queries and analysis functions for the collected traffic data.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "traffic.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def list_routes(conn):
    """List all available routes with sensor counts."""
    cursor = conn.execute("""
        SELECT route, direction, COUNT(*) as sensor_count
        FROM sensors
        WHERE route IS NOT NULL
        GROUP BY route, direction
        ORDER BY route, direction
    """)
    print("Available Routes:")
    print("-" * 40)
    for route, direction, count in cursor:
        print(f"  Route {route} {direction}: {count} sensors")


def get_sensor_speeds(conn, sensor_idx: int, hours: int = 24):
    """Get speed history for a specific sensor."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    cursor = conn.execute("""
        SELECT timestamp, speed_mph, has_incident
        FROM speed_readings
        WHERE sensor_idx = ? AND timestamp > ?
        ORDER BY timestamp
    """, (sensor_idx, cutoff))
    return cursor.fetchall()


def get_route_average_speeds(conn, route: str, direction: str, hours: int = 1):
    """Get average speeds for all sensors on a route."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    cursor = conn.execute("""
        SELECT s.idx, s.name, AVG(r.speed_mph) as avg_speed, COUNT(*) as readings
        FROM sensors s
        JOIN speed_readings r ON s.idx = r.sensor_idx
        WHERE s.route = ? AND s.direction = ? AND r.timestamp > ?
        GROUP BY s.idx
        ORDER BY s.idx
    """, (route, direction, cutoff))
    return cursor.fetchall()


def find_slowdowns(conn, threshold: int = 25, hours: int = 1):
    """Find sensors with speeds below threshold in recent readings."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    cursor = conn.execute("""
        SELECT s.name, s.route, s.direction, AVG(r.speed_mph) as avg_speed
        FROM sensors s
        JOIN speed_readings r ON s.idx = r.sensor_idx
        WHERE r.timestamp > ? AND r.speed_mph IS NOT NULL
        GROUP BY s.idx
        HAVING AVG(r.speed_mph) < ?
        ORDER BY avg_speed
    """, (cutoff, threshold))
    return cursor.fetchall()


def get_recent_incidents(conn, hours: int = 24):
    """Get incidents from the last N hours."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    cursor = conn.execute("""
        SELECT id, location, description, start_time, update_time
        FROM incidents
        WHERE first_seen > ?
        ORDER BY start_time DESC
    """, (cutoff,))
    return cursor.fetchall()


def get_data_stats(conn):
    """Get overall statistics about collected data."""
    stats = {}

    # Total readings
    cursor = conn.execute("SELECT COUNT(*) FROM speed_readings")
    stats["total_readings"] = cursor.fetchone()[0]

    # Date range
    cursor = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM speed_readings")
    row = cursor.fetchone()
    stats["first_reading"] = row[0]
    stats["last_reading"] = row[1]

    # Sensor count
    cursor = conn.execute("SELECT COUNT(*) FROM sensors")
    stats["sensor_count"] = cursor.fetchone()[0]

    # Incident count
    cursor = conn.execute("SELECT COUNT(*) FROM incidents")
    stats["incident_count"] = cursor.fetchone()[0]

    # Readings per hour (estimate)
    if stats["first_reading"] and stats["last_reading"]:
        first = datetime.fromisoformat(stats["first_reading"].replace("Z", ""))
        last = datetime.fromisoformat(stats["last_reading"].replace("Z", ""))
        hours = max((last - first).total_seconds() / 3600, 1)
        stats["readings_per_hour"] = int(stats["total_readings"] / hours)

    return stats


def export_route_csv(conn, route: str, direction: str, output_path: str, hours: int = 24):
    """Export route data to CSV for external analysis."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    cursor = conn.execute("""
        SELECT r.timestamp, s.idx, s.name, r.speed_mph, r.has_incident
        FROM speed_readings r
        JOIN sensors s ON r.sensor_idx = s.idx
        WHERE s.route = ? AND s.direction = ? AND r.timestamp > ?
        ORDER BY r.timestamp, s.idx
    """, (route, direction, cutoff))

    with open(output_path, "w") as f:
        f.write("timestamp,sensor_idx,sensor_name,speed_mph,has_incident\n")
        for row in cursor:
            f.write(",".join(str(x) if x is not None else "" for x in row) + "\n")
    print(f"Exported to {output_path}")


def main():
    """Interactive analysis CLI."""
    conn = get_connection()

    print("Traffic Data Analyzer")
    print("=" * 40)

    stats = get_data_stats(conn)
    print(f"\nDatabase Stats:")
    print(f"  Total readings: {stats['total_readings']:,}")
    print(f"  Sensors: {stats['sensor_count']:,}")
    print(f"  Incidents: {stats['incident_count']:,}")
    if stats.get("first_reading"):
        print(f"  Date range: {stats['first_reading'][:19]} to {stats['last_reading'][:19]}")
        print(f"  ~{stats.get('readings_per_hour', 0):,} readings/hour")

    print("\n" + "=" * 40)
    list_routes(conn)

    print("\n" + "=" * 40)
    print("\nRecent Slowdowns (<25 mph avg):")
    slowdowns = find_slowdowns(conn, threshold=25, hours=1)
    for name, route, direction, avg_speed in slowdowns[:10]:
        print(f"  {name} ({route} {direction}): {avg_speed:.0f} mph")

    if not slowdowns:
        print("  No slowdowns found (or no recent data)")

    print("\n" + "=" * 40)
    print("\nRecent Incidents:")
    incidents = get_recent_incidents(conn, hours=4)
    for inc_id, location, desc, start, update in incidents[:5]:
        print(f"  [{start[11:16] if start else '?'}] {location}")
        print(f"         {desc}")

    if not incidents:
        print("  No recent incidents (or no recent data)")

    conn.close()


if __name__ == "__main__":
    main()
