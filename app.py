#!/var/www/wayfinding/.venv/bin/python
"""
Flask way-finding demo for Gallaudet campus, with robust admin add-node and add-edge feature.

Improvements in this version:
- Distances for new edges are computed on the SERVER from node coords (ignore client-sent values).
- "Use my location" no longer duplicates the first step; we rewrite the first segment label.
- Admin protection via password login only:
    * Hash in env var WAYFINDING_ADMIN_PWHASH; login sets session['is_admin']=True
- Secret key pulled from env (WAYFINDING_SECRET) or randomized at boot.
- Basic file-locking for CSV read/write to avoid corruption with multiple workers.
- make_map accepts an explicit graph and highlights start/end nodes.
"""

import os
import csv
import math
import re
import secrets
from contextlib import contextmanager

import fcntl
import pandas as pd
import networkx as nx
import folium
from werkzeug.security import check_password_hash
from flask import (
    Flask, render_template_string, request, redirect, url_for, flash,
    jsonify, abort, session
)

# --------------------------------------------------------------------
# Config / paths
# --------------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
NODES_CSV = os.path.join(BASE_DIR, "nodes.csv")
EDGES_CSV = os.path.join(BASE_DIR, "edges.csv")

ADMIN_PWHASH = os.environ.get("WAYFINDING_ADMIN_PWHASH")        # Hashed password for admin login
SECRET = os.environ.get("WAYFINDING_SECRET") or secrets.token_hex(32)

# --------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------
@contextmanager
def locked_file(path: str, mode: str):
    """
    Open a file and acquire an advisory lock for the duration of the context.
    Shared lock for reads ('r'), exclusive for writes/appends ('w','a').
    """
    f = open(path, mode, newline="")
    try:
        lock_mode = fcntl.LOCK_SH
        if "w" in mode or "a" in mode or "+" in mode:
            lock_mode = fcntl.LOCK_EX
        fcntl.flock(f.fileno(), lock_mode)
        yield f
    finally:
        try:
            if "w" in mode or "a" in mode or "+" in mode:
                f.flush()
                os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()


