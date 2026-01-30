# --- IMPORTS NECESARIOS ---
import streamlit as st
import pandas as pd
import numpy as np
import json
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import unicodedata
import hashlib
import colorsys
from io import BytesIO

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Visualizador de Riesgos", page_icon="🗺️", layout="wide")

# --- FUNCIONES AUXILIARES ---

def limpiar_texto(texto):
    if not isinstance(texto, str): return texto
    try:
        texto_limpio = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('utf-8').lower().strip()
        if texto_limpio.startswith('deslizamiento'): return 'deslizamiento de tierra'
        return texto_limpio
    except: return str(texto).lower().strip()

def obtener_centroide(feature):
    """Calcula el centro del polígono para etiquetas"""
    try:
        geom = feature.get("geometry", {})
        gtype, coords = geom.get("type"), geom.get("coordinates", [])
        if gtype == "Polygon": poly = coords[0]
        elif gtype == "MultiPolygon": poly = max([p[0] for p in coords], key=len, default=[])
        else: return None
        if not poly: return None
        lons, lats = zip(*poly)
        return (sum(lats)/len(lats), sum(lons)/len(lons))
    except: return None

def generar_color_categoria(texto, index):
    """Genera colores distintivos para cada TIPO de incidente"""
    # Paleta manual de colores fuertes para los primeros tipos
    paleta = [
        '#E74C3C', # Rojo
        '#3498DB', # Azul
        '#F1C40F', # Amarillo
        '#9B59B6', # Morado
        '#2ECC71', # Verde
        '#1ABC9C', # Turquesa
        '#E91E63', # Rosa
        '#34495E', # Azul oscuro
        '#D35400', # Calabaza
        '#7F8C8D'  # Gris
    ]
    if index < len(paleta): return paleta[index]
    
    # Generar color aleatorio consistente para tipos extra
    h = int(hashlib.sha256(str(texto).encode()).hexdigest(), 16)
    hue = ((h % 1000)/1000.0 + (index * 0.618)) % 1.0
    r,g,b = colorsys.hls_to_rgb(hue, 0.5, 0.7)
    return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))

def color_gradiente(valor, maximo):
    """Escala de naranjas para la densidad"""
    if maximo == 0 or valor == 0: return '#ffffff'
    paleta = ['#FFF3E0', '#FFE0B2', '#FFCC80', '#FFB74D', '#FFA726', '#FF9800', '#FB8C00', '#F57C00', '#EF6C00', '#E65100']
    ratio = valor / maximo
    if ratio > 1: ratio = 1
    idx = int(ratio * (len(paleta)-1))
    return paleta[idx]

def agregar_leyenda_combinada(mapa, items_tipos, mostrar_gradiente=False):
    """Crea una leyenda que explica los colores de los puntos"""
    
    html = """
    <div style="position: fixed; bottom: 30px; left: 30px; width: 230px; max-height: 350px; 
    overflow-y: auto; z-index:9999; background: white; border: 2px solid grey; border-radius: 8px; padding: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
    """
    
    # 1. Sección de Tipos (Puntos)
    html += '<b style="font-size:14px; border-bottom: 1px solid #ccc; display:block; margin-bottom:5px;">Tipos de Incidente</b>'
    for txt, col in items_tipos.items():
        html += f'<div style="margin:3px 0; font-size:12px; display:flex; align-items:center;"><span style="background:{col};width:10px;height:10px;display:inline-block;margin-right:8px;border-radius:50%;border:1px solid #333;"></span>{txt.title()}</div>'
    
    # 2. Sección de Gradiente (Fondo) - Si aplica
    if mostrar_gradiente:
        html += '<div style="margin-top:10px; border-top:1px solid #ccc; padding-top:5px;">'
        html += '<b style="font-size:12px;">Intensidad (Fondo Colonia)</b>'
        html += '<div style="background: linear-gradient(to right, #FFF3E0, #E65100); height: 10px; width: 100%; border:1px solid #ccc; margin-top:3px;"></div>'
        html += '<div style="display:flex; justify-content:space-between; font-size:10px;"><span>Baja</span><span>Alta</span></div>'
        html += '</div>'

    html += "</div>"
    mapa.get_root().html.add_child(folium.Element(html))

