# Gallaudet Campus Wayfinding (Flask)

A web-based wayfinding application for the University campus.  
It calculates the shortest walking route between two locations using a constrained graph (connector nodes), displays it on an interactive map, and includes an admin UI for managing map data.

Routing is computed with **NetworkX** and rendered with **Folium/Leaflet**.  
Node and edge data are stored in `nodes.csv` and `edges.csv` with **safe file-locking** to prevent corruption when accessed by multiple workers.

---

## What's New in This Version

- **Server-side authoritative edge distances**  
  Distances for new edges are computed on the **server** from node coordinates (client-sent distances are ignored).
- **Improved GPS Start Point**  
  `"Use my location"` now rewrites the first segment instead of duplicating the start step.
- **Admin Authentication**  
  Admin access now requires password login:
  - Password hash in env var: `WAYFINDING_ADMIN_PWHASH`
  - Session flag `session['is_admin'] = True` set after login.
- **Secure Secret Key**  
  Pulled from `WAYFINDING_SECRET` or randomized at app startup.
- **CSV File Locking**  
  Advisory file locks to prevent race conditions when multiple workers read/write.
- **Enhanced Map Rendering**  
  `make_map()` accepts an explicit graph and highlights start/end nodes.
- **Live GPS Tracking**  
  Users can start/stop real-time GPS tracking while viewing a route.
- **Edge Deletion from Map**  
  Admins can click an edge to highlight and delete it directly.
- **JSON Path API**  
  `/wayfinding/api/path?start=...&end=...` returns structured route data for automation/mobile use.

---

## Features

### **User-Facing**
- **Route Finder**
  - Select start and end locations.
  - Or use browser GPS for "Use my location".
  - Real-time GPS tracking (optional) while viewing a route.
- **Connector-Based Routing**
  - All routes go through `cXX`/`cXXX` connector nodes for realistic walkway paths.
- **Interactive Map**
  - Shows full campus paths, highlights your route in red.
  - Start node (green), end node (purple), path nodes (red).
- **Privacy**
  - Location is never stored; only used for the current session.

### **Admin Interface**
Accessible via `/wayfinding/admin_login` → `/wayfinding/add_node` (after password login).

- **Add Nodes**
  - Click anywhere on the map, assign a label, save to `nodes.csv`.
  - Auto-suggests the next available connector label (`c###`).
- **Add Edges**
  - Click two existing nodes; server computes the distance automatically.
  - Saves to `edges.csv` after deduplication.
- **Delete Edges**
  - Click an edge to highlight, then delete it in one step.

---

## Repository Layout

```
.
├── app.py                      # Main Flask app (with GPS tracking, admin auth, APIs)
├── wsgi.py                     # Gunicorn entrypoint
├── nodes.csv                   # Node list (label, lat, lon, level)
├── edges.csv                   # Edge list (from, to, distance meters)
├── wayfinding.py                # CLI tool for route finding + map output
├── plot_graph.py               # Static PNG plot of campus graph
├── plot_map.py                 # Interactive HTML map of all nodes
├── get_gps_coordinates_openstreetmap.py  # Fetch GPS coords from OSM
├── create_wayfinding_env.sh    # Generate secure env file (hash + secret)
├── wayfinding.service          # systemd unit for Gunicorn service
├── nginx.conf                  # Nginx reverse proxy for /wayfinding/
├── restart.sh                  # Reload nginx + restart wayfinding service
├── source_activate_venv.sh     # Activate local virtual environment
```

---

## Data Files

- **`nodes.csv`**
- 
  ```
  label,lat,lon,level
  c000,38.9057,-76.9948,ground
  College Hall,38.9061,-76.9951,ground
  ...
  ```
  
- **`edges.csv`**
- 
  ```
  from,to,distance
  c001,c002,32.5
  Gate House,c002,20.5
  ...
  ```
  
---

## Deployment

### **Environment Variables**
Generated via:
```bash
./create_wayfinding_env.sh
```

Creates `/var/www/wayfinding/wayfinding.env`:

```
WAYFINDING_ADMIN_PWHASH=<scrypt hash>
WAYFINDING_SECRET=<64-char random hex>
```

### **Systemd Service**
`/etc/systemd/system/wayfinding.service`:

```
WorkingDirectory=/var/www/wayfinding
Environment="PATH=/var/www/wayfinding/.venv/bin"
EnvironmentFile=/var/www/wayfinding/wayfinding.env
ExecStart=/var/www/wayfinding/.venv/bin/gunicorn wsgi:app --bind 127.0.0.1:8000 --workers 1 --timeout 120
```

### **Nginx Reverse Proxy**
`/etc/nginx/sites-enabled/wayfinding.conf`:

```
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

---

## Command-Line Tools

### **`wayfinding.py`**
- Interactive CLI to select start/end points.
- Outputs step-by-step route and total distance.
- Generates `map.html` showing route.

### **`plot_graph.py`**
- Generates static `campus_graph.png` of all nodes and edges.

### **`plot_map.py`**
- Creates `gallaudet_map.html` with all node markers.

### **`get_gps_coordinates_openstreetmap.py`**
- Batch fetches lat/lon for building names using OpenStreetMap Nominatim.

---

## Tech Stack
- **Python**: Flask, Pandas, NetworkX, Folium
- **Frontend**: HTML, JavaScript, Leaflet.js
- **Deployment**: Gunicorn, systemd, Nginx
- **Data Storage**: CSV with advisory file locks

---

## Screenshots

**Mobile Route:**

<img src="https://i.imgur.com/p4VaqLd.png" width=500 height=800>

**Mobile Route with GPS Start:**

<img src="https://i.imgur.com/VJ1Rvdf.jpeg" width=500 height=800>

<img src="https://i.imgur.com/sBBe2DZ.jpeg" width=500 height=600>

**Admin Add Node/Edge:**

<img src="https://i.imgur.com/IdAFhrV.png" width=700 height=600>
