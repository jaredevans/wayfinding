# Gallaudet Campus Wayfinding — iOS Conversion Specification

> **Purpose**: Split the monolithic Flask web application into an Ubuntu server backend (REST API) and a native iOS frontend app. This document specifies each component's responsibilities, the API contract between them, and what changes from the current architecture.

---

## 1. Architecture Overview

```
┌──────────────────────┐         HTTPS/JSON         ┌──────────────────────┐
│                      │  ◄──────────────────────►   │                      │
│     iOS App          │                             │   Ubuntu Server      │
│  (Swift / SwiftUI)   │                             │  (Flask REST API)    │
│                      │                             │                      │
│  • MapKit maps       │                             │  • Pathfinding       │
│  • CoreLocation GPS  │                             │  • Graph management  │
│  • Native UI         │                             │  • Data storage      │
│  • Route rendering   │                             │  • Admin auth        │
│                      │                             │  • CSV / file I/O    │
└──────────────────────┘                             └──────────────────────┘
```

**Key change**: The server no longer renders HTML, maps, or templates. It becomes a pure JSON API. All UI, map rendering, and GPS handling move to the iOS app.

---

## 2. Ubuntu Server — Backend

### 2.1 Responsibilities

- Pathfinding (Dijkstra via NetworkX)
- Graph data storage (nodes.csv, edges.csv)
- Haversine distance computation (server-authoritative)
- Data validation (node/edge constraints)
- File locking (fcntl advisory locks)
- Graph caching with mtime invalidation
- Admin authentication (session-based or token-based)
- All CRUD operations on nodes and edges

### 2.2 Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Framework | Flask 3.1.1 | JSON-only responses |
| Pathfinding | NetworkX 3.4.2 | Unchanged |
| Data | Pandas 2.3.1 | Unchanged |
| Auth | Werkzeug scrypt | Unchanged hashing; consider JWT for mobile |
| WSGI | Gunicorn 23.0.0 | Unchanged |
| Proxy | Nginx | Add CORS headers, enforce HTTPS |

**Removed from server**: Folium, Jinja2 template rendering, all HTML/CSS/JS generation.

### 2.3 API Endpoints

All endpoints return JSON. The `/wayfinding/` prefix is retained for reverse proxy compatibility.

#### 2.3.1 `GET /wayfinding/api/locations` — List Named Locations (NEW)

Returns all non-connector nodes for populating the iOS app's location picker.

**Response 200**:
```json
{
    "locations": [
        {"label": "Chapel Hall", "lat": 38.9078, "lon": -76.9932},
        {"label": "College Hall", "lat": 38.9065, "lon": -76.9945}
    ]
}
```

Sorted alphabetically by label. Connector nodes (`c\d{2,3}`) are excluded.

#### 2.3.2 `GET /wayfinding/api/path` — Compute Route (MODIFIED)

**Query params**: `?start=College Hall&end=Chapel Hall`

For GPS-based start: `?user_lat=38.9061&user_lon=-76.9951&end=Chapel Hall`

**Response 200**:
```json
{
    "start": "College Hall",
    "end": "Chapel Hall",
    "total_m": 673.5,
    "nodes": ["College Hall", "c019", "c015", "Chapel Hall"],
    "segments": [
        {"from": "College Hall", "to": "c019", "m": 24.9},
        {"from": "c019", "to": "c015", "m": 17.4},
        {"from": "c015", "to": "Chapel Hall", "m": 31.2}
    ],
    "coordinates": [
        {"label": "College Hall", "lat": 38.9065, "lon": -76.9945},
        {"label": "c019", "lat": 38.9063, "lon": -76.9942},
        {"label": "c015", "lat": 38.9060, "lon": -76.9938},
        {"label": "Chapel Hall", "lat": 38.9078, "lon": -76.9932}
    ]
}
```

**New field**: `coordinates` — ordered lat/lon for each node in the path, so the iOS app can draw the route polyline on MapKit without a separate lookup.

