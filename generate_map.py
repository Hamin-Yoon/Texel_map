import folium
from folium import FeatureGroup, LayerControl, Element
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import time
import gpxpy
import gpxpy.gpx
import json

def geocode_addresses(df):
    """Fills in missing latitude and longitude using geopy."""
    geolocator = Nominatim(user_agent="texel_map_builder")
    # Rate limiter ensures we respect OpenStreetMap free service limits (1 sec delay)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=0.1)
    
    updated = False
    for index, row in df.iterrows():
        # Only geocode if latitude/longitude are missing
        if pd.isna(row['latitude']) or pd.isna(row['longitude']):
            address = row['address']
            print(f"Geocoding address: {address}...")
            try:
                location = geocode(address)
                if location:
                    df.at[index, 'latitude'] = location.latitude
                    df.at[index, 'longitude'] = location.longitude
                    updated = True
                    print(f"  -> Found: {location.latitude}, {location.longitude}")
                else:
                    print(f"  -> Could not find coordinates for: {address}")
            except Exception as e:
                print(f"  -> Error geocoding {address}: {e}")
            time.sleep(1)

    # Save the updated coordinates back to CSV so we don't re-fetch them every time
    if updated:
        df.to_csv("places.csv", index=False)
        print("Updated places.csv with new coordinates!")

    return df

