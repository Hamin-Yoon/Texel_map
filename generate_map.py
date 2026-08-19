import folium
from folium import FeatureGroup, LayerControl, Element
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import time

def geocode_addresses(df):
    """Fills in missing latitude and longitude using geopy."""
    geolocator = Nominatim(user_agent="texel_map_builder")
    # Rate limiter ensures we respect OpenStreetMap free service limits (1 sec delay)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    
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
    # 1. Load Data
    df = pd.read_csv("places.csv")
    df = geocode_addresses(df)

    # 2. Base Map centered on Texel
    texel_map = folium.Map(
        location=[53.0583, 4.8018], 
        zoom_start=12, 
        tiles="CartoDB positron"
    )

    # 3. Color Palette & Category Config
    category_colors = {
        'Galerieën': 'purple',
        'Natuur': 'green',
        'Bezienswaardigheden': 'red',
        'Restaurants': 'orange',
        'Sport & Cultuur': 'blue'
    }

    # 4. Create Dynamic Categories (Feature Groups) FIRST
    categories = df['category'].dropna().unique()
    feature_groups = {}

    for cat in categories:
        fg = FeatureGroup(name=cat)
        fg.add_to(texel_map)
        feature_groups[cat] = fg

    # 5. Build HTML Buttons and JavaScript Dynamically via Python
    buttons_html = ""
    js_clicks = ""
    map_id = texel_map.get_name() # Gets Folium's internal JS map variable

    for cat, fg in feature_groups.items():
        layer_id = fg.get_name() # Gets Folium's internal JS layer variable
        
        # Create a button for each category
        buttons_html += f'''
        <button id="btn_{layer_id}" class="cat-btn">
          <i class="fa-solid fa-eye"></i> {cat}
        </button>
        '''
        
        # Write the JS to toggle this exact layer
        js_clicks += f'''
        document.getElementById("btn_{layer_id}").onclick = function() {{
            if ({map_id}.hasLayer({layer_id})) {{
                {map_id}.removeLayer({layer_id});
                this.classList.add('inactive');
                this.innerHTML = '<i class="fa-solid fa-eye-slash"></i> {cat}';
            }} else {{
                {map_id}.addLayer({layer_id});
                this.classList.remove('inactive');
                this.innerHTML = '<i class="fa-solid fa-eye"></i> {cat}';
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
        color = category_colors.get(cat, 'cadetblue')
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
        category_config = {
            'Galerieën': {'color': 'purple', 'icon': 'palette', 'prefix': 'fa'},
            'Gallery-route1': {'color': 'darkpurple', 'icon': 'route', 'prefix': 'fa'},
            'boetje': {'color': 'orange', 'icon': 'home', 'prefix': 'fa'},
            'vogelkijkpunt': {'color': 'green', 'icon': 'binoculars', 'prefix': 'fa'},
            'Natuur': {'color': 'darkgreen', 'icon': 'tree', 'prefix': 'fa'},
            'Bezienswaardigheden': {'color': 'red', 'icon': 'camera', 'prefix': 'fa'}
        }

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

    
    # 8. Save output
    texel_map.save("texel_map.html")
    print("Successfully generated texel_map.html!")

if __name__ == "__main__":
    build_map()