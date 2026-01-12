#!/usr/bin/env python3
"""
Commute Analyzer: Culver City <-> Port of Long Beach

Routes analyzed:
1. 405 Route: 405 S → 710 S (most direct)
2. 105 Route: 405 S → 105 E → 710 S (avoids 405/710 interchange)
3. 110 Route: 10 E → 110 S → 710 S (downtown adjacent)

Reverse directions for evening commute.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
import json

DB_PATH = Path(__file__).parent / "traffic.db"

# Approximate distances in miles between sensor segments (avg ~0.5 mi per sensor)
# These are rough estimates - sigalert doesn't provide exact distances
MILES_PER_SENSOR = 0.5

# Route definitions: list of (route, direction, start_idx, end_idx) tuples
# Morning commute: Culver City -> Port of Long Beach
ROUTES_MORNING = {
    "405→710": [
        ("405", "South", 5789, 5816),  # Culver Blvd to 710 interchange
        ("710", "West", 5949, 5956),   # 710 interchange to Harbor Blvd/Terminal
    ],
    "405→105→710": [
        ("405", "South", 5789, 5800),  # Culver to 105
        ("105", "East", 4754, 4768),   # 405 to 710
        ("710", "West", 5949, 5956),   # 710 to Terminal
    ],
    "10→110→710": [
        ("10", "East", 1537, 1551),    # 405 to 110
        ("110", "South", 4825, 4873),  # 10 to end (near 710/harbor area)
        ("710", "West", 5949, 5956),   # To Terminal
    ],
}

# Evening commute: Port of Long Beach -> Culver City
ROUTES_EVENING = {
    "710→405": [
        ("710", "East", 5924, 5930),   # Terminal/Harbor to 405 interchange
        ("405", "North", 5709, 5736),  # 710 interchange to Culver Blvd
    ],
    "710→105→405": [
        ("710", "East", 5924, 5930),   # Terminal to 105
        ("105", "West", 4781, 4795),   # 710 to 405
        ("405", "North", 5730, 5736),  # 105 to Culver
    ],
    "710→110→10": [
        ("710", "East", 5924, 5930),   # Terminal area
        ("110", "North", 4776, 4824),  # Harbor area to 10
        ("10", "West", 1981, 1993),    # 110 to 405/Culver area
    ],
}


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_segment_speeds(conn, route: str, direction: str, start_idx: int, end_idx: int,
                       timestamp: str = None, hours_back: float = 0.5) -> list:
    """Get speeds for a route segment, optionally at a specific time."""
    if timestamp:
        # Get reading closest to timestamp
        cursor = conn.execute("""
            SELECT sensor_idx, speed_mph
            FROM speed_readings
            WHERE sensor_idx BETWEEN ? AND ?
            AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (start_idx, end_idx, timestamp, end_idx - start_idx + 1))
    else:
        # Get most recent readings
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
        cursor = conn.execute("""
            SELECT r.sensor_idx, AVG(r.speed_mph) as avg_speed
            FROM speed_readings r
            JOIN sensors s ON r.sensor_idx = s.idx
            WHERE s.route = ? AND s.direction = ?
            AND r.sensor_idx BETWEEN ? AND ?
            AND r.timestamp > ?
            AND r.speed_mph IS NOT NULL
            GROUP BY r.sensor_idx
            ORDER BY r.sensor_idx
        """, (route, direction, start_idx, end_idx, cutoff))

    return cursor.fetchall()


def estimate_travel_time(speeds: list, miles_per_segment: float = MILES_PER_SENSOR) -> tuple:
    """
    Estimate travel time from sensor speeds.
    Returns (minutes, avg_speed, min_speed, segment_count)
    """
    if not speeds:
        return (None, None, None, 0)

    total_time = 0
    valid_speeds = [s[1] for s in speeds if s[1] and s[1] > 0]

    if not valid_speeds:
        return (None, None, None, len(speeds))

    for speed in valid_speeds:
        # Time = distance / speed, convert to minutes
        segment_time = (miles_per_segment / speed) * 60
        total_time += segment_time

    avg_speed = sum(valid_speeds) / len(valid_speeds)
    min_speed = min(valid_speeds)

    return (total_time, avg_speed, min_speed, len(valid_speeds))


