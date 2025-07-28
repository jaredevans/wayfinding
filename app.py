#!/var/www/wayfinding/.venv/bin/python
"""
Flask way-finding demo for Gallaudet campus, with robust admin add-node and add-edge feature.
All shortest paths between named nodes must traverse only cXX or cXXX nodes between them.
"""

import os
import csv
import pandas as pd
import networkx as nx
import folium
import re
from flask import (
    Flask, render_template_string, request, redirect, url_for, flash, jsonify
)

NODES_CSV = os.path.join(os.path.dirname(__file__), "nodes.csv")
EDGES_CSV = os.path.join(os.path.dirname(__file__), "edges.csv")

def clean_nodes_df(df):
    for col in df.select_dtypes(include="object"):
        df[col] = df[col].str.strip()
    df = df.dropna(subset=["label", "lat", "lon"])
    df = df[~(df["lat"] == '') & ~(df["lon"] == '')]
    return df

def load_graph():
    nodes_df = clean_nodes_df(pd.read_csv(NODES_CSV))
    edges_df = pd.read_csv(EDGES_CSV)
    G = nx.Graph()
    for _, row in nodes_df.iterrows():
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except Exception as e:
            print(f"[WARN] Skipping node '{row.get('label', '?')}' due to bad lat/lon: {e}")
            continue
        label = str(row["label"]).strip()
        level = str(row.get("level", "ground")).strip().lower()
        G.add_node(label, lat=lat, lon=lon, level=level)
    for _, row in edges_df.iterrows():
        f = str(row["from"]).strip()
        t = str(row["to"]).strip()
        try:
            w = float(row["distance"])
            G.add_edge(f, t, weight=w)
        except Exception as e:
            print(f"[WARN] Bad edge {f}–{t}: {e}")
            continue
    return G, nodes_df

def shortest_path_via_cxx(start: str, end: str):
    def is_cxx(n):
        return bool(re.fullmatch(r"c\d{2,3}", n))
    allowed = {start, end}
    allowed.update([n for n in G.nodes if is_cxx(n)])
    H = G.subgraph(allowed)
    try:
        nodes = nx.dijkstra_path(H, start, end, weight="weight")
    except nx.NetworkXNoPath:
        return None, [], 0.0
    steps = []
    total = 0.0
    for a, b in zip(nodes[:-1], nodes[1:]):
        d = G[a][b]["weight"]
        total += d
        steps.append((f"{a} → {b} ({d:.1f} m)", d))
    return nodes, steps, total

def make_map(path_nodes):
    lats = [G.nodes[n]["lat"] for n in G.nodes if "lat" in G.nodes[n]]
    lons = [G.nodes[n]["lon"] for n in G.nodes if "lon" in G.nodes[n]]
    if not lats or not lons:
        m = folium.Map(location=[0,0], zoom_start=2)
    else:
        m = folium.Map(location=[sum(lats)/len(lats), sum(lons)/len(lons)],
                       zoom_start=17, tiles="OpenStreetMap")
    for n in G.nodes:
        if re.fullmatch(r"c\d{2,3}", n) and (not path_nodes or n not in path_nodes):
            continue
        attrs = G.nodes[n]
        if "lat" not in attrs or "lon" not in attrs:
            continue
        folium.CircleMarker(
            location=[attrs["lat"], attrs["lon"]],
            radius=4,
            popup=n,
            color="red" if (path_nodes and n in path_nodes) else "blue",
            fill=True, fill_opacity=0.9,
        ).add_to(m)
    for u, v in G.edges:
        if "lat" not in G.nodes[u] or "lon" not in G.nodes[u]:
            continue
        if "lat" not in G.nodes[v] or "lon" not in G.nodes[v]:
            continue
        folium.PolyLine(
            [(G.nodes[u]["lat"], G.nodes[u]["lon"]),
             (G.nodes[v]["lat"], G.nodes[v]["lon"])],
            color="#5ec7f8", weight=2, opacity=0.5,
            tooltip=f"{u} \u2192 {v}"
        ).add_to(m)
    if path_nodes:
        for u, v in zip(path_nodes[:-1], path_nodes[1:]):
            if "lat" not in G.nodes[u] or "lon" not in G.nodes[u]:
                continue
            if "lat" not in G.nodes[v] or "lon" not in G.nodes[v]:
                continue
            folium.PolyLine(
                [(G.nodes[u]["lat"], G.nodes[u]["lon"]),
                 (G.nodes[v]["lat"], G.nodes[v]["lon"])],
                color="red", weight=5, opacity=0.9,
            ).add_to(m)
    return m._repr_html_()

app = Flask(__name__)
app.secret_key = "replace‑me‑with‑something‑secret"

# All routes are now prefixed with /wayfinding

