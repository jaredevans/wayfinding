#!/Users/jared.evans/python_projs/wayfinding/.venv/bin/python3

from geopy.geocoders import Nominatim
import pandas as pd
import time

geolocator = Nominatim(user_agent="gallaudet_buildings")

buildings = [
    "dawes house 20242",
]

results = []
for name in buildings:
    location = geolocator.geocode(name)
    if location:
        print(f"{name}: {location.latitude}, {location.longitude}")
        results.append([name, location.latitude, location.longitude, "ground"])
    else:
        print(f"Not found: {name}")
    time.sleep(1)  # Be polite to the API!

pd.DataFrame(results, columns=["label", "lat", "lon", "level"]).to_csv("nodes_auto.csv", index=False)