def analyze_route(conn, route_name: str, segments: list) -> dict:
    """Analyze a complete route with multiple segments."""
    total_time = 0
    total_segments = 0
    min_speed_overall = 999
    all_speeds = []
    segment_details = []

    for route, direction, start_idx, end_idx in segments:
        speeds = get_segment_speeds(conn, route, direction, start_idx, end_idx)
        time_mins, avg_spd, min_spd, count = estimate_travel_time(speeds)

        if time_mins:
            total_time += time_mins
            total_segments += count
            if min_spd and min_spd < min_speed_overall:
                min_speed_overall = min_spd
            all_speeds.extend([s[1] for s in speeds if s[1]])

        segment_details.append({
            "segment": f"{route} {direction}",
            "sensors": count,
            "time_mins": round(time_mins, 1) if time_mins else None,
            "avg_speed": round(avg_spd, 1) if avg_spd else None,
            "min_speed": min_spd,
        })

    return {
        "route": route_name,
        "total_time_mins": round(total_time, 1) if total_time else None,
        "avg_speed": round(sum(all_speeds) / len(all_speeds), 1) if all_speeds else None,
        "min_speed": min_speed_overall if min_speed_overall < 999 else None,
        "segments": segment_details,
    }


def current_commute_status(conn, direction: str = "morning"):
    """Get current estimated commute times for all routes."""
    routes = ROUTES_MORNING if direction == "morning" else ROUTES_EVENING

    results = []
    for route_name, segments in routes.items():
        result = analyze_route(conn, route_name, segments)
        results.append(result)

    # Sort by travel time
    results.sort(key=lambda x: x["total_time_mins"] or 999)
    return results