@app.route("/wayfinding/", methods=["GET", "POST"])
def index():
    global G, nodes_df, labels_sorted
    G, nodes_df = load_graph()
    labels_sorted = sorted(G.nodes)
    if request.method == "POST":
        start = request.form.get("start")
        end   = request.form.get("end")
        if start == end:
            flash("Start and End must be different.")
            return redirect(url_for("index"))
        path_nodes, segments, total = shortest_path_via_cxx(start, end)
        if path_nodes is None:
            flash(f"No path found between {start} and {end} (must use cXX or cXXX nodes as intermediates).")
            return redirect(url_for("index"))
        map_html = make_map(path_nodes)
        return render_template_string(TEMPLATE_RESULT,
                                      start=start, end=end,
                                      segments=segments,
                                      total=total,
                                      map_html=map_html)
    locations = [n for n in sorted(G.nodes) if not re.fullmatch(r"c\d{2,3}", n)]
    return render_template_string(TEMPLATE_FORM, locations=locations)

@app.route("/wayfinding/add_node")
def add_node():
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
    existing = clean_nodes_df(pd.read_csv(NODES_CSV))
    c_nodes = [r for r in existing["label"] if re.fullmatch(r"c\d{2,3}", str(r))]
    if c_nodes:
        max_num = max(int(str(r)[1:]) for r in c_nodes)
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
    data = request.get_json()
    lat = float(data.get("lat"))
    lon = float(data.get("lon"))
    label = data.get("label", "").strip()
    if not label:
        return jsonify({"error": "Missing label"}), 400
    with open(NODES_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([label, lat, lon, "ground"])
    return jsonify({"label": label, "lat": lat, "lon": lon})

@app.route("/wayfinding/api/add_edge", methods=["POST"])
def api_add_edge():
    data = request.get_json()
    from_node = data.get("from", "").strip()
    to_node = data.get("to", "").strip()
    distance = float(data.get("distance"))
    if not from_node or not to_node or from_node == to_node:
        return jsonify({"error": "Invalid edge."}), 400
    found = False
    with open(EDGES_CSV, "r") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 3 or parts[0] == "from":
                continue
            a, b = parts[0].strip(), parts[1].strip()
            if (a == from_node and b == to_node) or (a == to_node and b == from_node):
                found = True
                break
    if found:
        return jsonify({"error": "Edge already exists."}), 200
    with open(EDGES_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([from_node, to_node, round(distance, 1)])
    return jsonify({"result": "Edge saved."})

@app.route("/wayfinding/api/delete_edge", methods=["POST"])
def api_delete_edge():
    data = request.get_json()
    from_node = data.get("from", "").strip()
    to_node = data.get("to", "").strip()
    if not from_node or not to_node:
        return jsonify({"error": "Missing edge data"}), 400
    new_rows = []
    found = False
    with open(EDGES_CSV, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == "from":
                new_rows.append(row)
                continue
            if not row or len(row) < 3:
                continue
            a, b = row[0].strip(), row[1].strip()
            if (a == from_node and b == to_node) or (a == to_node and b == from_node):
                found = True
                continue
            new_rows.append(row)
    with open(EDGES_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(new_rows)
    if found:
        return jsonify({"result": "Deleted"})
    else:
        return jsonify({"error": "Edge not found"}), 404

# Templates
TEMPLATE_FORM = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Gallaudet Way‑finding</title>
  <style>
    body{font-family:Arial,Helvetica,sans-serif;margin:2rem}
    label{margin-right:.5rem}
    select, option{min-width:280px; font-size:1.5rem;}
    .msg{color:red;margin:.5rem 0}
  </style>
</head>
<body>
  <h1>Shortest walking route on campus</h1>

  {% with messages = get_flashed_messages() %}
    {% if messages %}
      {% for m in messages %}<div class="msg">{{m}}</div>{% endfor %}
    {% endif %}
  {% endwith %}
  <form method="post">
    <p>
      <label for="start">Start:</label>
      <select name="start" id="start">
        {% for loc in locations %}
          <option value="{{loc}}">{{loc}}</option>
        {% endfor %}
      </select>
    </p>
    <p>
      <label for="end">End:</label>
      <select name="end" id="end">
        {% for loc in locations %}
          <option value="{{loc}}">{{loc}}</option>
        {% endfor %}
      </select>
    </p>
    <button type="submit">Find route</button>
  </form>
  <P></P><a href="{{ url_for('add_node') }}">Or add new node or edges (This is an admin feature: ** Use with care! **)</
a>
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
  <strong>Total distance: {{'%.1f'|format(total)}} m</strong>
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
    body{font-family:Arial,Helvetica,sans-serif;margin:2rem}
    #map{width:800px;height:500px;margin-top:1rem}
    .popup{background:#fff;padding:0.5em;border-radius:0.4em}
    #msg{margin-top:1em;}
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
  var map = L.map('map').setView([{{nodes[0]["lat"]}}, {{nodes[0]["lon"]}}], 17);

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
    var dist = map.distance(edgeStart.getLatLng(), edgeEnd.getLatLng());
    fetch("/wayfinding/api/add_edge", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({from:from, to:to, distance:dist})
    })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        document.getElementById("msg").innerHTML = '<span style="color:red">' + d.error + '</span>';
      } else {
        document.getElementById("msg").innerHTML = "Edge saved: <b>" + from + "</b> → <b>" + to + "</b> (" + dist.toFixed(1) + "m)";
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

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5555)
