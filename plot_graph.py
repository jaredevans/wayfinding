#!/Users/jared.evans/python_projs/wayfinding/.venv/bin/python3

import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt

# Load your CSV files
nodes_df = pd.read_csv("nodes.csv")
edges_df = pd.read_csv("edges.csv")

# Build the graph
G = nx.Graph()
for _, row in nodes_df.iterrows():
    G.add_node(row["label"], lat=row["lat"], lon=row["lon"], level=row["level"].lower())
for _, row in edges_df.iterrows():
    G.add_edge(row["from"], row["to"], weight=float(row["distance"]))

# Set positions for plotting (lon, lat for x, y)
pos = {node: (G.nodes[node]["lon"], G.nodes[node]["lat"]) for node in G.nodes}
ground_nodes = [n for n in G.nodes if G.nodes[n]["level"] == "ground"]
second_nodes = [n for n in G.nodes if G.nodes[n]["level"] == "second level"]

plt.figure(figsize=(16, 12))  # <- Bigger image!

nx.draw_networkx_edges(G, pos, alpha=0.6)
nx.draw_networkx_nodes(G, pos, nodelist=ground_nodes, node_color='skyblue', node_shape='o', label="Ground")
nx.draw_networkx_nodes(G, pos, nodelist=second_nodes, node_color='orange', node_shape='s', label="Second level")

# Show only first 10 characters for each label
short_labels = {node: node[:10] for node in G.nodes}
nx.draw_networkx_labels(G, pos, labels=short_labels, font_size=11)

# Draw edge labels (distances)
edge_labels = {(u, v): f'{d["weight"]:.0f}' for u, v, d in G.edges(data=True)}
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=9)

plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.title("Campus Graph: Nodes and Paths")
plt.legend(scatterpoints=1)
plt.tight_layout()

# --- Save as PNG ---
plt.savefig("campus_graph.png", dpi=200)
print("Saved as campus_graph.png")

plt.show()