def require_admin():
    """
    Allow admin access if session['is_admin'] is True (after password login).
    If ADMIN_PWHASH is NOT configured, admin routes remain open (dev mode).
    """
    if not ADMIN_PWHASH:
        return
    if session.get("is_admin"):
        return
    abort(403)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in meters."""
    R = 6371000.0
    from math import radians, sin, cos, asin, sqrt
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * R * asin(sqrt(a))


def clean_nodes_df(df: pd.DataFrame) -> pd.DataFrame:
    """Trim strings, coerce lat/lon to numeric, drop invalid rows."""
    for col in df.select_dtypes(include="object"):
        df[col] = df[col].astype(str).str.strip()
    # Coerce lat/lon to numeric and drop NaNs
    df["lat"] = pd.to_numeric(df.get("lat"), errors="coerce")
    df["lon"] = pd.to_numeric(df.get("lon"), errors="coerce")
    df = df.dropna(subset=["label", "lat", "lon"])
    return df


# --------------------------------------------------------------------
# Graph loading with light caching
# --------------------------------------------------------------------
_GRAPH_CACHE = {"nodes_mtime": None, "edges_mtime": None, "graph": None, "nodes_df": None}


def load_graph(force: bool = False):
    """Build (or reuse) the NetworkX graph from CSVs."""
    nodes_mtime = os.path.getmtime(NODES_CSV) if os.path.exists(NODES_CSV) else 0
    edges_mtime = os.path.getmtime(EDGES_CSV) if os.path.exists(EDGES_CSV) else 0

    cache = _GRAPH_CACHE
    if (
        not force
        and cache["graph"] is not None
        and cache["nodes_mtime"] == nodes_mtime
        and cache["edges_mtime"] == edges_mtime
    ):
        return cache["graph"], cache["nodes_df"]

    with locked_file(NODES_CSV, "r") as nf:
        nodes_df = clean_nodes_df(pd.read_csv(nf))
    with locked_file(EDGES_CSV, "r") as ef:
        edges_df = pd.read_csv(ef)

    G = nx.Graph()

    # Nodes
    for _, row in nodes_df.iterrows():
        try:
            label = str(row["label"]).strip()
            lat = float(row["lat"])
            lon = float(row["lon"])
            level = str(row.get("level", "ground")).strip().lower()
        except Exception as e:
            print(f"[WARN] Skipping node due to bad data: {e}")
            continue
        G.add_node(label, lat=lat, lon=lon, level=level)

    # Edges
    for _, row in edges_df.iterrows():
        try:
            f = str(row["from"]).strip()
            t = str(row["to"]).strip()
            w = float(row["distance"])
            if f in G.nodes and t in G.nodes:
                G.add_edge(f, t, weight=w)
        except Exception as e:
            print(f"[WARN] Bad edge: {e}")
            continue

    cache.update(
        {"graph": G, "nodes_df": nodes_df, "nodes_mtime": nodes_mtime, "edges_mtime": edges_mtime}
    )
    return G, nodes_df


# Global convenience (updated per request in index)
G, nodes_df = load_graph(force=True)


# --------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------
def shortest_path_via_cxx(start: str, end: str, graph=None):
    """Route from start to end using only cXX/cXXX intermediates (start/end always allowed)."""
    g = graph if graph is not None else G

    def is_cxx(n: str) -> bool:
        return bool(re.fullmatch(r"c\d{2,3}", str(n)))

    allowed = {start, end}
    allowed.update([n for n in g.nodes if is_cxx(n)])
    H = g.subgraph(allowed).copy()

    try:
        nodes = nx.dijkstra_path(H, start, end, weight="weight")
    except nx.NetworkXNoPath:
        return None, [], 0.0

    steps = []
    total = 0.0
    for a, b in zip(nodes[:-1], nodes[1:]):
        d = g[a][b]["weight"]
        total += d
        steps.append((f"{a} → {b} ({d:.1f} m)", d))
    return nodes, steps, total


def make_map(path_nodes, graph=None):
    """Render a folium map with background edges and an emphasized path."""
    g = graph if graph is not None else G

    lats = [g.nodes[n]["lat"] for n in g.nodes if "lat" in g.nodes[n]]
    lons = [g.nodes[n]["lon"] for n in g.nodes if "lon" in g.nodes[n]]
    if not lats or not lons:
        m = folium.Map(location=[0, 0], zoom_start=2)
    else:
        m = folium.Map(location=[sum(lats) / len(lats), sum(lons) / len(lons)], zoom_start=17, tiles="OpenStreetMap")

    path_set = set(path_nodes or [])
    start_node = path_nodes[0] if path_nodes else None
    end_node = path_nodes[-1] if path_nodes else None

    # Draw all edges lightly
    for u, v in g.edges:
        if "lat" not in g.nodes[u] or "lon" not in g.nodes[u]:
            continue
        if "lat" not in g.nodes[v] or "lon" not in g.nodes[v]:
            continue
        folium.PolyLine(
            [(g.nodes[u]["lat"], g.nodes[u]["lon"]), (g.nodes[v]["lat"], g.nodes[v]["lon"])],
            color="#5ec7f8",
            weight=2,
            opacity=0.5,
            tooltip=f"{u} \u2192 {v}",
        ).add_to(m)

    # Draw nodes: hide cXX nodes unless on the path; special colors for start/end
    for n in g.nodes:
        attrs = g.nodes[n]
        if "lat" not in attrs or "lon" not in attrs:
            continue
        if re.fullmatch(r"c\d{2,3}", str(n)) and (not path_nodes or n not in path_set):
            continue

        # Special case: user location node
        if n == "_user_location_":
            folium.CircleMarker(
                location=[attrs["lat"], attrs["lon"]],
                radius=8,
                popup="Your Location",
                color="green",
                fill=True,
                fill_opacity=1,
            ).add_to(m)
            continue

        color = "blue"
        if path_nodes and n in path_set:
            color = "red"
        if start_node and n == start_node:
            color = "green"
        if end_node and n == end_node:
            color = "#7e57c2"  # purple-ish

        folium.CircleMarker(
            location=[attrs["lat"], attrs["lon"]],
            radius=4,
            popup=str(n),
            color=color,
            fill=True,
            fill_opacity=0.9,
        ).add_to(m)

    # Emphasize the route line
    if path_nodes:
        for u, v in zip(path_nodes[:-1], path_nodes[1:]):
            if "lat" not in g.nodes[u] or "lon" not in g.nodes[u]:
                continue
            if "lat" not in g.nodes[v] or "lon" not in g.nodes[v]:
                continue
            folium.PolyLine(
                [(g.nodes[u]["lat"], g.nodes[u]["lon"]), (g.nodes[v]["lat"], g.nodes[v]["lon"])],
                color="red",
                weight=5,
                opacity=0.9,
            ).add_to(m)

    return m._repr_html_()


# --------------------------------------------------------------------
# Flask app
# --------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = SECRET
# Recommended cookie hardening (requires HTTPS for SECURE=True)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False  # set True in production with HTTPS
)


@app.route("/wayfinding/", methods=["GET", "POST"])
def index():
    global G, nodes_df
    G, nodes_df = load_graph()  # refresh if CSVs changed

    if request.method == "POST":
        user_lat = request.form.get("user_lat")
        user_lon = request.form.get("user_lon")
        use_user_loc = user_lat and user_lon and user_lat.strip() != "" and user_lon.strip() != ""

        start = (request.form.get("start") or "").strip()
        end = (request.form.get("end") or "").strip()

        # End location is always required
        if not end:
            flash("You must select an End location.")
            return redirect(url_for("index"))

        # GPS location takes priority over 'start'
        if use_user_loc:
            try:
                user_lat = float(user_lat)
                user_lon = float(user_lon)

                # Find closest cXX/cXXX node
                cxx_nodes = [n for n in G.nodes if re.fullmatch(r"c\d{2,3}", str(n))]
                if not cxx_nodes:
                    flash("No cXX/cXXX nodes available for routing.")
                    return redirect(url_for("index"))

                closest = min(
                    cxx_nodes,
                    key=lambda n: haversine_m(user_lat, user_lon, G.nodes[n]["lat"], G.nodes[n]["lon"]),
                )
                dist = haversine_m(user_lat, user_lon, G.nodes[closest]["lat"], G.nodes[closest]["lon"])

                temp_node = "_user_location_"
                # Add temp node and edge just for this calculation
                G.add_node(temp_node, lat=user_lat, lon=user_lon, level="ground")
                G.add_edge(temp_node, closest, weight=dist)

                # Route
                path_nodes, segments, total = shortest_path_via_cxx(temp_node, end, graph=G)
                if path_nodes is None:
                    flash(f"No path found from your location to {end}.")
                    return redirect(url_for("index"))

                # Rewrite the first segment label instead of duplicating it
                if segments and path_nodes and path_nodes[0] == temp_node and len(path_nodes) > 1:
                    first_edge_dist = G[temp_node][path_nodes[1]]["weight"]
                    segments[0] = (f"Your location → {path_nodes[1]} ({first_edge_dist:.1f} m)", first_edge_dist)

                start_label = "Your Location"
                map_html = make_map(path_nodes, graph=G)
                return render_template_string(
                    TEMPLATE_RESULT, start=start_label, end=end, segments=segments, total=total, map_html=map_html
                )
            except Exception as e:
                flash(f"Location error: {e}")
                return redirect(url_for("index"))

        # Manual start/end
        if not start:
            flash("You must select a Start location or use your location.")
            return redirect(url_for("index"))
        if start == end:
            flash("Start and End must be different.")
            return redirect(url_for("index"))

        path_nodes, segments, total = shortest_path_via_cxx(start, end, graph=G)
        if path_nodes is None:
            flash(f"No path found between {start} and {end} (must use cXX or cXXX nodes as intermediates).")
            return redirect(url_for("index"))

        map_html = make_map(path_nodes, graph=G)
        return render_template_string(
            TEMPLATE_RESULT, start=start, end=end, segments=segments, total=total, map_html=map_html
        )

    # GET
    locations = [n for n in sorted(G.nodes) if not re.fullmatch(r"c\d{2,3}", str(n))]
    return render_template_string(TEMPLATE_FORM, locations=locations)


# --------------------- Admin login/logout ----------------------------
@app.route("/wayfinding/admin_login", methods=["GET", "POST"])
def admin_login():
    # If password auth isn't configured, deny (or change to redirect if preferred)
    if not ADMIN_PWHASH:
        abort(403)

    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        if check_password_hash(ADMIN_PWHASH, pw):
            session["is_admin"] = True
            flash("Admin unlocked.")
            return redirect(url_for("add_node"))
        else:
            flash("Invalid password.")
    return render_template_string(TEMPLATE_ADMIN_LOGIN)


@app.route("/wayfinding/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Logged out.")
    return redirect(url_for("index"))


# ------------------------ Admin features -----------------------------
@app.route("/wayfinding/add_node")
def add_node():
    require_admin()
    G_now, nodes_now = load_graph()

    nodes = []
    for n in G_now.nodes:
        attrs = G_now.nodes[n]
        try:
            lat = float(attrs["lat"])
            lon = float(attrs["lon"])
            nodes.append(dict(label=n, lat=lat, lon=lon))
        except Exception as e:
            print(f"Skipping node {n} due to error: {e}")

    # Suggest next c### label
    existing = clean_nodes_df(pd.read_csv(NODES_CSV))
    c_nodes = [str(r) for r in existing["label"] if re.fullmatch(r"c\d{2,3}", str(r))]
    if c_nodes:
        max_num = max(int(s[1:]) for s in c_nodes)
    else:
        max_num = -1
    next_label = f"c{max_num + 1:03d}"

    edges = []
    for u, v in G_now.edges:
        try:
            u_lat, u_lon = G_now.nodes[u]["lat"], G_now.nodes[u]["lon"]
            v_lat, v_lon = G_now.nodes[v]["lat"], G_now.nodes[v]["lon"]
            edges.append({"from": u, "to": v, "u_lat": u_lat, "u_lon": u_lon, "v_lat": v_lat, "v_lon": v_lon})
        except Exception:
            continue

    return render_template_string(TEMPLATE_ADD_NODE, nodes=nodes, next_label=next_label, edges=edges)


@app.route("/wayfinding/api/add_node", methods=["POST"])
def api_add_node():
    require_admin()
    data = request.get_json(silent=True) or {}
    label = str(data.get("label", "")).strip()
    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except Exception:
        return jsonify({"error": "Invalid lat/lon"}), 400

    if not label:
        return jsonify({"error": "Missing label"}), 400
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return jsonify({"error": "Lat/lon out of bounds"}), 400

    # Enforce unique labels
    with locked_file(NODES_CSV, "r") as f:
        df = clean_nodes_df(pd.read_csv(f))
    if any(str(x).strip().lower() == label.lower() for x in df["label"]):
        return jsonify({"error": "Label already exists"}), 400

    with locked_file(NODES_CSV, "a") as f:
        writer = csv.writer(f)
        writer.writerow([label, lat, lon, "ground"])

    # Invalidate cache
    _GRAPH_CACHE["graph"] = None
    return jsonify({"label": label, "lat": lat, "lon": lon})


@app.route("/wayfinding/api/add_edge", methods=["POST"])
def api_add_edge():
    require_admin()
    data = request.get_json(silent=True) or {}
    from_node = str(data.get("from", "")).strip()
    to_node = str(data.get("to", "")).strip()

    if not from_node or not to_node or from_node == to_node:
        return jsonify({"error": "Invalid edge."}), 400

    # Load nodes and ensure both exist
    with locked_file(NODES_CSV, "r") as f:
        nodes_df = clean_nodes_df(pd.read_csv(f))
    nodes_df["label"] = nodes_df["label"].astype(str).str.strip()
    node_lookup = {
        r["label"]: (float(r["lat"]), float(r["lon"]))
        for _, r in nodes_df.iterrows()
        if r.get("lat") == r.get("lat") and r.get("lon") == r.get("lon")
    }

    if from_node not in node_lookup or to_node not in node_lookup:
        return jsonify({"error": "Unknown node(s). Save nodes first."}), 400

    # Deduplicate (both directions)
    with locked_file(EDGES_CSV, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0] == "from":
                continue
            if len(row) >= 2:
                a, b = row[0].strip(), row[1].strip()
                if {a, b} == {from_node, to_node}:
                    return jsonify({"error": "Edge already exists."}), 200

    # Compute authoritative distance on server
    (lat1, lon1), (lat2, lon2) = node_lookup[from_node], node_lookup[to_node]
    dist = round(haversine_m(lat1, lon1, lat2, lon2), 1)

    with locked_file(EDGES_CSV, "a") as f:
        writer = csv.writer(f)
        writer.writerow([from_node, to_node, dist])

    # Invalidate cache
    _GRAPH_CACHE["graph"] = None
    return jsonify({"result": f"Edge saved ({dist} m)."})


@app.route("/wayfinding/api/delete_edge", methods=["POST"])
def api_delete_edge():
    require_admin()
    data = request.get_json(silent=True) or {}
    from_node = str(data.get("from", "")).strip()
    to_node = str(data.get("to", "")).strip()
    if not from_node or not to_node:
        return jsonify({"error": "Missing edge data"}), 400

    new_rows = []
    found = False
    with locked_file(EDGES_CSV, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if row[0] == "from":
                new_rows.append(row)
                continue
            if len(row) < 2:
                continue
            a, b = row[0].strip(), row[1].strip()
            if {a, b} == {from_node, to_node}:
                found = True
                continue
            new_rows.append(row)

    with locked_file(EDGES_CSV, "w") as f:
        writer = csv.writer(f)
        writer.writerows(new_rows)

    # Invalidate cache
    _GRAPH_CACHE["graph"] = None
    if found:
        return jsonify({"result": "Deleted"})
    else:
        return jsonify({"error": "Edge not found"}), 404


# Optional: simple JSON path API (useful for mobile or automation)
@app.route("/wayfinding/api/path", methods=["GET"])
def api_path():
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    if not start or not end:
        return jsonify({"error": "start and end required"}), 400
    G_now, _ = load_graph()
    nodes, segments, total = shortest_path_via_cxx(start, end, graph=G_now)
    if nodes is None:
        return jsonify({"error": "no_path"}), 404
    return jsonify(
        {
            "start": start,
            "end": end,
            "total_m": round(total, 1),
            "nodes": nodes,
            "segments": [{"text": t, "m": d} for t, d in segments],
        }
    )


# --------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------
TEMPLATE_FORM = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Gallaudet Way-finding</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {
      font-family: Arial, Helvetica, sans-serif;
      margin: 0;
      padding: 0;
      background: #f7f9fc;
    }
    .container {
      max-width: 450px;
      margin: 0 auto;
      padding: 1em;
      background: #fff;
      box-shadow: 0 2px 12px #0001;
      border-radius: 1em;
      margin-top: 2em;
    }
    h1 {
      font-size: 2em;
      margin-bottom: .7em;
      text-align: center;
    }
    label {
      font-weight: 600;
      display: block;
      margin-bottom: .2em;
      margin-top: 1.2em;
    }
    select, option {
      width: 100%;
      min-width: 0;
      font-size: 1.2em;
      padding: .7em;
      margin-top: .2em;
      margin-bottom: 1em;
      border: 1px solid #bbb;
      border-radius: .5em;
      background: #f7f9fc;
      box-sizing: border-box;
    }
    #use-location-btn, #find-route-btn {
      width: 100%;
      font-size: 1.2em;
      padding: .7em;
      background: #0077cc;
      color: #fff;
      border: none;
      border-radius: .5em;
      margin-top: .2em;
      margin-bottom: 1em;
      cursor: pointer;
      transition: background .18s;
    }
    #use-location-btn:active,
    #use-location-btn:focus,
    #find-route-btn:active,
    #find-route-btn:focus {
      background: #005fa3;
    }
    .msg {
      color: #c00;
      margin: .7em 0;
      text-align: center;
      font-size: 1.08em;
    }
    #location-status {
      font-size: 1em;
      display: block;
      margin-bottom: .7em;
      text-align: center.
    }
    .admin-link {
      display: block;
      text-align: center;
      margin-top: 1.7em;
      font-size: 1em;
    }
    @media (max-width: 600px) {
      .container {
        max-width: 100vw;
        box-shadow: none;
        border-radius: 0;
        margin-top: 0;
        padding: 0.8em;
      }
      h1 { font-size: 1.3em; }
      select, option, #use-location-btn, #find-route-btn { font-size: 1em; }
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Shortest walking route on campus</h1>

    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for m in messages %}
          <div class="msg">{{m}}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="post">
      <input type="hidden" name="user_lat" id="user_lat">
      <input type="hidden" name="user_lon" id="user_lon">

      <label for="start">Start:</label>
      <select name="start" id="start">
        <option value="">-- Select --</option>
        {% for loc in locations %}
          <option value="{{loc}}">{{loc}}</option>
        {% endfor %}
      </select>

      <button type="button" id="use-location-btn">Or use my location</button>
      <span id="location-status"></span>
      <div style="margin-bottom: 1em; color:#333; font-size:.98em;">
        GPS locations are not stored and only used to build the route.
      </div>

      <label for="end">End:</label>
      <select name="end" id="end">
        {% for loc in locations %}
          <option value="{{loc}}">{{loc}}</option>
        {% endfor %}
      </select>

      <button type="submit" id="find-route-btn">Find route</button>
    </form>

    <a class="admin-link" href="{{ url_for('admin_login') }}">
      Or add new node or edges (admin feature)
    </a>
  </div>
  <script>
    document.getElementById('use-location-btn').onclick = function() {
      var status = document.getElementById('location-status');
      status.textContent = "Requesting location…";
      if (!navigator.geolocation) {
        status.textContent = "Geolocation not supported.";
        return;
      }
      navigator.geolocation.getCurrentPosition(function(pos) {
        var lat = pos.coords.latitude;
        var lon = pos.coords.longitude;
        document.getElementById('user_lat').value = lat;
        document.getElementById('user_lon').value = lon;
        status.innerHTML =
          '<b>Location set:</b><br>' +
          '<span style="color:green">' +
          'label: <code>_user_location_</code><br>' +
          'lat: <code>' + lat.toFixed(6) + '</code><br>' +
          'lon: <code>' + lon.toFixed(6) + '</code><br>' +
          'level: <code>ground</code></span>';
        document.getElementById('start').value = '';
      }, function(err) {
        status.textContent = "Unable to get location.";
      }, {enableHighAccuracy:true});
    };
  </script>
</body>
</html>
"""