**Response 400**: `{"error": "Start and end must be different"}`
**Response 404**: `{"error": "No path found between College Hall and Chapel Hall"}`

#### 2.3.3 `GET /wayfinding/api/graph` — Full Graph Data (NEW)

Returns all nodes and edges for the admin map editor in the iOS app.

**Requires**: Admin authentication

**Response 200**:
```json
{
    "nodes": [
        {"label": "College Hall", "lat": 38.9065, "lon": -76.9945, "level": "ground"},
        {"label": "c019", "lat": 38.9063, "lon": -76.9942, "level": "ground"}
    ],
    "edges": [
        {"from": "College Hall", "to": "c019", "distance": 24.9},
        {"from": "c019", "to": "c015", "distance": 17.4}
    ]
}
```

#### 2.3.4 `POST /wayfinding/api/admin_login` — Admin Authentication (MODIFIED)

**Request JSON**: `{"password": "secretpass"}`

**Response 200**: `{"token": "<session_token>", "expires": "2026-03-12T00:00:00Z"}`
**Response 401**: `{"error": "Invalid password"}`
**Response 403**: `{"error": "Admin login not configured"}`

**Options for mobile auth**:
- **Option A (Simple)**: Return Flask session cookie — iOS stores in `URLSession` cookie jar automatically.
- **Option B (Recommended)**: Return a JWT or opaque token in the response body. iOS passes it as `Authorization: Bearer <token>` on subsequent admin requests. This avoids cookie management on mobile.

#### 2.3.5 `POST /wayfinding/api/add_node` — Add Node (UNCHANGED)

**Request JSON**: `{"label": "New Building", "lat": 38.9057, "lon": -76.9949}`

**Headers**: `Authorization: Bearer <token>` (admin required)

**Response 200**: `{"label": "New Building", "lat": 38.9057, "lon": -76.9949}`
**Response 400**: `{"error": "Label already exists"}` (and other validation errors)
**Response 401/403**: Unauthorized

#### 2.3.6 `POST /wayfinding/api/add_edge` — Add Edge (UNCHANGED)

**Request JSON**: `{"from": "College Hall", "to": "c019"}`

**Headers**: `Authorization: Bearer <token>` (admin required)

**Response 200**: `{"result": "Edge saved (24.9 m)."}`
**Response 400/404**: Validation errors

#### 2.3.7 `POST /wayfinding/api/delete_edge` — Delete Edge (UNCHANGED)

**Request JSON**: `{"from": "College Hall", "to": "c019"}`

**Headers**: `Authorization: Bearer <token>` (admin required)

**Response 200**: `{"result": "Deleted"}`
**Response 404**: `{"error": "Edge not found"}`

#### 2.3.8 `GET /wayfinding/api/next_connector` — Next Connector Label (NEW)

Returns the next auto-increment connector label for admin use.

**Requires**: Admin authentication

**Response 200**: `{"label": "c108"}`

### 2.4 CORS Configuration

The server must allow requests from the iOS app. Add to Flask:

```python
from flask_cors import CORS

CORS(app, resources={r"/wayfinding/api/*": {
    "origins": "*",           # iOS apps send Origin header as nil
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})
```

### 2.5 Nginx Changes

Add HTTPS enforcement (required for iOS App Transport Security):

```nginx
location /wayfinding/ {
    proxy_pass         http://127.0.0.1:8000/wayfinding/;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_redirect     off;

    # CORS headers for iOS
    add_header Access-Control-Allow-Origin "*" always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Content-Type, Authorization" always;

    if ($request_method = OPTIONS) {
        return 204;
    }
}
```

HTTPS is mandatory — iOS blocks plain HTTP by default (App Transport Security).

### 2.6 What Gets Removed from Server

