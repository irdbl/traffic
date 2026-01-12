# Sigalert Traffic Data Format

## API Endpoints

### Static Data (metadata, rarely changes)
```
GET https://cdn-static.sigalert.com/240/Zip/RegionInfo/SoCalStatic.json
```

### Live Data (updates every ~2 minutes)
```
GET https://www.sigalert.com/Data/SoCal/4~j/SoCalData.json?cb={timestamp}
```
Required headers: `X-Requested-With: XMLHttpRequest`

---

## Static Data Structure

```json
{
  "sensorNames": ["I-5", "Exit Name 1", "Exit Name 2", ...],  // 6308 items
  "sensorPositions": [[x1, y1, x2, y2], ...],                 // Map coordinates
  "roadSections": [[id, direction, route, start_idx, end_idx], ...],
  "roads": { "road_id": [route, ?, ?, [[start, end, speed_limit], ...]], ... }
}
```

### sensorNames (6308 entries)
Array index corresponds to sensor/segment index. Names are typically:
- Exit/ramp names (e.g., "Doheny Park Rd")
- Highway references (e.g., "I-5", "CA-133 North")
- Distance markers (e.g., "Main St (1.4 miles before)")

### roadSections (116 entries)
Defines contiguous highway segments:
```
[section_id, direction, route_number, start_sensor_idx, end_sensor_idx]
```
Example: `[100011, "North", "1", 0, 425]` = Route 1 Northbound, sensors 0-425

### roads (102 entries)
Speed limit information by segment range:
```
"100011": ["1", 0, 0, [[0, 2, 55], [3, 3, 40], ...]]
                       ^start ^end ^limit(mph)
```

---

## Live Data Structure

```json
{
  "speeds": [[speed, null, incidents, camera_id?], ...],  // 6308 items
  "incidents": [[...], ...],
  "cameras": [[...], ...]
}
```

### speeds (6308 entries)
Array index maps to `sensorNames` index:
```
[speed_mph, null, [incident_refs], optional_camera_id]
```

| Field | Type | Description |
|-------|------|-------------|
| speed_mph | int/null | Current speed (null = no data) |
| null | - | Reserved/unused |
| incident_refs | array | `[[type, incident_id], ...]` Type 1 = active |
| camera_id | int? | Optional reference to cameras array |

### incidents
Active traffic incidents:
```
[road_section_id, incident_id, time_str, location, description,
 severity?, x, y, start_time_iso, update_time_iso]
```

Example:
```json
[968, 47601929, "7:16 PM", "I-5 North at Ave Pico",
 "2 vehicle crash. Center divider.", 50, 7800, 4429,
 "2026-01-12T03:16:14", "2026-01-12T03:16:14"]
```

### cameras
Traffic camera info with live image URLs:
```
[camera_id, x, y, ?, name, description, image_url, copyright, refresh_ms, ?]
```

---

## Database Schema (scraper.py)

```sql
-- Sensor metadata (populated once from static data)
sensors(idx, name, road_section_id, direction, route)

-- Road section definitions
road_sections(id, direction, route, start_idx, end_idx)

-- Historical speed readings (main data)
speed_readings(id, timestamp, sensor_idx, speed_mph, has_incident, incident_ids)

-- Incident history
incidents(id, road_section_id, time_str, location, description,
          severity, x, y, start_time, update_time, first_seen, last_seen)
```

---

## Usage

```bash
# Start scraper (collects every 5 minutes)
.venv/bin/python scraper.py

# Analyze collected data
.venv/bin/python analyze.py

# Query database directly
sqlite3 traffic.db "SELECT s.name, AVG(r.speed_mph)
  FROM speed_readings r JOIN sensors s ON r.sensor_idx = s.idx
  WHERE s.route = '5' AND s.direction = 'North'
  GROUP BY s.idx ORDER BY s.idx"
```

---

## Key Routes (SoCal)

| Route | Description |
|-------|-------------|
| 1 | Pacific Coast Highway (PCH) |
| 5 | I-5 (runs through LA to San Diego) |
| 10 | I-10 (Santa Monica to San Bernardino) |
| 15 | I-15 (San Diego to Barstow) |
| 101 | US-101 (Hollywood/Ventura Fwy) |
| 405 | I-405 (San Diego Fwy) |
| 110 | I-110 (Harbor Fwy) |
| 710 | I-710 (Long Beach Fwy) |
