# app.py
import os
import requests
from flask import Flask, render_template_string, request, jsonify
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import time

app = Flask(__name__)

# config from env
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")  # optional; best experience if provided
MAP_PROVIDER = "google" if GOOGLE_API_KEY else "osm"  # auto-fallback to OSM if no key

# HTML template: 2-column layout, left controls, right map
# Google Maps JS will be used if GOOGLE_API_KEY provided; otherwise use Leaflet + OSM tiles
TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>India Hospital Finder</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
  {% if map_provider == 'osm' %}
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.3/dist/leaflet.css"/>
  {% endif %}
  <style>
    body { background:#f8f9fa; }
    #map { height: 80vh; width:100%; border-radius:6px; }
    .result-item { cursor:pointer; }
  </style>
</head>
<body>
<div class="container-fluid py-3">
  <h2 class="mb-3 text-center">India Hospital Finder — Professional</h2>
  <div class="row g-3">
    <div class="col-md-4">
      <div class="card p-3 shadow-sm">
        <form id="searchForm">
          <div class="mb-2">
            <label class="form-label">Location (auto-suggest)</label>
            <input id="locationInput" class="form-control" placeholder="Type a city, landmark or address" autocomplete="off">
          </div>
          <div class="mb-2">
            <label class="form-label">Manual location (lat,lng) — optional</label>
            <input id="manualLocation" class="form-control" placeholder="12.97,77.59 or leave empty">
          </div>
          <div class="mb-2">
            <label class="form-label">Type</label>
            <select id="typeSelect" class="form-select">
              <option value="hospital">Hospital</option>
              <option value="clinic">Clinic</option>
              <option value="pharmacy">Pharmacy</option>
              <option value="mental_health">Mental Health</option>
              <option value="all">All</option>
            </select>
          </div>
          <div class="d-grid gap-2">
            <button class="btn btn-primary" type="submit">Search Nearby</button>
          </div>
        </form>

        <hr>
        <h6>Results</h6>
        <div id="results" style="max-height:50vh; overflow:auto;"></div>
      </div>
    </div>

    <div class="col-md-8">
      <div class="card p-2 shadow-sm">
        <div id="map"></div>
        <div id="detailCard" class="mt-3"></div>
      </div>
    </div>
  </div>
</div>

<!-- dependencies -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/js/bootstrap.bundle.min.js"></script>

{% if map_provider == 'google' %}
<script src="https://maps.googleapis.com/maps/api/js?key={{ google_api_key }}&libraries=places"></script>
<script>
  // Google Maps version
  let map, service, infoWindow, userMarker;
  function initMap() {
    map = new google.maps.Map(document.getElementById("map"), { center: { lat: 20.5937, lng: 78.9629 }, zoom: 5 });
    infoWindow = new google.maps.InfoWindow();
    // Autocomplete for location input
    const input = document.getElementById('locationInput');
    const autocomplete = new google.maps.places.Autocomplete(input, { componentRestrictions: { country: "in" }});
    autocomplete.setFields(["geometry","formatted_address","name"]);
    autocomplete.addListener('place_changed', () => {
      const place = autocomplete.getPlace();
      if (!place.geometry) return;
      const loc = place.geometry.location;
      map.setCenter(loc);
      map.setZoom(13);
    });
  }

  window.initMap = initMap; // for callback if needed

  // helpers: perform search via our backend
  async function searchNearby(lat,lng,type){
    const r = await fetch('/api/search_nearby', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ lat, lng, type })
    });
    return r.json();
  }

  // on submit
  document.getElementById('searchForm').addEventListener('submit', async (e)=>{
    e.preventDefault();
    const manual = document.getElementById('manualLocation').value.trim();
    let lat,lng;
    if(manual){
      const parts = manual.split(',');
      if(parts.length>=2){ lat = parseFloat(parts[0]); lng = parseFloat(parts[1]); }
    }
    if(!lat){
      const v = document.getElementById('locationInput').value.trim();
      if(!v){ alert('Enter location or manual coords'); return; }
      // geocode via backend
      const resp = await fetch('/api/geocode', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ q: v })
      });
      const j = await resp.json();
      if(!j.ok){ alert('Location not found'); return; }
      lat = j.lat; lng = j.lng;
    }
    const type = document.getElementById('typeSelect').value;
    const json = await searchNearby(lat,lng,type);
    renderResults(json, lat, lng);
  });

  let markers = [];
  function clearMarkers(){ markers.forEach(m=>m.setMap(null)); markers = []; }

  function renderResults(json, userLat, userLng){
    const resultsDiv = document.getElementById('results'); resultsDiv.innerHTML = '';
    clearMarkers();
    if(!json.results || json.results.length === 0){ resultsDiv.innerHTML = '<p>No results nearby.</p>'; return; }
    json.results.forEach((place, idx)=>{
      const item = document.createElement('div'); item.className='p-2 result-item border-bottom';
      item.innerHTML = `<b>${place.name}</b><br><small>${place.address||''}</small><br><small>Rating: ${place.rating||'N/A'}</small>`;
      item.onclick = ()=> { showDetails(place); }
      resultsDiv.appendChild(item);

      // place marker
      const marker = new google.maps.Marker({
        position: { lat: place.lat, lng: place.lng },
        map,
        title: place.name
      });
      marker.addListener('click', ()=> showDetails(place));
      markers.push(marker);
    });
    map.setCenter({ lat: userLat, lng: userLng }); map.setZoom(13);
  }

  async function showDetails(place){
    const r = await fetch('/api/place_details', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ place_id: place.place_id })
    });
    const j = await r.json();
    const html = `
      <div class="card p-3">
        <h5>${j.name}</h5>
        <p>${j.address||''}</p>
        <p>Phone: ${j.phone||'N/A'}</p>
        <p>Website: ${j.website ? '<a href="'+j.website+'" target="_blank">'+j.website+'</a>' : 'N/A'}</p>
        <p>Rating: ${j.rating||'N/A'}</p>
        <div>
          <button class="btn btn-sm btn-outline-primary" onclick="getDirections(${j.lat},${j.lng})">Get Directions</button>
        </div>
      </div>
    `;
    document.getElementById('detailCard').innerHTML = html;
  }

  async function getDirections(destLat, destLng){
    // get user's location (we used last searched center)
    const resp = await fetch('/api/directions', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ dest: { lat: destLat, lng: destLng } })
    });
    const j = await resp.json();
    if(!j.ok){ alert('Directions error'); return; }
    // open google maps with directions
    const url = j.google_maps_url || j.navigation_url || ('https://www.google.com/maps/dir/?api=1&destination='+destLat+','+destLng);
    window.open(url, '_blank');
  }

  // initialize map after script loads
  window.addEventListener('load', ()=> {
    // if initMap not automatically called, call it
    if(typeof google !== 'undefined' && google.maps && !map) initMap();
  });