| Component | Reason |
|-----------|--------|
| Folium / map rendering | Maps rendered natively on iOS via MapKit |
| `TEMPLATE_FORM` | iOS app replaces the route finder form |
| `TEMPLATE_RESULT` | iOS app renders route results natively |
| `TEMPLATE_ADD_NODE` | iOS app provides admin map editor |
| `TEMPLATE_ADMIN_LOGIN` | iOS app provides login screen |
| `render_template_string()` calls | No HTML rendering needed |
| `make_map()` function | Map logic moves to iOS |
| Flash messages | iOS uses native alerts/banners |
| `GET/POST /wayfinding/` HTML routes | Replaced by API-only endpoints |

### 2.7 What Stays on Server (Unchanged)

- `haversine_m()` — server-authoritative distance computation
- `shortest_path_via_cxx()` — Dijkstra pathfinding
- `load_graph()` — graph caching with mtime checks
- `clean_nodes_df()` — data validation
- `locked_file()` — file locking context manager
- `require_admin()` — admin check (adapted for token auth)
- CSV storage model (nodes.csv, edges.csv)
- Systemd service and Gunicorn deployment
- `wayfinding.env` for secrets

---

## 3. iOS App — Frontend

### 3.1 Responsibilities

- All user interface and navigation
- Map rendering (MapKit with OpenStreetMap or Apple Maps tiles)
- GPS location services (CoreLocation)
- Live GPS tracking during walk
- Route polyline rendering on map
- Location picker (search/select)
- Admin map editor (add nodes, add/delete edges)
- Admin login screen
- Network requests to backend API

### 3.2 Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Language | Swift 5.9+ | — |
| UI | SwiftUI | With UIKit interop where needed |
| Maps | MapKit | Apple Maps tiles, native annotations |
| Location | CoreLocation | GPS, permissions, continuous tracking |
| Networking | URLSession | Native HTTP client, JSON Codable |
| Min target | iOS 17.0+ | For latest MapKit SwiftUI APIs |

### 3.3 App Screens

#### 3.3.1 Route Finder (Main Screen)

**Replaces**: `TEMPLATE_FORM`

**Layout**:
- Navigation title: "Gallaudet Wayfinding"
- Start location picker (searchable list from `/api/locations`)
- "Use My Location" button — triggers CoreLocation permission + `CLLocationManager.requestLocation()`
- When GPS acquired: display coordinates, gray out start picker
- End location picker (required)
- "Find Route" button

**Behavior**:
- On launch, fetch locations from `/api/locations` and cache locally
- On "Find Route": call `/api/path` with selected start/end (or user_lat/user_lon)
- On success: navigate to Route Result screen
- On error: show native `Alert` with error message

#### 3.3.2 Route Result

**Replaces**: `TEMPLATE_RESULT` + `make_map()`

**Layout**:
- Header: "Route: {start} → {end}"
- Total distance (bold)
- Scrollable segment list with distances
- MapKit map view showing:
  - Route polyline (red, from `coordinates` array)
  - Start pin (green)
  - End pin (purple)
  - Named intermediate stops labeled
- "Start Tracking" button
- "New Search" button (pops back)

**Map rendering** (replaces Folium):
```swift
Map {
    // Route polyline from coordinates array
    MapPolyline(coordinates: routeCoordinates)
        .stroke(.red, lineWidth: 5)

    // Start marker
    Annotation("Start", coordinate: startCoord) {
        Circle().fill(.green).frame(width: 16, height: 16)
    }

    // End marker
    Annotation("End", coordinate: endCoord) {
        Circle().fill(.purple).frame(width: 16, height: 16)
    }

    // User location (if GPS mode)
    UserAnnotation()
}
.mapStyle(.standard)
```

#### 3.3.3 GPS Tracking (overlay on Route Result)

**Replaces**: GPS tracking JavaScript in `TEMPLATE_RESULT`

