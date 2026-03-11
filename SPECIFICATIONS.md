# Gallaudet Campus Wayfinding Application — Full Specification

> **Purpose**: This document provides enough detail to fully rebuild the application using generative AI. Every route, data structure, algorithm, template, and deployment detail is specified.

---

## 1. Overview

A Flask web application providing GPS-aware campus navigation for Gallaudet University. Users select a start and end location (or use live GPS), and the app computes the shortest walking route through campus walkways using Dijkstra's algorithm on a weighted graph. Results are displayed on an interactive Leaflet/OpenStreetMap map. An admin interface allows managing the campus graph (adding nodes, adding/deleting edges).

---

## 2. Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend framework | Flask | 3.1.1 |
| Graph/pathfinding | NetworkX | 3.4.2 |
| Data processing | Pandas | 2.3.1 |
| Map rendering | Folium (Leaflet.js) | 0.20.0 |
| Password hashing | Werkzeug (scrypt) | 3.1.3 |
| WSGI server | Gunicorn | 23.0.0 |
| Reverse proxy | Nginx | — |
| Python | 3.12+ | — |
| Frontend | HTML5, vanilla JS, Leaflet.js, Browser Geolocation API | — |

---

## 3. Directory Structure

```
/var/www/wayfinding/
├── app.py                   # Main Flask application (~1,165 lines, includes all templates)
├── wsgi.py                  # Gunicorn entry point: `from app import app`
├── nodes.csv                # Campus locations (buildings + connector nodes)
├── edges.csv                # Walkway connections with distances
├── requirements.txt         # Python dependencies
├── nginx.conf               # Nginx reverse proxy location block
├── wayfinding.service       # systemd unit file
├── wayfinding.env           # Environment variables (admin hash + secret key)
├── create_wayfinding_env.sh # Interactive script to generate wayfinding.env
├── restart.sh               # Reloads nginx + restarts wayfinding service
├── cat_ai_files.sh          # Utility to dump codebase for AI context
├── wayfinding.py            # CLI route finder (development/testing tool)
├── plot_graph.py            # Static PNG graph visualization
├── plot_map.py              # Static HTML map generation
├── get_gps_coordinates_openstreetmap.py # OSM geocoding utility
└── .venv/                   # Python virtual environment
```

---

## 4. Data Model

### 4.1 nodes.csv

**Schema**: `label,lat,lon,level`

| Column | Type | Description |
|--------|------|-------------|
| label | string | Unique identifier. Either a building name (e.g., "College Hall") or a connector code matching pattern `c\d{2,3}` (e.g., "c000"–"c107") |
| lat | float | Latitude, range -90 to 90 |
| lon | float | Longitude, range -180 to 180 |
| level | string | "ground" or "second level" (currently unused in routing; future multi-floor support) |

**Two node types**:
- **Named locations** (~56): Buildings and landmarks visible to users in dropdowns
- **Connector nodes** (~108): Walkway intersection points (pattern `c\d{2,3}`), invisible to users, used as routing intermediates

**Current data**: 164 rows, all within Gallaudet campus bounds (~38.904–38.911N, ~76.989–76.997W)

### 4.2 edges.csv

**Schema**: `from,to,distance`

| Column | Type | Description |
|--------|------|-------------|
| from | string | Label of first node (must exist in nodes.csv) |
| to | string | Label of second node (must exist in nodes.csv) |
| distance | float | Haversine great-circle distance in meters (always server-computed) |

**Characteristics**:
- Undirected (bidirectional)
- 217 rows
- Distance range: ~7.7m to ~142.3m
- No self-loops, no duplicates (bidirectional dedup: {a,b} == {b,a})

---

## 5. Core Algorithms

### 5.1 Haversine Distance

Computes great-circle distance in meters between two lat/lon points:

```python
def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0  # Earth radius in meters
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * R * asin(sqrt(a))
```

**Server authority**: All edge weights are computed server-side from node coordinates. Client-submitted distance values are ignored.

### 5.2 Pathfinding — `shortest_path_via_cxx(start, end)`

1. Build a **subgraph** containing only:
   - The start and end nodes (always included)
   - All connector nodes matching pattern `c\d{2,3}`
   - Named locations are excluded as intermediates (they are only endpoints)
2. Run **Dijkstra's algorithm** on the subgraph: `nx.dijkstra_path(H, start, end, weight="weight")`
3. Return: `(node_list, segments, total_distance_meters)`

