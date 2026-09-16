import folium
from folium import FeatureGroup, LayerControl, Element
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import time
import gpxpy
import os
import gpxpy.gpx
import webbrowser  # Add this at the top of generate_map.py
import json
import branca.colormap as cm
from folium.plugins import HeatMap

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
        tiles= "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri"
    )

    # 4. Create Dynamic Categories (Feature Groups) FIRST
    categories = df['category'].dropna().unique()
    feature_groups = {}

    for cat in categories:
        fg = FeatureGroup(name=cat)
        fg.add_to(texel_map)
        feature_groups[cat] = fg

   
    def add_bio_layer(json_file, layer_name, gradient_colors):
        layer = folium.FeatureGroup(name=layer_name, show=False)
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                bio_data = json.load(f)
                top_n_crs = bio_data.get("top_n_crs", {})
                top_n_div = bio_data.get("top_n_div", {})
                details = bio_data.get("details", {}) # JSON에 새로 추가된 상세 데이터
            
            # 1. 히트맵 배경 데이터 생성
            heat_data = []
            for idx_str, coords in top_n_crs.items():
                score = top_n_div[idx_str] 
                lon, lat = coords[0], coords[1]
                heat_data.append([lat, lon, score])

            if heat_data:
                HeatMap(
                    heat_data,
                    radius=25,           # 클릭 영역 확보를 위해 범위를 약간 넓힘
                    blur=15,             
                    max_zoom=13,
                    min_opacity=0.4,
                    gradient=gradient_colors
                ).add_to(layer)

            # 2. 클릭 팝업을 위한 투명 마커(CircleMarker) 생성
            for idx_str, coords in top_n_crs.items():
                lon, lat = coords[0], coords[1]
                obs_list = details.get(idx_str, [])
                
                if not obs_list:
                    continue

                # 팝업 HTML 생성
                popup_html = f"""
                <div style="width: 240px; max-height: 250px; overflow-y: auto; font-family: sans-serif;">
                    <h4 style="margin: 0 0 8px 0; font-size: 13px; color: #333; border-bottom: 2px solid #ddd; padding-bottom: 4px;">
                        <span class="lang-nl">Waargenomen soorten ({len(obs_list)})</span>
                        <span class="lang-en">Observed species ({len(obs_list)})</span>
                    </h4>
                """
                
                for item in obs_list[:15]:  # 상위 15개 항목 표시
                    photo_url = item.get("photo_url", "")
                    img_tag = f'<img src="{photo_url}" style="width:48px; height:48px; object-fit:cover; border-radius:4px;">' if photo_url else '<div style="width:48px; height:48px; background:#eee; border-radius:4px; text-align:center; line-height:48px; font-size:10px; color:#999;">No Image</div>'
                    
                    popup_html += f"""
                    <div style="display: flex; gap: 10px; margin-bottom: 8px; border-bottom: 1px solid #f0f0f0; padding-bottom: 6px; align-items: center;">
                        {img_tag}
                        <div style="flex-grow: 1;">
                            <strong style="font-size: 12px; color: #222; display: block; line-height: 1.2;">{item.get('name', 'Unknown')}</strong>
                            <span style="font-size: 10px; color: #777;">📅 {item.get('date', 'N/A')}</span>
                        </div>
                    </div>
                    """
                
                popup_html += "</div>"

                # 히트맵 상단에 투명 클릭 마커 배치
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=18,
                    color="transparent",      # 테두리 투명
                    fill=True,
                    fill_color="transparent", # 채우기 투명
                    fill_opacity=0.01,         # 마커 클릭 이벤트를 받기 위한 미세 오파시티
                    popup=folium.Popup(popup_html, max_width=280)
                ).add_to(layer)

        except FileNotFoundError:
            print(f"Warning: {json_file} not found.")
            
        layer.add_to(texel_map)
        feature_groups[layer_name] = layer

    bird_gradient = {0.4: "#A7D1E4", 0.7: "#19A7E8", 1.0: "#1519F5"}
    add_bio_layer("biodiversity_data_bird.json", "Biodiversiteit Vogels (sep-2023 - sep-2026)", bird_gradient)

    # Plant Heatmap: Light Green -> Green -> Dark Green
    plant_gradient = {0.4: "#e2f0d9", 0.7: "#78A858", 1.0: "#1e330c"}
    add_bio_layer("biodiversity_data_plant.json", "Biodiversiteit Planten (sep-2023 - sep-2026)", plant_gradient)

    # Load both files as separate layers
    # add_bio_layer("biodiversity_data_bird.json", "Biodiversiteit Vogels (3 jaar)", ['#ffcccc', '#ff0000', '#800000'])
    # # Plant Layer: Light Green -> Dark Forest Green
    # add_bio_layer("biodiversity_data_plant.json", "Biodiversiteit Planten (3 jaar)", ['#e2f0d9', '#385723', '#1e330c'])
    category_config = {
                    'Galerieën': {'color': 'purple', 'icon': 'palette', 'prefix': 'fa'},
                    'Boet': {'color': 'orange', 'icon': 'home', 'prefix': 'fa'},
                    'Vogelkijkpunt': {'color': 'green', 'icon': 'binoculars', 'prefix': 'fa'},
                    'Natuur': {'color': 'darkgreen', 'icon': 'tree', 'prefix': 'fa'},
                    'Museum': {'color': 'black', 'icon': 'museum', 'prefix': 'fa'},
                    'Vuurtoren': {'color': 'red', 'icon': 'tower-observation', 'prefix': 'fa'},
                    'Kijkboet (suggestie)': {'color': 'yellow', 'icon': 'caret-up', 'prefix': 'fa'},
                    'Biodiversiteit Vogels (sep-2023 - sep-2026)': {'color': 'skyblue', 'icon': 'crow', 'prefix': 'fa'},
                    'Biodiversiteit Planten (sep-2023 - sep-2026)': {'color': 'darkgreen', 'icon': 'leaf', 'prefix': 'fa'}
                }
     
        #https://fontawesome.com/search?s=solid
    folium_to_css = {
        'purple': "#cc29d1", 'darkpurple': "#5B376B", 'orange': '#F39C12',
        'green': '#72B026', 'darkgreen': '#728224', 'red': '#D33D2A', 'yellow': "#F1DE2C",
        'blue': '#38AADD', 'skyblue': "#6DCCE8"
    }
    category_translations = {
        "Galerieën": "Galleries",
        "Boet": "Little shed",
        "Natuur": "Nature",
        "Museum": "Museums",
        "Vuurtoren": "Lighthouses",
        "Kijkboet (suggestie)": "Observation Shed (suggestion)",
        "Vogelkijkpunt": "Bird Observatories",
        "Biodiversiteit Vogels (sep-2023 - sep-2026)": "Biodiversity of birds (sep-2023 - sep-2026)",
        "Biodiversiteit Planten (sep-2023 - sep-2026)": "Biodiversity of plants (sep-2023 - sep-2026)"
    }

    route_palette = ["#375360", "#9930B9", "#A7BBDF", "#1627C0", "#7659E8"]
    route_count = 0

    gpx_folder = "gpx"
    if os.path.exists(gpx_folder):
        for filename in sorted(os.listdir(gpx_folder)):
            if filename.lower().endswith(".gpx"):
                route_name = os.path.splitext(filename)[0].replace("_", " ").title()
                gpx_path = os.path.join(gpx_folder, filename)
                
                try:
                    with open(gpx_path, 'r', encoding='utf-8') as gpx_file:
                        gpx = gpxpy.parse(gpx_file)

                    points = []
                    for track in gpx.tracks:
                        for segment in track.segments:
                            for point in segment.points:
                                points.append((point.latitude, point.longitude))

                    if points:
                        # Automatically cycle through route_palette for each route
                        route_color = route_palette[route_count % len(route_palette)]
                        route_count += 1

                        # Store hex color in category_config dynamically while keeping the route icon
                        category_config[route_name] = {
                            'color': route_color, 
                            'icon': 'route', 
                            'prefix': 'fa'
                        }

                        route_fg = FeatureGroup(name=route_name)
                        route_fg.add_to(texel_map)

                        folium.PolyLine(
                            locations=points,
                            color=route_color,
                            weight=5,
                            opacity=0.8,
                            tooltip=route_name
                        ).add_to(route_fg)

                        feature_groups[route_name] = route_fg
                        
                except Exception as e:
                    print(f"Error parsing GPX file {filename}: {e}")

    # 5. Build HTML Buttons and JavaScript Dynamically via Python
