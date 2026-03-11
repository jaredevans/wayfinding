# Gallaudet Campus Wayfinding

## What It Does

A web-based walking directions app for Gallaudet University's campus. Users pick where they are and where they want to go, and the app shows the shortest walking route on an interactive map.

## How It Works for Users

1. **Open the app** in any mobile or desktop browser
2. **Choose a starting point** — either select a building from a dropdown list, or tap "Use my location" to let the app find you via GPS
3. **Choose a destination** from the dropdown list
4. **View your route** — the app displays step-by-step walking directions with distances, plus an interactive map showing the path highlighted in color
5. **Track your walk** — optionally enable live GPS tracking to see your position move on the map as you walk

## How It Works for Admins

Authorized administrators can log in to manage the campus map:

- **Add locations** — click anywhere on the map to add a new building or walkway point
- **Connect locations** — click two points to create a walkable path between them (the app automatically calculates the distance)
- **Remove connections** — click an existing path to delete it

Changes take effect immediately — no restart needed.

## Key Features

- **Shortest route calculation** — finds the optimal walking path through campus walkways
- **GPS integration** — uses your phone's location to start directions from wherever you are
- **Live tracking** — watch your position on the map in real time as you walk
- **Interactive maps** — zoomable, pannable maps built on OpenStreetMap
- **Mobile-friendly** — responsive design that works well on phones and tablets
- **Privacy-first** — GPS locations are used in the moment and never stored
- **Admin tools** — password-protected interface for maintaining the campus map

## What the Campus Map Contains

- **~56 named locations** — buildings, landmarks, and points of interest across campus
- **~108 walkway intersections** — points where paths meet, used behind the scenes to calculate realistic walking routes
- **~217 path segments** — the walkable connections between all these points, each with a measured distance in meters