# --- FUNCIÓN PRINCIPAL DEL MAPA ---

def crear_mapa(df, gj_data, config, opciones):
    try:
        centro = [df[config['lat']].mean(), df[config['lon']].mean()]
        m = folium.Map(location=centro, zoom_start=13, tiles="CartoDB positron", control_scale=True)

        # 1. Definir Colores de Tipos (Categorías)
        tipos = sorted(df[config['tip']].unique())
        colores_tipos = {t: generar_color_categoria(t, i) for i, t in enumerate(tipos)}
        
        # Conteo para el degradado
        conteo_colonia = df[config['col']].value_counts().to_dict()
        max_val = max(conteo_colonia.values()) if conteo_colonia else 1

        # 2. Capa Polígonos (Fondo)
        def estilo(feature):
            nom = feature['properties'].get(config['c_geo'], '') 
            if opciones['gradiente']:
                val = conteo_colonia.get(nom, 0)
                # Usamos colores naranjas para el relleno
                color_relleno = color_gradiente(val, max_val)
                # Borde sutil
                return {'fillColor': color_relleno, 'color': '#FF8F00', 'weight': 1, 'fillOpacity': 0.6 if val > 0 else 0.1}
            else:
                return {'fillColor': '#ffffff', 'color': '#bdc3c7', 'weight': 1, 'fillOpacity': 0.1}

        # Preparar GeoJSON
        nombres_etiquetas = {}
        for f in gj_data['features']:
            orig = f['properties'].get(config['c_geo_raw'])
            clean = limpiar_texto(orig)
            f['properties'][config['c_geo']] = clean 
            f['properties']['_count'] = conteo_colonia.get(clean, 0)
            if clean: nombres_etiquetas[clean] = orig

        folium.GeoJson(
            gj_data,
            name="Colonias (Fondo)",
            style_function=estilo,
            tooltip=folium.GeoJsonTooltip(
                fields=[config['c_geo_raw'], '_count'], 
                aliases=['Colonia:', 'Total Reportes:'], 
                localize=True
            )
        ).add_to(m)

        # 3. Capa Puntos (Incidentes) - SIEMPRE VISIBLE Y COLOREADA
        # Nota: Show=True asegura que se vean encima del degradado
        fg_puntos = folium.FeatureGroup(name="Incidentes (Puntos)", show=True)
        
        for _, row in df.iterrows():
            try:
                tipo = row[config['tip']]
                color = colores_tipos.get(tipo, '#333')
                
                popup_content = f"""
                <div style="width:200px; font-family:sans-serif;">
                    <b style="color:{color}; font-size:14px;">{tipo.upper()}</b><br>
                    <div style="background-color:{color}; height:2px; width:100%; margin:3px 0;"></div>
                    <b>Ubicación:</b> {row[config['col']].title()}<br>
                    <b>Fecha:</b> {row[config['fec']].strftime('%d/%m/%Y')}<br>
                </div>
                """
                
                folium.CircleMarker(
                    [row[config['lat']], row[config['lon']]],
                    radius=6, # Un poco más grandes para que destaquen sobre el naranja
                    color='white', # Borde blanco para separar del fondo
                    weight=1.5,
                    fill=True,
                    fill_color=color, # COLOR CATEGÓRICO
                    fill_opacity=1.0,
                    popup=folium.Popup(popup_content, max_width=250), 
                    tooltip=f"{tipo.title()}"
                ).add_to(fg_puntos)
            except: continue
        m.add_child(fg_puntos)

        # 4. Etiquetas de Nombres (Opcional en menú capas)
        fg_nombres = folium.FeatureGroup(name="Etiquetas Nombres", show=False)
        for f in gj_data['features']:
            centro = obtener_centroide(f)
            nombre = f['properties'].get(config['c_geo'])
            if centro and nombre:
                display = nombres_etiquetas.get(nombre, nombre).title()
                folium.Marker(
                    location=centro,
                    icon=folium.DivIcon(html=f'<div style="font-size:10px; font-weight:bold; color:#555; text-shadow:1px 1px 0 #fff;">{display}</div>')
                ).add_to(fg_nombres)
        m.add_child(fg_nombres)

        # 5. Capa Calor (Opcional)
        if opciones['calor']:
            heat_data = [[row[config['lat']], row[config['lon']]] for _, row in df.iterrows()]
            HeatMap(heat_data, radius=15, blur=12, name="Mapa de Calor").add_to(m)

        # 6. LEYENDA (Controlada)
        if opciones['leyenda']:
            # Pasamos los colores de los tipos Y el estado del gradiente
            agregar_leyenda_combinada(m, colores_tipos, mostrar_gradiente=opciones['gradiente'])

        folium.LayerControl(collapsed=True).add_to(m)
        return m

    except Exception as e:
        st.error(f"Error generando mapa: {e}")
        return None