# 7. Separate feature layers into 3 panel groups
    cat_fgs = {k: v for k, v in feature_groups.items() if k in categories}
    route_fgs = {k: v for k, v in feature_groups.items() if k not in categories and not k.startswith("Biodiversiteit")}
    bio_fgs = {k: v for k, v in feature_groups.items() if k.startswith("Biodiversiteit")}

    map_id = texel_map.get_name()

    def build_panel_content(fg_dict):
        html = ""
        js = ""
        for cat, fg in fg_dict.items():
            layer_id = fg.get_name()
            cat_en = category_translations.get(cat, cat)
            config = category_config.get(cat, {'color': 'blue', 'icon': 'route', 'prefix': 'fa'})
            btn_color = folium_to_css.get(config['color'], config['color'])

            html += f'''
            <button id="btn_{layer_id}" class="cat-btn active" style="border-left: 4px solid {btn_color};">
                <i class="fa-solid fa-{config['icon']}" style="color: {btn_color}; width: 22px; text-align: center; font-size: 14px;"></i> 
                <span class="lang-nl" style="flex-grow: 1; margin-left: 5px;">{cat}</span>
                <span class="lang-en" style="flex-grow: 1; margin-left: 5px;">{cat_en}</span>
                <i class="fa-solid fa-toggle-on toggle-icon" style="color: #28a745; font-size: 18px;"></i>
            </button>
            '''
            js += f'''
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
        return html, js

    cat_html, cat_js = build_panel_content(cat_fgs)
    route_html, route_js = build_panel_content(route_fgs)
    bio_html, bio_js = build_panel_content(bio_fgs)
    
    js_clicks = cat_js + route_js + bio_js

    # 8. Inject Custom UI with 3 stacked panels
    custom_ui = f"""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
      body.lang-nl .content-nl {{ display: block; }}
      body.lang-nl .content-en {{ display: none; }}
      body.lang-en .content-nl {{ display: none; }}
      body.lang-en .content-en {{ display: block; }}
      body.lang-nl .lang-en {{ display: none !important; }}
      body.lang-en .lang-nl {{ display: none !important; }}
      
      /* 기본 패널 스타일 (데스크톱) */
      .panel-container {{ 
        position: absolute; 
        top: 20px; 
        right: 20px; 
        left: auto;
        z-index: 9999; 
        display: flex; 
        flex-direction: column; 
        gap: 10px; 
        max-height: 90vh; 
        overflow-y: auto;
      }}
      .category-panel {{ 
        background: white; 
        padding: 12px 15px; 
        border-radius: 8px; 
        box-shadow: 0 2px 10px rgba(0,0,0,0.2); 
        font-family: sans-serif; 
        min-width: 180px; 
        max-width: 250px; 
      }}
      .category-panel h4 {{ margin: 0 0 8px 0; font-size: 13px; border-bottom: 1px solid #eee; padding-bottom: 4px; color: #333; }}
      .cat-btn {{ display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; margin-bottom: 5px; border: 1px solid #007bff; border-radius: 5px; background: #e7f1ff; color: #007bff; cursor: pointer; font-size: 12px; font-weight: bold; text-align: left; transition: all 0.2s; }}
      .cat-btn.inactive {{ background: #f8f9fa; border-color: #ccc; color: #777; }}
      
      .lang-switcher {{
        position: absolute; 
        top: 20px; 
        left: 60px; 
        z-index: 9999; 
        background: white; 
        padding: 8px 12px; 
        border: 2px solid rgba(0,0,0,0.2); 
        border-radius: 8px; 
        cursor: pointer; 
        font-family: sans-serif; 
        font-size: 12px;
        font-weight: bold; 
      }}
      .popup-btn {{ display: inline-block; margin-top: 8px; padding: 5px 10px; background-color: #007bff; color: white !important; text-decoration: none; border-radius: 4px; font-size: 12px; }}

      /* 커스텀 범례 수치 스타일 */
      .legend-labels {{ display: flex; justify-content: space-between; font-size: 9px; color: #777; margin-top: 1px; }}

      /* ========================================================= */
      /* 모바일 / 스마트폰 화면 최적화 (화면 폭 600px 이하)         */
      /* ========================================================= */
      @media (max-width: 600px) {{
        .panel-container {{
          top: 10px;
          right: 10px;
          gap: 6px;
          max-height: 80vh;
        }}
        .category-panel {{
          padding: 8px 10px;
          min-width: 140px;
          max-width: 170px;
          border-radius: 6px;
        }}
        .category-panel h4 {{
          font-size: 11px;
          margin-bottom: 5px;
          padding-bottom: 2px;
        }}
        .cat-btn {{
          padding: 4px 6px;
          font-size: 10px;
          gap: 4px;
          margin-bottom: 3px;
        }}
        .cat-btn i {{
          font-size: 11px !important;
          width: 14px !important;
        }}
        .toggle-icon {{
          font-size: 14px !important;
        }}
        .lang-switcher {{
          top: 10px;
          left: 50px;
          padding: 5px 8px;
          font-size: 10px;
          border-width: 1px;
        }}
      }}
    </style>

    <div class="panel-container">
      <div class="category-panel">
        <h4 class="content-nl">Filter Categorieën</h4>
        <h4 class="content-en">Filter Categories</h4>
        {cat_html}
      </div>
      
      <div class="category-panel">
        <h4 class="content-nl">Filter Routes</h4>
        <h4 class="content-en">Filter Routes</h4>
        {route_html}
      </div>
      
      <div class="category-panel">
        <h4 class="content-nl">Biodiversiteit</h4>
        <h4 class="content-en">Biodiversity</h4>
        {bio_html}
        
        <!-- 통합된 패널 내 범례 (수치 + 색상 그라데이션) -->
        <div style="margin-top: 10px; font-size: 11px; color: #555;">
          <!-- 새 범례 -->
          <div style="margin-bottom: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span class="content-nl" style="font-weight: bold;">Vogels Dichtheid:</span>
              <span class="content-en" style="font-weight: bold;">Bird Density:</span>
            </div>
            <div style="height: 8px; width: 100%; border-radius: 4px; background: linear-gradient(to right, #A7D1E4, #19A7E8, #1519F5); margin-top: 3px;"></div>
            <div class="legend-labels">
              <span>0 (Laag)</span>
              <span>50</span>
              <span>100+ (Hoog)</span>
            </div>
          </div>
          
          <!-- 식물 범례 -->
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span class="content-nl" style="font-weight: bold;">Planten Dichtheid:</span>
              <span class="content-en" style="font-weight: bold;">Plant Density:</span>
            </div>
            <div style="height: 8px; width: 100%; border-radius: 4px; background: linear-gradient(to right, #e2f0d9, #78A858, #1e330c); margin-top: 3px;"></div>
            <div class="legend-labels">
              <span>0 (Laag)</span>
              <span>50</span>
              <span>100+ (Hoog)</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <button id="langBtn" class="lang-switcher" onclick="toggleLanguage()">🇬🇧 Switch to English</button>

    <script>
      function toggleLanguage() {{
        const body = document.body;
        if (body.classList.contains('lang-nl')) {{
          body.classList.remove('lang-nl'); body.classList.add('lang-en');
          document.getElementById('langBtn').innerText = "🇳🇱 Bekijk in het Nederlands";
        }} else {{
          body.classList.remove('lang-en'); body.classList.add('lang-nl');
          document.getElementById('langBtn').innerText = "🇬🇧 Switch to English";
        }}
      }}
      document.body.classList.add('lang-nl');

      window.addEventListener("load", function() {{
        setTimeout(function() {{
            {js_clicks}
        }}, 500);
      }});
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

        config = category_config.get(cat, {'color': 'blue', 'icon': 'home', 'prefix': 'fa'})
        if cat in feature_groups:
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.Icon(
                    color=config['color'], 
                    icon=config['icon'], 
                    prefix=config['prefix']
                )
            ).add_to(feature_groups[cat])

    # 8. Save output
    texel_map.save("texel_map.html")
    webbrowser.open("texel_map.html")
    print("Successfully generated texel_map.html!")

if __name__ == "__main__":
    build_map()