TEMPLATE_RESULT = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Route: {{start}} ➜ {{end}}</title>
  <style>
    body{font-family:Arial,Helvetica,sans-serif;margin:1rem}
    ul{margin-top:.5rem}
    li{margin-bottom:.3rem}
    #map{margin-top:1rem}
    a{margin-top:1rem;display:inline-block}
  </style>
</head>
<body>
  <h2>Route: {{start}} ➜ {{end}}</h2>
  <strong>Total distance: {{'%.1f'|format(total)}} m</strong>
  <ul>
    {% for line, dist in segments %}
      <li>{{line}}</li>
    {% endfor %}
  </ul>
  <div id="map">{{map_html|safe}}</div>
  <a href="{{ url_for('index') }}">⇠ New search</a>
</body>
</html>
"""

TEMPLATE_ADD_NODE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Add Node by Map Click</title>
  <style>
    body {font-family:Arial,Helvetica,sans-serif;margin:2rem;}
    #map {
      width: 100%;
      max-width: 1000px;
      height: 600px;
      margin-top: 1rem;
    }
    .popup {background:#fff;padding:0.5em;border-radius:0.4em;}
    #msg {margin-top:1em;}
    @media (max-width: 700px) {
      #map {
        width: 100vw;
        height: 60vw;
        min-height: 300px;
        max-width: 100vw;
      }
      body {margin:0; padding:0.7em;}
    }
  </style>
  <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
</head>
<body>
  <h1>Click on map to add nodes and edges.</h1>
  <a href="{{ url_for('index') }}">⇠ Back to main</a>
  <div id="map"></div>
  <div id="msg"></div>
  <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
  var map = L.map('map').setView([{{nodes[0]["lat"]}}, {{nodes[0]["lon"]}}], 19);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  var nodes = {{nodes|tojson}};
  var nodeMarkers = {};
  nodes.forEach(function(node){
    var marker = L.circleMarker([node.lat, node.lon], {radius:5, color:'blue'}).addTo(map)
      .bindPopup(node.label);
    marker.label = node.label;
    marker.on('click', function(e){
      onNodeMarkerClick(marker);
      e.originalEvent.stopPropagation();
    });
    nodeMarkers[node.label] = marker;
  });

  var edges = {{edges|tojson}};
  var edgeLayers = [];
  var selectedEdge = null;
  var selectedLayer = null;
  var edgeClickedRecently = false;

  edges.forEach(function(edge){
    var poly = L.polyline(
      [[edge.u_lat, edge.u_lon], [edge.v_lat, edge.v_lon]],
      {color: '#5ec7f8', weight: 2, opacity: 0.5}
    ).addTo(map);
    poly.bindTooltip(edge.from + ' \u2192 ' + edge.to, {permanent: false, direction: "auto"});
    poly.on('click', function(e){
      selectEdge(edge, poly);
      edgeClickedRecently = true;
      e.originalEvent.stopPropagation();
    });
    edgeLayers.push({edge: edge, layer: poly});
  });

  function selectEdge(edge, layer) {
    if(selectedLayer) {
      selectedLayer.setStyle({color:'#5ec7f8', weight:2, opacity:0.5});
    }
    selectedEdge = edge;
    selectedLayer = layer;
    layer.setStyle({color:'orange', weight:4, opacity:0.8});
    document.getElementById("msg").innerHTML =
      '<b>Selected edge:</b> ' + edge.from + ' → ' + edge.to +
      ' <button id="inline-delete-btn" style="margin-left:1em;">Delete</button>';
    document.getElementById("inline-delete-btn").onclick = function() {
      if(!selectedEdge) return;
      if(!confirm("Delete edge " + selectedEdge.from + " → " + selectedEdge.to + "?")) return;
      fetch("/wayfinding/api/delete_edge", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({from:selectedEdge.from, to:selectedEdge.to})
      })
      .then(r => r.json())
      .then(d => {
        if(d.error) {
          document.getElementById("msg").innerHTML = '<span style="color:red">'+d.error+'</span>';
        } else {
          document.getElementById("msg").innerHTML = '<b>Edge deleted.</b> Reloading...';
          setTimeout(() => { window.location.reload(); }, 700);
        }
      });
    };
  }

  var edgeStart = null, edgeEnd = null, edgeLine = null;

  function onNodeMarkerClick(marker) {
    if (!edgeStart) {
      edgeStart = marker;
      marker.setStyle({color:'orange'});
      document.getElementById("msg").innerHTML = "Start: <b>" + marker.label + "</b>. Now select end node.";
    } else if (!edgeEnd && marker !== edgeStart) {
      edgeEnd = marker;
      marker.setStyle({color:'orange'});
      edgeLine = L.polyline([edgeStart.getLatLng(), edgeEnd.getLatLng()], {color:'blue', weight:4, dashArray:"6,8"}).addTo(map);
      var dist = map.distance(edgeStart.getLatLng(), edgeEnd.getLatLng());
      document.getElementById("msg").innerHTML =
        "Edge: <b>" + edgeStart.label + "</b> → <b>" + edgeEnd.label + "</b> = " + dist.toFixed(1) + "m " +
        '<button onclick="saveEdge()">Save Edge</button> <button onclick="cancelEdge()">Cancel</button>';
    }
  }

  function saveEdge() {
    var from = edgeStart.label;
    var to = edgeEnd.label;
    // distance is computed server-side; we send just endpoints for convenience
    fetch("/wayfinding/api/add_edge", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({from:from, to:to})
    })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        document.getElementById("msg").innerHTML = '<span style="color:red">' + d.error + '</span>';
      } else {
        document.getElementById("msg").innerHTML = "Edge saved: <b>" + from + "</b> → <b>" + to + "</b> (" + (d.result || '') + ")";
        var poly = L.polyline([edgeStart.getLatLng(), edgeEnd.getLatLng()], {color:'#5ec7f8', weight:2, opacity:0.5}).addTo(map);
        poly.bindTooltip(from + ' \u2192 ' + to, {permanent: false, direction: "auto"});
      }
      resetEdge();
    });
  }

  function cancelEdge() {
    resetEdge();
    document.getElementById("msg").innerHTML = "Edge creation cancelled.";
  }

  function resetEdge() {
    if(edgeStart) edgeStart.setStyle({color:'blue'});
    if(edgeEnd) edgeEnd.setStyle({color:'blue'});
    if(edgeLine) map.removeLayer(edgeLine);
    edgeStart = edgeEnd = edgeLine = null;
  }

  var lastMarker = null;
  map.on('click', function(e){
    if (edgeClickedRecently) {
      edgeClickedRecently = false;
      return;
    }
    if(lastMarker) map.removeLayer(lastMarker);
    lastMarker = L.marker(e.latlng).addTo(map);
    lastMarker.bindPopup(
      '<div class="popup">'+
        '<b>Add node here</b><br>Lat: '+e.latlng.lat.toFixed(6)+'<br>Lon: '+e.latlng.lng.toFixed(6)+
        '<br><input id="nlabel" type="text" value="{{next_label}}" style="width:160px"/><br>'+
        '<button onclick="saveNode('+e.latlng.lat+','+e.latlng.lng+')">Save Node</button>'+
      '</div>'
    ).openPopup();
  });

  function saveNode(lat, lon){
    var label = document.getElementById("nlabel").value.trim();
    if(!label){ alert("Please enter a label/name."); return; }
    fetch("/wayfinding/api/add_node", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({lat:lat, lon:lon, label:label})
    })
    .then(r => r.json())
    .then(d => {
      if(d.error){
        document.getElementById("msg").innerHTML = '<span style="color:red">'+d.error+'</span>';
        return;
      }
      document.getElementById("msg").innerHTML = '<b>Added node:</b> '+d.label+'<br>Reloading...';
      setTimeout(() => { window.location.reload(); }, 600);
    })
    .catch(err => {
      alert("Failed to save node: "+err);
    });
  }
</script>
</body>
</html>
"""

TEMPLATE_ADMIN_LOGIN = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Admin Login</title>
  <style>
    body {font-family: Arial, Helvetica, sans-serif; background:#f7f9fc; margin:0}
    .box {max-width:420px; margin:8vh auto; background:#fff; padding:1.2em 1.4em; border-radius:1em; box-shadow:0 2px 12px #0001}
    h1 {font-size:1.4em; margin:0 0 .8em}
    input[type=password], button {width:100%; font-size:1.1em; padding:.7em; margin:.4em 0}
    button {background:#0077cc; color:#fff; border:none; border-radius:.5em; cursor:pointer}
    button:focus, button:active {background:#005fa3}
    .msg {color:#c00; text-align:center; margin:.5em 0}
  </style>
</head>
<body>
  <div class="box">
    <h1>Admin Login</h1>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for m in messages %}
          <div class="msg">{{m}}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <form method="post">
      <input type="password" name="password" placeholder="Admin password" autocomplete="current-password" required>
      <button type="submit">Unlock</button>
    </form>
    <p><a href="{{ url_for('index') }}">⇠ Back</a></p>
  </div>
</body>
</html>
"""

# --------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5555)