# --- INTERFAZ STREAMLIT ---

st.title("🗺️ Visualizador de Riesgos")

if 'procesado' not in st.session_state: st.session_state.procesado = False

with st.sidebar:
    st.header("1. Carga de Datos")
    f_data = st.file_uploader("Excel/CSV Incidentes", type=['xlsx','csv'])
    f_geo = st.file_uploader("GeoJSON Colonias", type=['geojson','json'])

    if f_data and f_geo:
        try:
            if f_data.name.endswith('xlsx'): df_raw = pd.read_excel(f_data)
            else: df_raw = pd.read_csv(f_data)
            gj = json.load(f_geo)
            
            st.subheader("Configuración")
            cols = df_raw.columns.tolist()
            c_lat = st.selectbox("Latitud", cols)
            c_lon = st.selectbox("Longitud", cols)
            c_col = st.selectbox("Colonia (Excel)", cols)
            c_tip = st.selectbox("Tipo Incidente", cols)
            c_fec = st.selectbox("Fecha", cols)
            
            props = list(gj['features'][0]['properties'].keys())
            c_geo_raw = st.selectbox("Colonia (GeoJSON)", props)

            if st.button("Procesar Datos"):
                df = df_raw.copy()
                df[c_lat] = pd.to_numeric(df[c_lat], errors='coerce')
                df[c_lon] = pd.to_numeric(df[c_lon], errors='coerce')
                df[c_fec] = pd.to_datetime(df[c_fec], errors='coerce')
                df[c_col] = df[c_col].apply(limpiar_texto)
                df[c_tip] = df[c_tip].apply(limpiar_texto)
                df = df.dropna(subset=[c_lat, c_lon])
                
                st.session_state.df = df
                st.session_state.gj = gj
                st.session_state.config = {
                    'lat': c_lat, 'lon': c_lon, 'col': c_col, 
                    'tip': c_tip, 'fec': c_fec, 
                    'c_geo': 'colonia_clean', 
                    'c_geo_raw': c_geo_raw
                }
                st.session_state.procesado = True
                st.rerun()
        except Exception as e: st.error(f"Error: {e}")

if st.session_state.procesado:
    df = st.session_state.df
    gj = st.session_state.gj
    cfg = st.session_state.config

    col1, col2 = st.columns([1, 4])
    
    with col1:
        st.subheader("Filtros")
        all_tips = sorted(df[cfg['tip']].unique())
        sel_tips = st.multiselect("Tipos", all_tips, default=all_tips)
        
        st.markdown("---")
        st.subheader("Capas")
        opt_gradiente = st.checkbox("🔶 Fondo Colonias (Densidad)", value=True, help="Colorea el fondo de las colonias naranja según la cantidad total.")
        opt_calor = st.checkbox("🔥 Mapa de Calor (Difuso)", value=False)
        opt_leyenda = st.checkbox("📝 Ver Leyenda Detallada", value=True)

    with col2:
        df_show = df[df[cfg['tip']].isin(sel_tips)]
        
        if not df_show.empty:
            mapa = crear_mapa(
                df_show, gj, cfg, 
                opciones={'gradiente': opt_gradiente, 'calor': opt_calor, 'leyenda': opt_leyenda}
            )
            st_folium(mapa, width="100%", height=650, returned_objects=[])
            
            buffer = BytesIO()
            mapa.save(buffer, close_file=False)
            st.download_button("💾 Descargar HTML", buffer.getvalue(), "mapa.html", "text/html")
        else:
            st.warning("No hay datos visibles.")
else:
    st.info("Por favor carga los archivos.")
