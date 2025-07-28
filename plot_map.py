#!/Users/jared.evans/python_projs/wayfinding/.venv/bin/python3

import pandas as pd
import folium

# Read the nodes.csv
nodes = pd.read_csv("nodes.csv")

# Get the campus center for initial map location
center_lat = nodes["lat"].mean()
center_lon = nodes["lon"].mean()

# Create the map
m = folium.Map(location=[center_lat, center_lon], zoom_start=17)

# Add each building as a marker
for _, row in nodes.iterrows():
    folium.Marker(
        [row["lat"], row["lon"]],
        popup=row["label"],
        tooltip=row["label"]
    ).add_to(m)

# Save and show the map
m.save("gallaudet_map.html")
print("Map saved as gallaudet_map.html. Open it in your browser.")

