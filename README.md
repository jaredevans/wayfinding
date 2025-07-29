# Campus Wayfinding

This project provides a web-based wayfinding application for a campus. It allows users to find the shortest walking route between two points of interest and includes an administrative interface for managing the underlying campus graph data.

## Python Scripts

### `app.py`

This is the main Flask web application that powers the interactive wayfinding service. It provides a user-friendly interface for route calculation and a comprehensive admin panel for graph management.

**User-Facing Features:**

-   **Route Finding:**
    -   Users can select a start and end location from dropdown menus populated with named points of interest.
    -   Alternatively, users can use their device's GPS coordinates as the starting point. The application will find the nearest connector node to begin the route.
-   **Specialized Routing Algorithm:** The core logic ensures that all routes between major locations are calculated via a network of connector nodes (e.g., `c001`, `c002`). This enforces realistic paths along primary walkways.
-   **Interactive Map Visualization:** The calculated route is displayed on an interactive map (using Folium and Leaflet.js), with the path highlighted and markers for each node.

**Administrative Features:**

The application includes a powerful admin interface at the `/wayfinding/add_node` endpoint for real-time management of the campus map data.

-   **Add Nodes:** Administrators can add new nodes (points of interest or connector nodes) to the graph simply by clicking on the desired location on the map. A popup allows them to assign a label before saving.
-   **Add Edges:** New paths (edges) can be created by clicking on two existing nodes in sequence. The application automatically calculates the distance and prompts for confirmation before saving.
-   **Delete Edges:** Existing edges can be selected and deleted with a single click, making it easy to correct or update pathways.

<img src="https://i.imgur.com/p4VaqLd.png" width=500 height=800>

### `wayfinding.py`

A command-line interface (CLI) tool for finding routes.

-   It loads the campus graph from `nodes.csv` and `edges.csv`.
-   Prompts the user to select start and end locations from a numbered list of major locations (connector nodes are excluded).
-   Calculates the shortest path using a specialized algorithm that requires the route to pass through connector nodes (labeled `cXX` or `cXXX`). This mirrors the logic in the web application.
-   Prints the step-by-step directions and total distance to the console.
-   Generates an interactive `map.html` file that visualizes the route, highlighting the path in red.

### `get_gps_coordinates_openstreetmap.py`

A utility script to fetch GPS coordinates for a list of building names.

-   Uses the `geopy` library with the Nominatim (OpenStreetMap) geocoder.
-   Takes a list of building names as input.
-   Queries the geocoding service to find the latitude and longitude for each name.
-   Saves the results into a `nodes_auto.csv` file.
-   Includes a `time.sleep(1)` call between API requests to avoid overwhelming the service.

### `plot_graph.py`

A script for visualizing the campus graph as a static image.

-   Reads `nodes.csv` and `edges.csv`.
-   Uses `networkx` to build the graph data structure.
-   Uses `matplotlib` to draw the graph, with nodes positioned according to their actual GPS coordinates.
-   Differentiates nodes by level (e.g., "ground" vs. "second level") using different colors and shapes.
-   Labels nodes and edges with their names and distances.
-   Saves the resulting plot as `campus_graph.png`.

### `plot_map.py`

A simple script to generate an interactive map of all nodes.

-   Reads the `nodes.csv` file.
-   Uses `folium` to create an HTML map centered on the average coordinates of all nodes.
-   Adds a marker for each node, with a popup displaying its label.
-   Saves the map as `gallaudet_map.html`.

### `wsgi.py`

A standard WSGI entry point used to deploy the Flask application (`app.py`) with a production-ready server like Gunicorn. It imports the `app` instance so the server can find it.

## Data Files

-   `nodes.csv`: Contains the list of all points of interest (nodes) with their `label`, `lat` (latitude), `lon` (longitude), and `level`.
-   `edges.csv`: Contains the list of all paths (edges) connecting the nodes, with their `from` node, `to` node, and the `distance` between them in meters.