def get_historical_pattern(conn, route: str, direction: str, start_idx: int, end_idx: int,
                           day_of_week: int = None, hour: int = None, weeks_back: int = 4):
    """
    Analyze historical patterns for a route segment.
    day_of_week: 0=Monday, 1=Tuesday, etc.
    hour: 0-23
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks_back)).isoformat() + "Z"

    query = """
        SELECT
            strftime('%w', timestamp) as dow,
            strftime('%H', timestamp) as hour,
            AVG(speed_mph) as avg_speed,
            MIN(speed_mph) as min_speed,
            COUNT(*) as readings
        FROM speed_readings r
        JOIN sensors s ON r.sensor_idx = s.idx
        WHERE s.route = ? AND s.direction = ?
        AND r.sensor_idx BETWEEN ? AND ?
        AND r.timestamp > ?
        AND r.speed_mph IS NOT NULL
    """
    params = [route, direction, start_idx, end_idx, cutoff]

    if day_of_week is not None:
        # SQLite strftime %w: 0=Sunday, so Monday=1
        sqlite_dow = (day_of_week + 1) % 7
        query += " AND strftime('%w', timestamp) = ?"
        params.append(str(sqlite_dow))

    if hour is not None:
        query += " AND strftime('%H', timestamp) = ?"
        params.append(f"{hour:02d}")

    query += " GROUP BY dow, hour ORDER BY dow, hour"

    cursor = conn.execute(query, params)
    return cursor.fetchall()


def analyze_best_departure_times(conn, direction: str = "morning",
                                  day_of_week: int = None, weeks_back: int = 4):
    """
    Find best departure times based on historical data.
    Returns hourly averages for each route.
    """
    routes = ROUTES_MORNING if direction == "morning" else ROUTES_EVENING

    # Relevant hours: morning 5-10 AM, evening 3-8 PM
    hours = range(5, 11) if direction == "morning" else range(15, 21)

    results = defaultdict(lambda: defaultdict(list))

    for route_name, segments in routes.items():
        for route, dir_, start_idx, end_idx in segments:
            for hour in hours:
                data = get_historical_pattern(conn, route, dir_, start_idx, end_idx,
                                             day_of_week=day_of_week, hour=hour,
                                             weeks_back=weeks_back)
                if data:
                    avg_speed = sum(d[2] for d in data) / len(data)
                    results[route_name][hour].append(avg_speed)

    # Aggregate results
    summary = {}
    for route_name in routes:
        summary[route_name] = {}
        for hour in hours:
            speeds = results[route_name].get(hour, [])
            if speeds:
                avg = sum(speeds) / len(speeds)
                # Rough time estimate for full route
                total_sensors = sum(s[3] - s[2] for s in routes[route_name])
                est_time = (total_sensors * MILES_PER_SENSOR / avg) * 60
                summary[route_name][hour] = {
                    "avg_speed": round(avg, 1),
                    "est_time_mins": round(est_time, 1),
                }

    return summary


def print_commute_report(conn):
    """Print a comprehensive commute report."""
    print("=" * 70)
    print("COMMUTE REPORT: Culver City <-> Port of Long Beach")
    print("=" * 70)

    now = datetime.now(timezone.utc)
    local_hour = (now.hour - 8) % 24  # Rough PST conversion

    print(f"\nCurrent time (approx): {local_hour}:00 PST")

    # Determine if it's morning or evening commute time
    if 5 <= local_hour <= 10:
        direction = "morning"
        print("\n>>> MORNING COMMUTE (Culver City → Port of Long Beach)\n")
    elif 15 <= local_hour <= 20:
        direction = "evening"
        print("\n>>> EVENING COMMUTE (Port of Long Beach → Culver City)\n")
    else:
        direction = "morning"  # Default to morning for off-hours
        print("\n>>> SHOWING MORNING ROUTES (off-peak hours)\n")

    results = current_commute_status(conn, direction)

    print("Current Route Estimates (ranked by travel time):\n")
    for i, r in enumerate(results, 1):
        status = "🟢" if r["min_speed"] and r["min_speed"] >= 50 else "🟡" if r["min_speed"] and r["min_speed"] >= 30 else "🔴"
        time_str = f"{r['total_time_mins']} min" if r['total_time_mins'] else "N/A"
        speed_str = f"avg {r['avg_speed']} mph" if r['avg_speed'] else ""
        slowest = f"slowest: {r['min_speed']} mph" if r['min_speed'] else ""

        print(f"  {i}. {status} {r['route']}: {time_str} ({speed_str}, {slowest})")
        for seg in r['segments']:
            seg_time = f"{seg['time_mins']} min" if seg['time_mins'] else "N/A"
            print(f"       └─ {seg['segment']}: {seg_time} (avg {seg['avg_speed']} mph)")

    # Check data availability for historical analysis
    cursor = conn.execute("SELECT COUNT(DISTINCT date(timestamp)) FROM speed_readings")
    days_of_data = cursor.fetchone()[0]

    print(f"\n{'=' * 70}")
    print(f"Data collected: {days_of_data} day(s)")

    if days_of_data < 3:
        print("\n⚠️  Need more data for pattern analysis!")
        print("   Run scraper for at least 1 week to see departure time recommendations.")
        print("   Ideally, collect 2-4 weeks of data covering Mon-Wed commute times.")
    else:
        print("\nHistorical Analysis Available - run with --analyze flag")


def main():
    import sys

    conn = get_connection()

    if "--analyze" in sys.argv:
        # Detailed historical analysis
        print("Historical pattern analysis (requires sufficient data)...")
        for dow, day_name in [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday")]:
            print(f"\n{day_name}:")
            for direction in ["morning", "evening"]:
                print(f"  {direction.title()} commute:")
                summary = analyze_best_departure_times(conn, direction, day_of_week=dow)
                for route, hours in summary.items():
                    if hours:
                        best_hour = min(hours.items(), key=lambda x: x[1].get("est_time_mins", 999))
                        print(f"    {route}: Best at {best_hour[0]}:00 (~{best_hour[1].get('est_time_mins', '?')} min)")
    elif "--json" in sys.argv:
        import json
        results = {
            "morning": current_commute_status(conn, "morning"),
            "evening": current_commute_status(conn, "evening"),
        }
        print(json.dumps(results, indent=2))
    else:
        print_commute_report(conn)

    conn.close()


if __name__ == "__main__":
    main()