**Rationale**: Routes must follow actual campus walkways (represented by connector nodes), not arbitrary point-to-point lines.

### 5.3 GPS-Based Start Location

When the user provides GPS coordinates instead of selecting a start location:
1. Find the closest connector node (`c\d{2,3}`) to the user's lat/lon using Haversine
2. Temporarily add a `_user_location_` node to the graph at the user's coordinates
3. Add a temporary edge from `_user_location_` to the closest connector
4. Route from `_user_location_` to the selected end location
5. Rewrite the first segment label: "Your location → {connector} ({distance} m)"
6. Display the user's position as a green marker on the map

### 5.4 Graph Caching

```python
_GRAPH_CACHE = {
    "nodes_mtime": None,
    "edges_mtime": None,
    "graph": None,       # NetworkX Graph
    "nodes_df": None     # Pandas DataFrame
}
```

Cache invalidates when CSV file modification times change. Hot-reload: edit CSVs and the next request picks up changes automatically.

---

## 6. Data Validation

### 6.1 Node Cleaning (`clean_nodes_df()`)

- Strip whitespace from all string columns
- Coerce lat/lon to numeric, drop rows that fail conversion
- Drop rows with missing label, lat, or lon
- Validate lat bounds (-90 to 90) and lon bounds (-180 to 180)

### 6.2 Node Addition Validation

- Label must be non-empty
- Label must be unique (case-insensitive comparison)
- lat must be numeric and in range [-90, 90]
- lon must be numeric and in range [-180, 180]

### 6.3 Edge Addition Validation

- Both `from` and `to` must exist in nodes.csv
- `from` ≠ `to` (no self-loops)
- Edge must not already exist (bidirectional dedup)
- Distance is always server-computed (client value ignored)

---

## 7. File Locking

All CSV access uses advisory file locking via `fcntl.flock()`:

```python
@contextmanager
def locked_file(path, mode):
    # mode 'r' → shared lock (LOCK_SH)
    # mode 'w'/'a' → exclusive lock (LOCK_EX)
    # After write: fsync() to ensure persistence
```

- `nodes.csv`: shared lock on read (route finding, page load), exclusive lock on append (add node)
- `edges.csv`: shared lock on read, exclusive lock on append (add edge) or full rewrite (delete edge)

**Design constraint**: Single Gunicorn worker recommended to keep file locking simple.

---

## 8. API Endpoints

### 8.1 `GET /wayfinding/` — Route Finder Form

Returns HTML form with:
- Start location dropdown (all non-connector nodes, sorted)
- "Use my location" button (triggers `navigator.geolocation.getCurrentPosition` with `enableHighAccuracy: true`)
- End location dropdown
- Hidden fields: `user_lat`, `user_lon` (populated by geolocation JS)
- Privacy note: "GPS locations are not stored"
- Link to admin login

### 8.2 `POST /wayfinding/` — Compute Route

**Form data**:
```
start=College Hall          (optional if user_lat/user_lon provided)
end=Peter J. Fine Health Center  (required)
user_lat=38.9061618         (optional, triggers GPS mode)
user_lon=-76.9951292        (optional)
```

**Success response**: HTML page with:
- Route header: "Route: {start} ➜ {end}"
- Total distance in meters (bold)
- Bulleted segment list (e.g., "College Hall → c019 (24.9 m)")
- Interactive Folium map with route highlighted
- GPS tracking controls (start/stop buttons)

**Error responses**: Flash message + redirect to form:
- "No path found between {start} and {end}."
- Start and end "must be different"
- Missing required fields

### 8.3 `GET /wayfinding/api/path` — JSON Route API

**Query params**: `?start=College Hall&end=Peter J. Fine Health Center`

**200 response**:
```json
{
    "start": "College Hall",
    "end": "Peter J. Fine Health Center",
    "total_m": 673.5,
    "nodes": ["College Hall", "c019", "c015", ...],
    "segments": [
        {"text": "College Hall → c019 (24.9 m)", "m": 24.9},
        {"text": "c019 → c015 (17.4 m)", "m": 17.4}
    ]
}
```

**404 response**: `{"error": "no_path"}`

### 8.4 `GET/POST /wayfinding/admin_login` — Admin Authentication

**GET**: Login form with password field