</script>

{% else %}
<!-- OSM / Leaflet JS version (fallback) -->
<script src="https://unpkg.com/leaflet@1.9.3/dist/leaflet.js"></script>
<script>
  let map = L.map('map').setView([20.5937,78.9629],5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{ attribution:'© OpenStreetMap contributors' }).addTo(map);
  let markers = [];

  async function searchNearby(lat,lng,type){
    const r = await fetch('/api/search_nearby', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ lat, lng, type })
    });
    return r.json();
  }

  document.getElementById('searchForm').addEventListener('submit', async (e)=>{
    e.preventDefault();
    const manual = document.getElementById('manualLocation').value.trim();
    let lat,lng;
    if(manual){
      const parts = manual.split(',');
      if(parts.length>=2){ lat = parseFloat(parts[0]); lng = parseFloat(parts[1]); }
    }
    if(!lat){
      const v = document.getElementById('locationInput').value.trim();
      if(!v){ alert('Enter location or manual coords'); return; }
      const resp = await fetch('/api/geocode', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ q: v })
      });
      const j = await resp.json();
      if(!j.ok){ alert('Location not found'); return; }
      lat = j.lat; lng = j.lng;
    }
    const type = document.getElementById('typeSelect').value;
    const json = await searchNearby(lat,lng,type);
    renderResults(json, lat, lng);
  });

  function clearMarkers(){ markers.forEach(m=>map.removeLayer(m)); markers=[]; }

  function renderResults(json,userLat,userLng){
    const resultsDiv = document.getElementById('results'); resultsDiv.innerHTML = '';
    clearMarkers();
    if(!json.results || json.results.length == 0){ resultsDiv.innerHTML = '<p>No results nearby.</p>'; return; }
    json.results.forEach((place, idx)=>{
      const item = document.createElement('div'); item.className='p-2 result-item border-bottom';
      item.innerHTML = `<b>${place.name}</b><br><small>${place.address||''}</small><br><small>Rating: ${place.rating||'N/A'}</small>`;
      item.onclick = ()=> { showDetails(place); }
      resultsDiv.appendChild(item);

      const marker = L.marker([place.lat, place.lng]).addTo(map).bindPopup(place.name);
      markers.push(marker);
    });
    map.setView([userLat,userLng],13);
  }

  async function showDetails(place){
    const r = await fetch('/api/place_details', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ place_id: place.osm_id })
    });
    const j = await r.json();
    const html = `
      <div class="card p-3">
        <h5>${j.name}</h5>
        <p>${j.address||''}</p>
        <p>Phone: ${j.phone||'N/A'}</p>
        <p>Website: ${j.website ? '<a href="'+j.website+'" target="_blank">'+j.website+'</a>' : 'N/A'}</p>
        <div>
          <button class="btn btn-sm btn-outline-primary" onclick="window.open('https://www.openstreetmap.org/?mlat=${j.lat}&mlon=${j.lng}#map=18/${j.lat}/${j.lng}','_blank')">Open in OSM</button>
        </div>
      </div>
    `;
    document.getElementById('detailCard').innerHTML = html;
  }

  async function getDirections(destLat,destLng){
    // open OSM directions site or fallback to Google Maps
    const url = `https://www.openstreetmap.org/directions?to=${destLat}%2C${destLng}`;
    window.open(url,'_blank');
  }
