#!/usr/bin/env python3
import os
import re
import pandas as pd
import networkx as nx
import folium

NODES_CSV = "nodes.csv"
EDGES_CSV = "edges.csv"

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
        except Exception:
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
        except Exception:
            continue
    return G

def shortest_path_via_cxx(G, start, end):
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

# --- Load graph ---
G = load_graph()
node_labels = sorted([n for n in G.nodes if not re.fullmatch(r"c\d{2,3}", n)])

print("Available locations:")
for i, label in enumerate(node_labels, 1):
    print(f" {i}: {label}")

def get_node_by_number(prompt):
    while True:
        try:
            n = int(input(prompt))
            if 1 <= n <= len(node_labels):
                return node_labels[n-1]
            else:
                print(f"Please enter a number between 1 and {len(node_labels)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")

start = get_node_by_number("\nEnter the number for the START location: ")
end = get_node_by_number("Enter the number for the END location: ")
if start == end:
    print("Start and end must be different.")
    exit(1)

path_nodes, segments, total = shortest_path_via_cxx(G, start, end)

print(f"\nRoute from {start} to {end}:")
if not path_nodes:
    print("No route found (must traverse via cXX or cXXX nodes).")
else:
    for desc, dist in segments:
        print(f" - {desc}")
    print(f"\nTotal distance: {total:.1f} m")

# ----------- Generate Map -----------
if path_nodes:
    lats = [G.nodes[n]["lat"] for n in G.nodes if "lat" in G.nodes[n]]
    lons = [G.nodes[n]["lon"] for n in G.nodes if "lon" in G.nodes[n]]
    map_center = [sum(lats)/len(lats), sum(lons)/len(lons)]
    m = folium.Map(location=map_center, zoom_start=17)

    # Show all nodes, highlight only those in the path
    for n in G.nodes:
        attrs = G.nodes[n]
        color = "red" if n in path_nodes else "blue"
        folium.CircleMarker(
            location=[attrs["lat"], attrs["lon"]],
            radius=4,
            popup=n,
            color=color,
            fill=True, fill_opacity=0.9,
        ).add_to(m)
    # Draw all edges in gray
    for u, v in G.edges:
        if "lat" in G.nodes[u] and "lat" in G.nodes[v]:
            folium.PolyLine(
                [(G.nodes[u]["lat"], G.nodes[u]["lon"]),
                 (G.nodes[v]["lat"], G.nodes[v]["lon"])],
                color="#5ec7f8", weight=2, opacity=0.5,
            ).add_to(m)
    # Highlight path in red
    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        folium.PolyLine(
            [(G.nodes[u]["lat"], G.nodes[u]["lon"]),
             (G.nodes[v]["lat"], G.nodes[v]["lon"])],
            color="red", weight=5, opacity=0.9,
        ).add_to(m)
    m.save("map.html")
    print("\nInteractive map saved as map.html")
else:
    print("\nNo map generated (no route found).")