**POST**: `{"password": "..."}` → checks against `WAYFINDING_ADMIN_PWHASH` using `check_password_hash()`
- Success: sets `session['is_admin'] = True`, redirects to `/wayfinding/add_node`
- Failure: flash error, re-display form
- If `WAYFINDING_ADMIN_PWHASH` not set: returns 403

### 8.5 `GET /wayfinding/logout`

Clears `session['is_admin']`, redirects to index with flash message.

### 8.6 `GET /wayfinding/add_node` — Admin Map Interface

**Requires**: `session['is_admin']` (403 otherwise)

Returns interactive Leaflet map with:
- All existing nodes as blue circle markers
- All existing edges as light blue polylines
- Click map → add node (popup with label input, default: next connector number e.g. "c108")
- Click node → start edge selection (turns orange) → click second node → shows distance + save/cancel
- Click edge → highlight orange → delete button with confirm dialog
- Status/error messages displayed in `#msg` div

### 8.7 `POST /wayfinding/api/add_node` — Add Node (Admin)

**Request JSON**: `{"label": "New Building", "lat": 38.9057, "lon": -76.9949}`

**200**: `{"label": "New Building", "lat": 38.9057, "lon": -76.9949}`
**400**: `{"error": "Invalid lat/lon" | "Missing label" | "Lat/lon out of bounds" | "Label already exists"}`

**Side effect**: Appends `[label, lat, lon, "ground"]` to nodes.csv with exclusive lock.

### 8.8 `POST /wayfinding/api/add_edge` — Add Edge (Admin)

**Request JSON**: `{"from": "College Hall", "to": "c019"}`

**200**: `{"result": "Edge saved (24.9 m)."}`
**400/404**: `{"error": "Invalid edge." | "Unknown node(s). Save nodes first." | "Edge already exists."}`

**Side effect**: Appends `[from, to, haversine_distance]` to edges.csv with exclusive lock.

### 8.9 `POST /wayfinding/api/delete_edge` — Delete Edge (Admin)

**Request JSON**: `{"from": "College Hall", "to": "c019"}`

**200**: `{"result": "Deleted"}`
**404**: `{"error": "Edge not found"}`

**Side effect**: Reads edges.csv, filters out matching row (bidirectional match), rewrites entire file with exclusive lock.

---

## 9. Frontend Templates

All templates are embedded as Python string constants in `app.py` and rendered via `render_template_string()`.

### 9.1 TEMPLATE_FORM (Route Finder)

**Layout**:
- Centered container (max-width 450px desktop, full-width mobile)
- White card with box shadow
- Responsive: smaller fonts and padding on mobile

**Components**:
1. H2: "Shortest walking route on campus"
2. Flash message area (styled red/orange)
3. Start location `<select>` with all named locations sorted alphabetically
4. "Or use my location" button — calls `navigator.geolocation.getCurrentPosition({enableHighAccuracy: true})`
5. Location status text (green when GPS acquired, red on error)
6. Small note: "GPS locations are not stored"
7. End location `<select>` (required)
8. "Find route" submit button (green, full-width)
9. Small "Admin" link to `/wayfinding/admin_login`

**GPS JavaScript behavior**:
- On success: populate hidden `user_lat`/`user_lon` fields, display coordinates, clear start dropdown
- On error: display error message in red

### 9.2 TEMPLATE_RESULT (Route Results)

**Components**:
1. H2: "Route: {start} ➜ {end}"
2. Bold total distance: "{total} m"
3. `<ul>` of segment strings (each with distance)
4. GPS tracking section:
   - "▶ Start tracking" button
   - "■ Stop" button (initially disabled)
   - Status `<span>` for GPS readout
5. Folium map HTML (inserted via `{{ map_html|safe }}`)
6. "⇠ New search" link

**GPS Tracking JavaScript**:
- Resolves Leaflet map context from Folium-generated iframe (polls up to 30 times at 150ms intervals)
- `navigator.geolocation.watchPosition()` for continuous updates
- Creates/updates green circle marker at user position
- Creates/updates semi-transparent accuracy circle around user
- Status shows: "GPS: {lat}, {lon} (±{accuracy} m)"
- Stop button: clears watch, removes markers

### 9.3 TEMPLATE_ADD_NODE (Admin Map)

**Layout**: Full-width Leaflet map (60vh height on mobile), status bar at top

**Map initialization**:
- Centered on first node, zoom level 19
- All nodes as blue `CircleMarker` (radius 6)
- All edges as light blue `PolyLine` (weight 2, opacity 0.5) with tooltip showing "{from} → {to}"