</script>
{% endif %}
</body>
</html>
"""

# -------------------------
# Server-side helpers & endpoints
# -------------------------

geolocator = Nominatim(user_agent="india_hospital_finder", timeout=10)

@app.route("/", methods=["GET"])
def index():
    return render_template_string(TEMPLATE, map_provider=MAP_PROVIDER, google_api_key=GOOGLE_API_KEY)

@app.route("/api/geocode", methods=["POST"])
def api_geocode():
    data = request.get_json() or {}
    q = data.get("q","").strip()
    if not q:
        return jsonify({"ok": False, "error": "Missing query"})
    try:
        if GOOGLE_API_KEY:
            # Use Google Geocoding API
            url = f"https://maps.googleapis.com/maps/api/geocode/json"
            r = requests.get(url, params={"address": q, "key": GOOGLE_API_KEY, "region": "in"})
            j = r.json()
            if j.get("status") == "OK":
                loc = j["results"][0]["geometry"]["location"]
                return jsonify({"ok": True, "lat": loc["lat"], "lng": loc["lng"], "address": j["results"][0]["formatted_address"]})
            return jsonify({"ok": False, "error": "geocode_failed", "raw": j})
        else:
            loc = geolocator.geocode(q + ", India")
            if not loc: return jsonify({"ok": False, "error": "not_found"})
            return jsonify({"ok": True, "lat": loc.latitude, "lng": loc.longitude, "address": loc.address})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/search_nearby", methods=["POST"])
def api_search_nearby():
    """
    Request JSON: { lat, lng, type }
    If GOOGLE_API_KEY present: use Places Nearby Search (ranked by distance/rating).
    Else: use Overpass to query OSM 'amenity=hospital/clinic/pharmacy' within a radius.
    """
    data = request.get_json() or {}
    lat = data.get("lat")
    lng = data.get("lng")
    typ = data.get("type", "hospital")
    if lat is None or lng is None:
        return jsonify({"ok": False, "error": "missing_coords"}), 400

    try:
        if GOOGLE_API_KEY:
            # Map our typ to Google place types or keywords
            keyword = "hospital" if typ in ["hospital","all"] else ("clinic" if typ=="clinic" else typ)
            url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            params = {
                "key": GOOGLE_API_KEY,
                "location": f"{lat},{lng}",
                "radius": 20000,  # 20 km radius; adjust as needed for coverage
                "keyword": keyword,
            }
            r = requests.get(url, params=params)
            j = r.json()
            results = []
            for p in j.get("results", []):
                loc = p.get("geometry", {}).get("location", {})
                results.append({
                    "name": p.get("name"),
                    "address": p.get("vicinity"),
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                    "rating": p.get("rating"),
                    "place_id": p.get("place_id"),
                })
            return jsonify({"ok": True, "results": results})
        else:
            # Overpass query for hospital/clinic/pharmacy around point
            # convert type filter
            tag = "hospital"
            if typ=="clinic": tag="clinic"
            elif typ=="pharmacy": tag="pharmacy"
            elif typ=="mental_health": tag="hospital"
            # Overpass QL
            overpass = """
            [out:json][timeout:25];
            (
              node["amenity"~"hospital|clinic|pharmacy"](around:{radius},{lat},{lng});
              way["amenity"~"hospital|clinic|pharmacy"](around:{radius},{lat},{lng});
              relation["amenity"~"hospital|clinic|pharmacy"](around:{radius},{lat},{lng});
            );
            out center 25;
            """
            q = overpass.format(radius=20000, lat=lat, lng=lng)
            r = requests.post("https://overpass-api.de/api/interpreter", data=q, timeout=30)
            data = r.json()
            results = []
            for el in data.get("elements", []):
                if el.get("type") == "node":
                    el_lat = el.get("lat")
                    el_lon = el.get("lon")
                else:
                    center = el.get("center", {})
                    el_lat = center.get("lat"); el_lon = center.get("lon")
                name = el.get("tags", {}).get("name") or el.get("tags", {}).get("operator") or "Unknown"
                addr = ", ".join(v for k,v in el.get("tags", {}).items() if k.startswith("addr:") ) or None
                results.append({
                    "name": name,
                    "address": addr,
                    "lat": el_lat,
                    "lng": el_lon,
                    "rating": None,
                    "osm_id": el.get("id"),
                })
            return jsonify({"ok": True, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/place_details", methods=["POST"])
def api_place_details():
    data = request.get_json() or {}
    place_id = data.get("place_id")
    # For OSM we accept osm_id as place_id and return tags
    try:
        if GOOGLE_API_KEY and place_id:
            url = "https://maps.googleapis.com/maps/api/place/details/json"
            r = requests.get(url, params={"key": GOOGLE_API_KEY, "place_id": place_id, "fields":"name,formatted_address,formatted_phone_number,website,rating,geometry"})
            j = r.json()
            if j.get("status")=="OK":
                res = j["result"]
                geometry = res.get("geometry", {}).get("location", {})
                return jsonify({
                    "ok": True,
                    "name": res.get("name"),
                    "address": res.get("formatted_address"),
                    "phone": res.get("formatted_phone_number"),
                    "website": res.get("website"),
                    "rating": res.get("rating"),
                    "lat": geometry.get("lat"),
                    "lng": geometry.get("lng")
                })
            return jsonify({"ok": False, "error": j}), 400
        else:
            osm_id = data.get("place_id") or data.get("osm_id")
            if not osm_id:
                return jsonify({"ok": False, "error": "missing_id"}), 400
            # For Overpass/OSM lookup use Nominatim reverse or lookup
            # Try Nominatim lookup by OSM id (format: type/id)
            # We'll attempt to use Nominatim search by osm_id for simplicity
            url = "https://nominatim.openstreetmap.org/search"
            r = requests.get(url, params={"osm_id": osm_id, "format":"json", "limit":1}, headers={"User-Agent":"india_hospital_finder"})
            j = r.json()
            if j:
                el = j[0]
                return jsonify({"ok": True, "name": el.get("display_name"), "address": el.get("display_name"), "phone": None, "website": None, "lat": float(el.get("lat")), "lng": float(el.get("lon"))})
            return jsonify({"ok": False, "error": "not_found"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/directions", methods=["POST"])
def api_directions():
    """
    If Google key exists, call Directions API and return a google maps url for navigation
    Otherwise return OSM link
    """
    data = request.get_json() or {}
    dest = data.get("dest")
    if not dest:
        return jsonify({"ok": False, "error": "missing_dest"}), 400
    # best-effort: use user's geocoded center (we don't maintain user session) -> client should open google maps.
    try:
        if GOOGLE_API_KEY:
            # return a google maps web directions URL (safer than returning raw API polyline)
            lat = dest.get("lat"); lng = dest.get("lng")
            url = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
            return jsonify({"ok": True, "google_maps_url": url})
        else:
            lat = dest.get("lat"); lng = dest.get("lng")
            url = f"https://www.openstreetmap.org/directions?to={lat}%2C{lng}"
            return jsonify({"ok": True, "navigation_url": url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug False in production
    app.run(host="0.0.0.0", port=port, debug=False)