def build_map():
    # 1. Load Data from Google Sheets
    # Change '/edit?gid=' to '/export?format=csv&gid='
    sheet_url = "https://docs.google.com/spreadsheets/d/1qEE9cMS7sf_Apa-tP8KOQt81zJhOpeu_L2RxPYZov1Q/export?format=csv&gid=716767332"
    df = pd.read_csv(sheet_url)

    # 1b. Automatically fill in missing columns with empty data so the script doesn't crash
    missing_columns = ['latitude', 'longitude', 'description_nl', 'description_en', 'name_nl', 'name_en']
    for col in missing_columns:
        if col not in df.columns:
            df[col] = pd.NA
            
    # 1c. Fallback: Use the basic 'name' column for both NL and EN popups if they are empty
    if 'name' in df.columns:
        df['name_nl'] = df['name_nl'].fillna(df['name'])
        df['name_en'] = df['name_en'].fillna(df['name'])

    # The geocoder will now see the empty 'latitude'/'longitude' columns and fill them!
    df = geocode_addresses(df)
    
    # 2. Base Map centered on Texel
    texel_map = folium.Map(
        location=[53.0583, 4.8018], 
        zoom_start=11, 
        tiles="CartoDB positron"
    )

    # 4. Create Dynamic Categories (Feature Groups) FIRST
    categories = df['category'].dropna().unique()
    feature_groups = {}

    for cat in categories:
        fg = FeatureGroup(name=cat)
        fg.add_to(texel_map)
        feature_groups[cat] = fg

    import json
    try:
        with open("biodiversity_data.json", "r") as f:
            bio_data = json.load(f)
            top_n_crs = bio_data["top_n_crs"]
            top_n_div = bio_data["top_n_div"]
    except FileNotFoundError:
        top_n_crs, top_n_div = {}, {}

    bio_layer = folium.FeatureGroup(name="Biodiversity Intensity", show=False)

    for idx_str, coords in top_n_crs.items():
        score = top_n_div[idx_str] 
        lon, lat = coords[0], coords[1]
        folium.CircleMarker(
            location=[lat, lon],
            radius=score * 1.5,       
            color="crimson",
            fill=True,
            fill_color="red",
            fill_opacity=0.6,
            popup=f"<b>Biodiversity Spot</b><br>Unique Species: {score}"
        ).add_to(bio_layer)

    bio_layer.add_to(texel_map)
    # ADD IT TO THE DICTIONARY SO THE BUTTON LOOP SEES IT
    feature_groups["Biodiversity Intensity"] = bio_layer

    route_fg = FeatureGroup(name="Route Suggestie")
    route_fg.add_to(texel_map)
    feature_groups["Route Suggestie"] = route_fg # Adds it to your custom UI menu

    # 2. Parse the GPX file
    with open('route.gpx', 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    # 3. Extract the coordinates
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append(tuple([point.latitude, point.longitude]))

    # 4. Draw the line on the map
    folium.PolyLine(
        locations=points,
        color="blue",
        weight=5,
        opacity=0.7,
        tooltip="Suggested Route"
    ).add_to(route_fg)

    category_config = {
                'Galerieën': {'color': 'purple', 'icon': 'palette', 'prefix': 'fa'},
                'Gallery-route1': {'color': 'darkpurple', 'icon': 'route', 'prefix': 'fa'},
                'boetje': {'color': 'orange', 'icon': 'home', 'prefix': 'fa'},
                'vogelkijkpunt': {'color': 'green', 'icon': 'binoculars', 'prefix': 'fa'},
                'Natuur': {'color': 'darkgreen', 'icon': 'tree', 'prefix': 'fa'},
                'Bezienswaardigheden': {'color': 'red', 'icon': 'camera', 'prefix': 'fa'}
            }
    folium_to_css = {
        'purple': '#d9534f', 'darkpurple': '#5B396B', 'orange': '#F39C12',
        'green': '#72B026', 'darkgreen': '#728224', 'red': '#D33D2A',
        'blue': '#38AADD', 'cadetblue': '#436978'
    }
    # 5. Build HTML Buttons and JavaScript Dynamically via Python
    buttons_html = ""
    js_clicks = ""
    map_id = texel_map.get_name() # Gets Folium's internal JS map variable
    category_translations = {
        "Galerieën": "Galleries",
        "Gallery-route1": "Gallery Route 1",
        "boetje": "Sheep Barns",
        "vogelkijkpunt": "Bird Observatories",
        "Route Suggestie": "Suggested Route",
        "Biodiversity Intensity": "Biodiversity"
    }
    for cat, fg in feature_groups.items():
        layer_id = fg.get_name() # Gets Folium's internal JS layer variable
        cat_en = category_translations.get(cat, cat)
        config = category_config.get(cat, {'color': 'cadetblue', 'icon': 'circle', 'prefix': 'fa'})
        btn_color = folium_to_css.get(config['color'], '#38AADD')
        buttons_html += f'''
        <button id="btn_{layer_id}" class="cat-btn active" style="border-left: 4px solid {btn_color};">
            <i class="fa-solid fa-{config['icon']}" style="color: {btn_color}; width: 22px; text-align: center; font-size: 14px;"></i> 
            <span class="lang-nl" style="flex-grow: 1; margin-left: 5px;">{cat}</span>
            <span class="lang-en" style="flex-grow: 1; margin-left: 5px;">{cat_en}</span>
            <i class="fa-solid fa-toggle-on toggle-icon" style="color: #28a745; font-size: 18px;"></i>
        </button>
        '''
        
        # Write the JS to toggle this exact layer
        js_clicks += f'''
        document.getElementById("btn_{layer_id}").onclick = function() {{
            let toggleIcon = this.querySelector('.toggle-icon');
            if ({map_id}.hasLayer({layer_id})) {{
                {map_id}.removeLayer({layer_id});
                this.classList.add('inactive');
                toggleIcon.className = "fa-solid fa-toggle-off toggle-icon";
                toggleIcon.style.color = "#ccc";
            }} else {{
                {map_id}.addLayer({layer_id});
                this.classList.remove('inactive');
                toggleIcon.className = "fa-solid fa-toggle-on toggle-icon";
                toggleIcon.style.color = "#28a745";
            }}
        }};
        '''

    # 6. Inject the Custom UI with our generated buttons
    custom_ui = """
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
      body.lang-nl .content-nl { display: block; }
      body.lang-nl .content-en { display: none; }
      body.lang-en .content-nl { display: none; }
      body.lang-en .content-en { display: block; }
      /* New rules for the menu buttons */
      body.lang-nl .lang-en { display: none !important; }
      body.lang-en .lang-nl { display: none !important; }
      .category-panel { position: absolute; top: 20px; left: 60px; z-index: 9999; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); font-family: sans-serif; min-width: 180px; max-width: 250px; }
      .category-panel h4 { margin: 0 0 10px 0; font-size: 14px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
      .cat-btn { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 10px; margin-bottom: 6px; border: 1px solid #007bff; border-radius: 5px; background: #e7f1ff; color: #007bff; cursor: pointer; font-size: 12px; font-weight: bold; text-align: left; transition: all 0.2s; }
      .cat-btn.inactive { background: #f8f9fa; border-color: #ccc; color: #777; }
      .lang-switcher { position: absolute; top: 20px; right: 20px; z-index: 9999; background: white; padding: 10px 15px; border: 2px solid rgba(0,0,0,0.2); border-radius: 8px; cursor: pointer; font-family: sans-serif; font-weight: bold; }
      .popup-btn { display: inline-block; margin-top: 8px; padding: 5px 10px; background-color: #007bff; color: white !important; text-decoration: none; border-radius: 4px; font-size: 12px; }
    </style>

    <div class="category-panel">
      <h4 class="content-nl">Filter Categorieën</h4>
      <h4 class="content-en">Filter Categories</h4>
      <div id="category-buttons">
        """ + buttons_html + """
      </div>
    </div>
    <button id="langBtn" class="lang-switcher" onclick="toggleLanguage()">🇬🇧 Switch to English</button>

    <script>
      function toggleLanguage() {
        const body = document.body;
        if (body.classList.contains('lang-nl')) {
          body.classList.remove('lang-nl'); body.classList.add('lang-en');
          document.getElementById('langBtn').innerText = "🇳🇱 Bekijk in het Nederlands";
        } else {
          body.classList.remove('lang-en'); body.classList.add('lang-nl');
          document.getElementById('langBtn').innerText = "🇬🇧 Switch to English";
        }
      }
      document.body.classList.add('lang-nl');

      // Wait a fraction of a second for Folium to load, then attach our exact click events
      window.addEventListener("load", function() {
        setTimeout(function() {
            """ + js_clicks + """
        }, 500);
      });
    </script>
    """
    texel_map.get_root().html.add_child(Element(custom_ui))

    # 6. Loop through items in CSV and add Markers
    for _, row in df.iterrows():
        if pd.isna(row['latitude']) or pd.isna(row['longitude']):
            continue # Skip if geocoding failed

        cat = row['category']
        website_url = row['website'] if pd.notna(row['website']) else "#"

        popup_html = f"""
        <div style="width: 220px; font-family: sans-serif;">
            <div class="content-nl">
                <h4 style="margin: 0 0 5px 0;">{row['name_nl']}</h4>
                <p style="margin: 0 0 5px 0; font-size: 13px;">{row['description_nl']}</p>
                <p style="margin: 0 0 8px 0; font-size: 11px; color: #666;">📍 {row['address']}</p>
                <a href="{website_url}" target="_blank" class="popup-btn">Meer informatie (texel.net)</a>
            </div>
            <div class="content-en">
                <h4 style="margin: 0 0 5px 0;">{row['name_en']}</h4>
                <p style="margin: 0 0 5px 0; font-size: 13px;">{row['description_en']}</p>
                <p style="margin: 0 0 8px 0; font-size: 11px; color: #666;">📍 {row['address']}</p>
                <a href="{website_url}" target="_blank" class="popup-btn">More details (texel.net)</a>
            </div>
        </div>
        """
        

# 2. Inside your loop, pull these styling options dynamically:
        config = category_config.get(cat, {'color': 'blue', 'icon': 'info-circle', 'prefix': 'fa'})
        folium.Marker(
            location=[row['latitude'], row['longitude']],
            popup=folium.Popup(popup_html, max_width=300),
            # Apply custom icon, color, and icon library
            icon=folium.Icon(
                color=config['color'], 
                icon=config['icon'], 
                prefix=config['prefix']
            )
        ).add_to(feature_groups[cat])

    try:
        with open("biodiversity_data.json", "r") as f:
            bio_data = json.load(f)
            top_n_crs = bio_data["top_n_crs"]
            top_n_div = bio_data["top_n_div"]
    except FileNotFoundError:
        print("Warning: biodiversity_data.json not found. Run the sampler notebook first.")
        top_n_crs, top_n_div = {}, {}
    bio_layer = folium.FeatureGroup(name="Biodiversity Intensity", show=False)

    # Loop through your Jupyter variables (top_n_crs and top_n_div)
    for idx, coords in top_n_crs.items():
        score = top_n_div[idx] # Get the unique species count for this grid cell
        
        # coords contains [longitude, latitude], but Folium requires [latitude, longitude]
        lon, lat = coords[0], coords[1]
        
        folium.CircleMarker(
            location=[lat, lon],
            radius=score * 1.5,       # Adjust multiplier to make circle radius scale nicely
            color="crimson",
            fill=True,
            fill_color="red",
            fill_opacity=0.6,
            popup=f"<b>Biodiversity Spot #{idx}</b><br>Unique Species: {score}"
        ).add_to(bio_layer)

    # 1. Add the filled layer to the map
    bio_layer.add_to(texel_map)
    # feature_groups["Biodiversity Intensity"] = bio_layer

    # 8. Save output
    texel_map.save("texel_map.html")
    print("Successfully generated texel_map.html!")

if __name__ == "__main__":
    build_map()