**Interaction modes**:

*Adding a node*:
1. Click empty map area → temporary marker at click point
2. Popup: lat/lon display, text input for label (default: next `c###` number), "Save Node" button
3. POST to `/wayfinding/api/add_node` → page reload on success (600ms delay)

*Adding an edge*:
1. Click first node marker → turns orange, status: "Start: {label}. Now select end node."
2. Click second node marker → turns orange, dashed blue preview line drawn
3. Status: "Edge: {from} → {to} = {distance} m" with Save/Cancel buttons
4. Save → POST to `/wayfinding/api/add_edge` → edge becomes permanent polyline
5. Cancel → clears selection

*Deleting an edge*:
1. Click existing edge polyline → highlights orange
2. Status: "Selected edge: {from} → {to}" with Delete button
3. Confirm via `window.confirm()` dialog
4. POST to `/wayfinding/api/delete_edge` → page reload on success (700ms delay)

**Client-side distance display**: Uses its own Haversine calculation for preview; server recomputes authoritatively on save.

### 9.4 TEMPLATE_ADMIN_LOGIN

- Centered white card with shadow
- "Admin Login" title
- Password input (`type="password"`, `autocomplete="current-password"`)
- "Unlock" submit button
- Flash message area
- "← Back" link to index

---

## 10. Map Rendering (`make_map()`)

**Input**: List of path node labels

**Process**:
1. Create `folium.Map` centered on mean of all node coordinates, zoom level 17, OpenStreetMap tiles
2. Draw all edges as light blue polylines (`#5ec7f8`, opacity 0.5, weight 2)
3. Draw all nodes as circle markers:
   - Default: blue, radius 5
   - Connector nodes not on path: **hidden** (not drawn)
   - Path nodes: red, radius 7
   - Start node: green, radius 8
   - End node: purple (`#7e57c2`), radius 8
   - `_user_location_` node: green marker labeled "Your location"
4. Draw path as red polyline (weight 5, opacity 0.9) on top of all other layers
5. Return HTML string via `m._repr_html_()`

**Output**: Self-contained HTML (~150–300 KB) with embedded Leaflet JS and tile references.

---

## 11. Security

### 11.1 Authentication
- Admin password hashed with Werkzeug `scrypt` method
- Hash stored in env var `WAYFINDING_ADMIN_PWHASH`
- Session cookie: `HttpOnly=True`, `SameSite=Lax`, secret key from `WAYFINDING_SECRET` (64-char hex)
- If `WAYFINDING_SECRET` not set, a random token is generated at startup (non-persistent across restarts)

### 11.2 Admin Route Protection
```python
def require_admin():
    if not ADMIN_PWHASH:
        return  # Dev mode: no password configured, allow all
    if session.get("is_admin"):
        return
    abort(403)
```

### 11.3 Input Sanitization
- All CSV writes use Pandas (handles quoting/escaping)
- Jinja2 auto-escaping on by default
- Map HTML uses `|safe` filter (controlled Folium output only)

### 11.4 Server-Side Authority
- Edge distances always computed server-side
- Client cannot inject arbitrary distance values

---

## 12. Deployment

### 12.1 WSGI Entry Point (`wsgi.py`)

```python
from app import app

if __name__ == "__main__":
    app.run()
```

### 12.2 Systemd Service (`wayfinding.service`)

```ini
[Unit]
Description=Wayfinding Flask web app with Gunicorn
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/wayfinding
Environment="PATH=/var/www/wayfinding/.venv/bin"
EnvironmentFile=/var/www/wayfinding/wayfinding.env
ExecStart=/var/www/wayfinding/.venv/bin/gunicorn wsgi:app \
    --bind 127.0.0.1:8000 \
    --workers 1 \
    --timeout 120
Restart=always
RestartSec=3
KillSignal=SIGQUIT
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

**Key choices**: Single worker (file locking simplicity), localhost-only binding (behind Nginx), 120s timeout.

### 12.3 Nginx Configuration (`nginx.conf`)

```nginx
location = /wayfinding {
    return 301 /wayfinding/;
}

