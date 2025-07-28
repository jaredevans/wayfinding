#!/Users/jared.evans/python_projs/wayfinding/.venv/bin/python3
import pandas as pd
import networkx as nx

# --- Load data from CSV files ---
nodes_df = pd.read_csv("nodes.csv")
edges_df = pd.read_csv("edges.csv")

# --- Build the graph ---
G = nx.Graph()

# Add nodes (label, lat, lon, level)
for _, row in nodes_df.iterrows():
    G.add_node(
        row["label"],
        lat=row["lat"],
        lon=row["lon"],
        level=str(row["level"]).lower()
    )

# Add edges (from, to, distance)
for _, row in edges_df.iterrows():
    G.add_edge(
        row["from"],
        row["to"],
        weight=float(row["distance"])
    )

def find_route(start_label, end_label):
    try:
        path = nx.dijkstra_path(G, start_label, end_label, weight="weight")
    except nx.NetworkXNoPath:
        print(f"No path found between {start_label} and {end_label}.")
        return []
    steps = []
    for i in range(len(path)-1):
        a, b = path[i], path[i+1]
        a_level = G.nodes[a]["level"]
        b_level = G.nodes[b]["level"]
        distance = G[a][b]["weight"]
        desc = f"{a} ({a_level}) → {b} ({b_level})"
        if a_level != b_level:
            desc += "   [USE STAIR OR RAMP]"
        steps.append((desc, distance))
    return steps

# --- Show numbered list of nodes ---
node_labels = list(G.nodes)
print("Available locations:")
for i, label in enumerate(node_labels, 1):
    print(f" {i}: {label}")

# --- Get user selection by number ---
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

# --- Find and display the route ---
route = find_route(start, end)

print(f"\nRoute from {start} to {end}:")
total_distance = 0
if not route:
    print("No route found.")
else:
    for step, distance in route:
        print(f" - {step}  [{distance:.1f} units]")
        total_distance += distance
    print(f"\nTotal distance: {total_distance:.1f} units")

# ----------- Generate Map -----------
import folium

if route:
    # Get a list of node labels in the path, in order
    path_labels = [start]
    for step, _ in route:
        # step is in the format "A (...) → B (...)", extract B
        to_label = step.split("→")[1].split("(")[0].strip()
        path_labels.append(to_label)

    # Calculate map center
    lats = [G.nodes[label]["lat"] for label in G.nodes]
    lons = [G.nodes[label]["lon"] for label in G.nodes]
    map_center = [sum(lats)/len(lats), sum(lons)/len(lons)]

    m = folium.Map(location=map_center, zoom_start=17)

    # Add all nodes as markers
    for label in G.nodes:
        lat = G.nodes[label]["lat"]
        lon = G.nodes[label]["lon"]
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            popup=label,
            color="blue" if label not in path_labels else "red",
            fill=True,
            fill_color="blue" if label not in path_labels else "red",
            fill_opacity=0.8,
        ).add_to(m)

    # Add all edges in gray
    for u, v in G.edges:
        lat1, lon1 = G.nodes[u]["lat"], G.nodes[u]["lon"]
        lat2, lon2 = G.nodes[v]["lat"], G.nodes[v]["lon"]
        folium.PolyLine(
            locations=[(lat1, lon1), (lat2, lon2)],
            color="gray",
            weight=2,
            opacity=0.5,
        ).add_to(m)

    # Highlight the path in red
    for i in range(len(path_labels)-1):
        u, v = path_labels[i], path_labels[i+1]
        lat1, lon1 = G.nodes[u]["lat"], G.nodes[u]["lon"]
        lat2, lon2 = G.nodes[v]["lat"], G.nodes[v]["lon"]
        folium.PolyLine(
            locations=[(lat1, lon1), (lat2, lon2)],
            color="red",
            weight=6,
            opacity=1,
        ).add_to(m)

    # Save the map
    m.save("map.html")
    print("\nInteractive map saved as map.html")

else:
    print("\nNo map generated (no route found).")