**Behavior**:
- "Start Tracking": begin `CLLocationManager.startUpdatingLocation()`
- Update user's position annotation on map in real-time
- Show accuracy circle (semi-transparent) around user dot
- Display status: "GPS: {lat}, {lon} (±{accuracy} m)"
- "Stop Tracking": call `stopUpdatingLocation()`, remove tracking UI
- Auto-center map on user position (with option to disable)

**CoreLocation setup**:
```swift
let manager = CLLocationManager()
manager.desiredAccuracy = kCLLocationAccuracyBest
manager.requestWhenInUseAuthorization()
// Info.plist: NSLocationWhenInUseUsageDescription =
//   "Used to show your position on the campus map and calculate walking routes."
```

#### 3.3.4 Admin Login

**Replaces**: `TEMPLATE_ADMIN_LOGIN`

**Layout**:
- "Admin Login" title
- SecureField for password
- "Unlock" button
- Error message display

**Behavior**:
- POST to `/api/admin_login` with password
- On success: store token in Keychain, navigate to Admin Map
- On failure: show error alert

#### 3.3.5 Admin Map Editor

**Replaces**: `TEMPLATE_ADD_NODE`

**Layout**:
- Full-screen MapKit map
- All nodes as circle annotations (blue)
- All edges as polylines (light blue)
- Floating status bar at top
- Toolbar at bottom with mode selector (Add Node / Add Edge / Delete Edge)

**Behavior**:

*Adding a node*:
1. Long-press on map → drop pin at coordinate
2. Sheet slides up: lat/lon display, text field for label (default: next connector from `/api/next_connector`), "Save" button
3. POST to `/api/add_node` → add annotation to map on success

*Adding an edge*:
1. Tap first node → highlight orange, status: "Select end node"
2. Tap second node → highlight orange, show preview dashed line + distance
3. Distance computed client-side (Haversine) for preview; server recomputes on save
4. "Save Edge" button → POST to `/api/add_edge` → draw permanent polyline
5. "Cancel" button → clear selection

*Deleting an edge*:
1. Tap edge polyline → highlight orange
2. Status: "Delete edge: {from} → {to}?"
3. Confirmation alert → POST to `/api/delete_edge` → remove polyline

**Data loading**: Fetch full graph from `/api/graph` on screen appear.

### 3.4 Data Models (Swift)

```swift
struct Location: Codable, Identifiable {
    let label: String
    let lat: Double
    let lon: Double
    var id: String { label }
}

struct PathSegment: Codable {
    let from: String
    let to: String
    let m: Double
}

struct RouteResponse: Codable {
    let start: String
    let end: String
    let totalM: Double
    let nodes: [String]
    let segments: [PathSegment]
    let coordinates: [Location]

    enum CodingKeys: String, CodingKey {
        case start, end, nodes, segments, coordinates
        case totalM = "total_m"
    }
}

struct GraphResponse: Codable {
    let nodes: [NodeData]
    let edges: [EdgeData]
}

struct NodeData: Codable {
    let label: String
    let lat: Double
    let lon: Double
    let level: String
}

struct EdgeData: Codable {
    let from: String
    let to: String
    let distance: Double
}
```

### 3.5 Networking Layer

```swift
class WayfindingAPI {
    let baseURL: URL  // e.g. https://yourserver.edu/wayfinding/api

    func getLocations() async throws -> [Location]
    func getPath(start: String?, end: String,
                 userLat: Double?, userLon: Double?) async throws -> RouteResponse
    func getGraph(token: String) async throws -> GraphResponse
    func login(password: String) async throws -> String  // returns token
    func addNode(label: String, lat: Double, lon: Double,
                 token: String) async throws -> Location
    func addEdge(from: String, to: String,
                 token: String) async throws -> String
    func deleteEdge(from: String, to: String,
                    token: String) async throws -> String
    func getNextConnector(token: String) async throws -> String
}
```

### 3.6 Info.plist Requirements