location /wayfinding/ {
    proxy_pass         http://127.0.0.1:8000/wayfinding/;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_redirect     off;
}
```

This block is included inside the main Nginx `server {}` block.

### 12.4 Environment Setup (`create_wayfinding_env.sh`)

Interactive script that:
1. Prompts for admin password (no echo, confirms match)
2. Hashes with Werkzeug scrypt via Python one-liner
3. Generates 64-char hex random secret
4. Writes to temp file, moves atomically to `wayfinding.env`
5. Sets ownership root:www-data, permissions 0640

### 12.5 Restart Script (`restart.sh`)

```bash
#!/bin/sh
systemctl reload nginx
systemctl restart wayfinding
sleep 2
systemctl status wayfinding
```

---

## 13. Setup Procedure (from scratch)

```bash
# 1. Clone repo
git clone <repo> /var/www/wayfinding
cd /var/www/wayfinding

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate environment file (interactive password prompt)
./create_wayfinding_env.sh

# 5. Install systemd service
sudo cp wayfinding.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wayfinding

# 6. Add nginx.conf content to your Nginx server block
# Then: sudo systemctl reload nginx

# 7. Start
sudo systemctl start wayfinding
```

---

## 14. Utility Scripts

### `wayfinding.py` — CLI Route Finder
Interactive terminal tool: lists locations by number, user selects start/end, prints route segments + total distance, generates `map.html`.

### `plot_graph.py` — Static Graph Visualization
Builds NetworkX graph from CSVs, renders with matplotlib using (lon, lat) positions, saves `campus_graph.png` (16x12", 200 DPI). Node colors by level, edge labels showing distances.

### `plot_map.py` — Static Campus Map
Loads nodes.csv, creates Folium map centered on mean coordinates, adds standard markers for each node, saves `gallaudet_map.html`.

### `get_gps_coordinates_openstreetmap.py` — Geocoding
Uses `geopy.geocoders.Nominatim` to fetch GPS coordinates from OpenStreetMap. 1-second delay between requests. Outputs `nodes_auto.csv`.

### `cat_ai_files.sh` — Codebase Dump
Recursively scans directory for code files (.py, .conf, .csv, .sh, .css, .service, .json), excluding .venv/node_modules/__pycache__, prints contents to stdout for LLM context.

---

## 15. Requirements (`requirements.txt`)

```
blinker==1.9.0
branca==0.8.1
certifi==2025.1.31
charset-normalizer==3.4.2
click==8.1.8
Flask==3.1.1
folium==0.20.0
gunicorn==23.0.0
idna==3.10
itsdangerous==2.2.0
Jinja2==3.1.6
MarkupSafe==3.0.2
networkx==3.4.2
numpy==2.2.6
packaging==25.0
pandas==2.3.1
python-dateutil==2.9.0.post0
pytz==2025.2
requests==2.32.3
six==1.17.0
tzdata==2025.2
urllib3==2.4.0
Werkzeug==3.1.3
xyzservices==2025.4.0
```

---

## 16. Known Limitations & Design Decisions

| Decision | Rationale |
|----------|-----------|
| CSV storage (not database) | Simple, human-editable, sufficient for campus-scale data |
| Single Gunicorn worker | File locking simplicity; <10 concurrent users expected |
| Connector-based routing | Ensures routes follow actual walkways, not arbitrary lines |
| All templates in app.py | Single-file deployment, no template directory needed |
| `level` column unused | Future-proofing for multi-floor routing |
| No user accounts | Privacy-first: no route history, no GPS storage |
| No HTTPS enforcement | Depends on Nginx/infrastructure config; `SESSION_COOKIE_SECURE=False` |

---

## 17. Key Behavioral Details for Rebuilding

1. **Named locations are never used as intermediates** in routing — only as start/end points. All intermediate hops go through connector nodes.
2. **The `_user_location_` node is ephemeral** — added to the graph copy for GPS routing, never persisted to CSV.
3. **Edge deletion rewrites the entire edges.csv** (read all → filter → write all) under exclusive lock.
4. **Graph cache checks file mtimes** on every request — editing CSVs triggers automatic reload with zero downtime.
5. **The admin add_node page auto-suggests the next connector label** by finding the max existing `c###` number and incrementing.
6. **Flash messages** use Flask's `flash()` and are displayed once then cleared (standard Flask session-based flashing).
7. **All admin API endpoints return JSON**; all user-facing endpoints return HTML.
8. **The Folium map is rendered server-side** as an HTML string and embedded in the template with `|safe`. It is not an iframe — it's inline HTML/JS.
9. **CSS is inline** in each template (no external stylesheet).
10. **No JavaScript frameworks** — all frontend code is vanilla JS embedded in templates.
