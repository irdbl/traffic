#!/usr/bin/env python3
"""Build commute camera dashboard with only working cameras."""

import urllib.request
import ssl
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

ssl_ctx = ssl.create_default_context()

ROUTES = ['405', '710', '110', '10', '105']
BOUNDS = {
    'minLat': 33.70,
    'maxLat': 34.05,
    'minLon': -118.50,
    'maxLon': -118.10
}

def fetch_json(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as response:
        return json.loads(response.read().decode('utf-8'))

def test_stream(url):
    """Test if HLS stream is working."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as response:
            content = response.read().decode('utf-8', errors='ignore')
            return '#EXTM3U' in content
    except:
        return False

def get_commute_cameras():
    """Fetch and filter cameras along commute route."""
    print("Fetching CalTrans D7 camera data...")
    data = fetch_json('https://cwwp2.dot.ca.gov/data/d7/cctv/cctvStatusD07.json')

    cameras = []
    for cam in data.get('data', []):
        cctv = cam.get('cctv', {})
        loc = cctv.get('location', {})
        stream = cctv.get('imageData', {}).get('streamingVideoURL', '')

        if not stream:
            continue

        route = loc.get('route', '')
        lat = float(loc.get('latitude', 0) or 0)
        lon = float(loc.get('longitude', 0) or 0)

        # Check if on commute route and in bounding box
        is_commute = any(r in route for r in ROUTES)
        in_bounds = (BOUNDS['minLat'] <= lat <= BOUNDS['maxLat'] and
                    BOUNDS['minLon'] <= lon <= BOUNDS['maxLon'])

        if is_commute and in_bounds:
            route_num = route.replace('I-', '').replace('SR-', '')

            cameras.append({
                'route': route_num,
                'lat': lat,
                'lon': lon,
                'stream': stream
            })

    print(f"Found {len(cameras)} cameras along commute routes")
    return cameras

def test_cameras(cameras):
    """Test which cameras are actually working."""
    print(f"Testing {len(cameras)} cameras...")

    working = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(test_stream, c['stream']): c for c in cameras}
        for future in as_completed(futures):
            cam = futures[future]
            if future.result():
                working.append(cam)
                print(f"  ✓ {cam['route']} ({cam['lat']:.3f})")

    # Sort in commute order: 405 (N→S) then 710 (N→S), then alternatives
    # This follows the drive from Culver City down 405, then 710 to Long Beach
    def commute_order(cam):
        route = cam['route']
        lat = cam['lat']
        lon = cam['lon']

        if route == '405':
            # 405: north to south, primary route start
            return (0, -lat)
        elif route == '710':
            # 710: north to south, primary route end
            return (1, -lat)
        elif route == '105':
            # 105: west to east (connector between 405 and 710)
            return (2, -lon)  # west to east = increasing longitude
        elif route == '110':
            # 110: north to south (alternate)
            return (3, -lat)
        elif route == '10':
            # 10: west to east (alternate start)
            return (4, -lon)
        else:
            return (99, -lat)

    working.sort(key=commute_order)

    print(f"\n{len(working)} working cameras")
    return working

def generate_html(cameras):
    """Generate static HTML with working cameras."""

    # Count by route
    counts = {}
    for cam in cameras:
        counts[cam['route']] = counts.get(cam['route'], 0) + 1

    # Generate camera JS array (no names needed - burned into feed)
    cams_js = ',\n    '.join([
        f'{{r:"{c["route"]}",s:"{c["stream"]}"}}'
        for c in cameras
    ])

    # Generate tab buttons
    tabs_html = f'<button class="tab active" data-r="all">All <span class="count">{len(cameras)}</span></button>'
    for route in ROUTES:
        if counts.get(route):
            tabs_html += f'\n        <button class="tab" data-r="{route}">{route} <span class="count">{counts[route]}</span></button>'

    updated = datetime.now().strftime('%b %d, %I:%M %p')

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Commute Cams</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ height: 100%; overflow: hidden; }}
        body {{
            background: #000;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background: #111;
            padding: 8px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }}
        .header h1 {{ font-size: 0.95em; font-weight: 500; color: #888; }}
        .header .time {{ font-size: 1.1em; font-weight: 300; }}
        .header .info {{ font-size: 0.75em; color: #555; }}
        .tabs {{
            display: flex;
            gap: 6px;
            padding: 6px 12px;
            background: #111;
            overflow-x: auto;
            flex-shrink: 0;
            border-bottom: 1px solid #222;
        }}
        .tab {{
            padding: 4px 12px;
            background: #222;
            border: none;
            border-radius: 12px;
            color: #666;
            cursor: pointer;
            font-size: 0.8em;
            white-space: nowrap;
        }}
        .tab.active {{ background: #0066cc; color: #fff; }}
        .tab .count {{
            background: rgba(255,255,255,0.2);
            padding: 1px 5px;
            border-radius: 6px;
            margin-left: 3px;
            font-size: 0.85em;
        }}
        .grid {{
            flex: 1;
            display: grid;
            gap: 2px;
            padding: 2px;
            overflow: hidden;
        }}
        .cam {{
            position: relative;
            background: #000;
            min-width: 0;
            min-height: 0;
        }}
        .cam video {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}
        .cam .badge {{
            position: absolute;
            top: 4px;
            left: 4px;
            background: rgba(0,100,200,0.8);
            padding: 2px 6px;
            border-radius: 8px;
            font-size: 0.65em;
            font-weight: 600;
        }}
        .cam .dot {{
            position: absolute;
            top: 6px;
            right: 6px;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #333;
        }}
        .cam .dot.live {{ background: #0c6; animation: pulse 2s infinite; }}
        .cam .dot.err {{ background: #c33; }}
        @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.4}} }}
        .fs {{
            position: fixed;
            inset: 0;
            z-index: 999;
            background: #000;
        }}
        .fs video {{ width: 100%; height: 100%; object-fit: contain; }}
        .fs .x {{
            position: absolute;
            top: 12px;
            right: 12px;
            background: rgba(0,0,0,0.6);
            border: none;
            color: #fff;
            padding: 6px 14px;
            border-radius: 12px;
            cursor: pointer;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Culver City → Long Beach</h1>
        <span class="info">{len(cameras)} cams • {updated}</span>
        <span class="time" id="clock"></span>
    </div>
    <div class="tabs">
        {tabs_html}
    </div>
    <div class="grid" id="grid"></div>
<script>
const cams = [
    {cams_js}
];

const players = new Map();

function updateClock() {{
    document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-US', {{
        hour: 'numeric', minute: '2-digit', hour12: true
    }});
}}

function mkCam(c, i) {{
    const d = document.createElement('div');
    d.className = 'cam';
    d.dataset.r = c.r;
    d.innerHTML = `
        <video id="v${{i}}" muted playsinline></video>
        <div class="badge">${{c.r}}</div>
        <div class="dot" id="d${{i}}"></div>
    `;
    d.onclick = () => fullscreen(i);
    return d;
}}

function initHls(i, url) {{
    const v = document.getElementById('v'+i);
    const d = document.getElementById('d'+i);

    if (Hls.isSupported()) {{
        const h = new Hls({{ enableWorker: true, lowLatencyMode: true }});
        h.loadSource(url);
        h.attachMedia(v);
        h.on(Hls.Events.MANIFEST_PARSED, () => {{ v.play().catch(()=>{{}}); d.className='dot live'; }});
        h.on(Hls.Events.ERROR, (_,e) => {{
            if (e.fatal) {{ d.className='dot err'; setTimeout(() => h.loadSource(url), 15000); }}
        }});
        players.set(i, h);
    }} else if (v.canPlayType('application/vnd.apple.mpegurl')) {{
        v.src = url;
        v.onloadedmetadata = () => {{ v.play().catch(()=>{{}}); d.className='dot live'; }};
    }}
}}

function filter(r) {{
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.r === r));
    document.querySelectorAll('.cam').forEach(c => c.style.display = (r==='all' || c.dataset.r===r) ? 'block' : 'none');
}}

function fullscreen(i) {{
    if (document.querySelector('.fs')) {{ document.querySelector('.fs').remove(); return; }}
    const d = document.createElement('div');
    d.className = 'fs';
    d.innerHTML = `<video id="fsv" muted playsinline autoplay></video><button class="x">✕</button>`;
    document.body.appendChild(d);

    const v = document.getElementById('fsv');
    if (Hls.isSupported()) {{
        const h = new Hls();
        h.loadSource(cams[i].s);
        h.attachMedia(v);
        h.on(Hls.Events.MANIFEST_PARSED, () => v.play());
    }} else v.src = cams[i].s;

    d.querySelector('.x').onclick = () => d.remove();
}}

function layoutGrid() {{
    const grid = document.getElementById('grid');
    const visible = [...document.querySelectorAll('.cam')].filter(c => c.style.display !== 'none');
    const n = visible.length;
    if (n === 0) return;

    const rect = grid.getBoundingClientRect();
    const w = rect.width - 4;  // padding
    const h = rect.height - 4;
    const ratio = 4/3;  // camera aspect ratio

    // Find optimal grid that fills space
    let bestCols = 1, bestRows = n, bestSize = 0;
    for (let cols = 1; cols <= n; cols++) {{
        const rows = Math.ceil(n / cols);
        const cellW = w / cols;
        const cellH = h / rows;
        // Size limited by either width or height
        const size = Math.min(cellW, cellH * ratio);
        if (size > bestSize) {{
            bestSize = size;
            bestCols = cols;
            bestRows = rows;
        }}
    }}

    grid.style.gridTemplateColumns = `repeat(${{bestCols}}, 1fr)`;
    grid.style.gridTemplateRows = `repeat(${{bestRows}}, 1fr)`;
}}

document.addEventListener('DOMContentLoaded', () => {{
    const g = document.getElementById('grid');
    cams.forEach((c,i) => {{ g.appendChild(mkCam(c,i)); initHls(i, c.s); }});
    document.querySelectorAll('.tab').forEach(t => t.onclick = () => {{ filter(t.dataset.r); layoutGrid(); }});
    updateClock();
    setInterval(updateClock, 1000);
    layoutGrid();
    window.addEventListener('resize', layoutGrid);
}});
</script>
</body>
</html>'''

    return html

def main():
    cameras = get_commute_cameras()
    working = test_cameras(cameras)

    if not working:
        print("No working cameras found!")
        return 1

    html = generate_html(working)

    with open('index.html', 'w') as f:
        f.write(html)

    print(f"\nGenerated index.html with {len(working)} cameras")
    return 0

if __name__ == "__main__":
    exit(main())