| Key | Value |
|-----|-------|
| `NSLocationWhenInUseUsageDescription` | "Used to show your position on the campus map and calculate walking routes." |
| `NSAppTransportSecurity` | Not needed if server uses HTTPS (default allows HTTPS) |

### 3.7 Accessibility

- All buttons and controls labeled for VoiceOver
- Route segments readable as list items
- Map annotations with accessibility labels
- Dynamic Type support for all text

---

## 4. Migration Checklist

### 4.1 Server Changes

- [ ] Remove Folium dependency and `make_map()` function
- [ ] Remove all `TEMPLATE_*` string constants
- [ ] Remove `render_template_string()` calls
- [ ] Remove `GET/POST /wayfinding/` HTML routes
- [ ] Convert `GET/POST /wayfinding/admin_login` to JSON endpoint
- [ ] Add `GET /wayfinding/api/locations` endpoint
- [ ] Add `GET /wayfinding/api/graph` endpoint (admin-only)
- [ ] Add `GET /wayfinding/api/next_connector` endpoint (admin-only)
- [ ] Modify `GET /wayfinding/api/path` to include `coordinates` array
- [ ] Implement token-based auth (JWT or opaque tokens)
- [ ] Add CORS support (flask-cors)
- [ ] Configure HTTPS via Nginx + Let's Encrypt
- [ ] Update `requirements.txt` (add flask-cors, PyJWT; remove folium, branca, xyzservices)
- [ ] Update Nginx config for CORS headers

### 4.2 iOS App Development

- [ ] Create Xcode project (SwiftUI, iOS 17+)
- [ ] Implement `WayfindingAPI` networking layer
- [ ] Build Route Finder screen (location pickers + GPS button)
- [ ] Build Route Result screen (segment list + MapKit route)
- [ ] Implement GPS tracking (CoreLocation continuous updates)
- [ ] Build Admin Login screen
- [ ] Build Admin Map Editor (node/edge CRUD on MapKit)
- [ ] Store admin token in Keychain
- [ ] Cache location list for offline picker
- [ ] Add VoiceOver accessibility labels
- [ ] Configure App Transport Security (HTTPS)
- [ ] Test on physical device (GPS requires real hardware)

### 4.3 Preserved Behaviors

These must work identically after conversion:

| Behavior | Implementation |
|----------|---------------|
| Named locations never used as intermediates | Server pathfinding logic unchanged |
| `_user_location_` node is ephemeral | Server creates/destroys per request |
| Edge distances are server-authoritative | iOS preview is cosmetic; server recomputes |
| File locking on CSV access | Server unchanged |
| Graph cache invalidates on CSV mtime change | Server unchanged |
| Next connector label auto-increments | Server computes, iOS fetches |
| No GPS data stored | iOS sends coords per-request; server discards after routing |
| Admin password hashed with scrypt | Server unchanged |

---

## 5. What Each Side Owns

| Concern | Current (Monolith) | Server (After) | iOS App (After) |
|---------|-------------------|----------------|-----------------|
| Pathfinding algorithm | Server | **Server** | — |
| Distance computation | Server | **Server** | Preview only |
| Data validation | Server | **Server** | — |
| Data storage (CSV) | Server | **Server** | — |
| File locking | Server | **Server** | — |
| Admin authentication | Server (session) | **Server** (token) | Token storage |
| Map rendering | Server (Folium) | — | **iOS** (MapKit) |
| GPS acquisition | Browser JS | — | **iOS** (CoreLocation) |
| Live GPS tracking | Browser JS | — | **iOS** (CoreLocation) |
| Route polyline drawing | Server (Folium) | — | **iOS** (MapKit) |
| UI / forms / styling | Server (HTML/CSS/JS) | — | **iOS** (SwiftUI) |
| Location picker | Server (HTML select) | — | **iOS** (SwiftUI List) |
| Error display | Server (flash) | JSON errors | **iOS** (Alert) |
| Haversine (preview) | Server + client JS | **Server** (authoritative) | **iOS** (preview) |
