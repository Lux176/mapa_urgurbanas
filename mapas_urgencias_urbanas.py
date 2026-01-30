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
    paleta = ['#E74C3C', '#3498DB', '#F1C40F', '#9B59B6', '#2ECC71', '#E67E22', '#1ABC9C', '#34495E']
    if index < len(paleta): return paleta[index]
    h = int(hashlib.sha256(str(texto).encode()).hexdigest(), 16)
    hue = ((h % 1000)/1000.0 + (index * 0.618)) % 1.0
    r,g,b = colorsys.hls_to_rgb(hue, 0.5, 0.7)
    return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))

def color_gradiente(valor, maximo):
    if maximo == 0 or valor == 0: return '#ffffff'
    paleta = ['#FFF3E0', '#FFE0B2', '#FFCC80', '#FFB74D', '#FFA726', '#FF9800', '#FB8C00', '#F57C00', '#EF6C00', '#E65100']
    idx = int((valor/maximo) * (len(paleta)-1))
    return paleta[idx]

def agregar_leyenda_flotante(mapa, items, titulo="Leyenda"):
    html = f"""
    <div style="position: fixed; bottom: 30px; left: 30px; width: 220px; max-height: 300px; 
    overflow-y: auto; z-index:9999; background: white; border: 2px solid grey; border-radius: 8px; padding: 10px;">
    <b>{titulo}</b><br>
    """
    for txt, col in items.items():
        html += f'<div style="margin:3px 0;"><span style="background:{col};width:12px;height:12px;display:inline-block;margin-right:5px;border:1px solid #333;"></span>{txt.title()}</div>'
    html += "</div>"
    mapa.get_root().html.add_child(folium.Element(html))

# --- FUNCIÓN PRINCIPAL DEL MAPA ---

def crear_mapa(df, gj_data, config, opciones):
    """
    opciones es un dict: {'gradiente': bool, 'calor': bool, 'leyenda': bool}
    """
    try:
        centro = [df[config['lat']].mean(), df[config['lon']].mean()]
        m = folium.Map(location=centro, zoom_start=13, tiles="CartoDB positron")

        # 1. Preparar Datos
        tipos = sorted(df[config['tip']].unique())
        colores_tipos = {t: generar_color_categoria(t, i) for i, t in enumerate(tipos)}
        
        conteo_colonia = df[config['col']].value_counts().to_dict()
        max_val = max(conteo_colonia.values()) if conteo_colonia else 1

        # 2. Capa Polígonos (Colonias)
        def estilo(feature):
            nom = feature['properties'].get(config['c_geo'])
            if opciones['gradiente']:
                val = conteo_colonia.get(nom, 0)
                return {
                    'fillColor': color_gradiente(val, max_val),
                    'color': '#d35400' if val > 0 else '#bdc3c7',
                    'weight': 2 if val > 0 else 1,
                    'fillOpacity': 0.7 if val > 0 else 0.1
                }
            else:
                return {'fillColor': '#fff', 'color': '#bdc3c7', 'weight': 1, 'fillOpacity': 0.1}

        # Preparar GeoJSON con nombres limpios para el match
        for f in gj_data['features']:
            orig = f['properties'].get(config['c_geo_raw']) # Usar nombre original del archivo
            clean = limpiar_texto(orig)
            f['properties'][config['c_geo']] = clean # Asignar limpio para tooltip
            f['properties']['_count'] = conteo_colonia.get(clean, 0)

        folium.GeoJson(
            gj_data,
            name="Colonias",
            style_function=estilo,
            tooltip=folium.GeoJsonTooltip(fields=[config['c_geo'], '_count'], aliases=['Colonia:', 'Incidentes:'], localize=True)
        ).add_to(m)

        # 3. Capa Puntos (Incidentes)
        # Si el gradiente está activo, ocultamos puntos por defecto para limpieza visual, pero se pueden activar en el menú capas
        fg_puntos = folium.FeatureGroup(name="Puntos (Reportes)", show=not opciones['gradiente'])
        for _, row in df.iterrows():
            try:
                tipo = row[config['tip']]
                color = colores_tipos.get(tipo, '#333')
                html = f"<b>{tipo.upper()}</b><br>{row[config['col']].title()}<br>{row[config['fec']].date()}"
                folium.CircleMarker(
                    [row[config['lat']], row[config['lon']]],
                    radius=5, color='white', weight=1, fill_color=color, fill_opacity=0.9,
                    popup=folium.Popup(html, max_width=200), tooltip=tipo
                ).add_to(fg_puntos)
            except: continue
        fg_puntos.add_to(m)

        # 4. Capa Mapa de Calor (Heatmap)
        if opciones['calor']:
            heat_data = [[row[config['lat']], row[config['lon']]] for _, row in df.iterrows()]
            fg_calor = folium.FeatureGroup(name="Mapa de Calor", show=True)
            HeatMap(heat_data, radius=15, blur=10).add_to(fg_calor)
            fg_calor.add_to(m)

        # 5. Leyenda
        if opciones['leyenda']:
            if opciones['gradiente']:
                # Leyenda de gradiente (simplificada)
                items_grad = {'Alta Incidencia': '#E65100', 'Media': '#FFA726', 'Baja': '#FFF3E0', 'Sin Reportes': '#FFFFFF'}
                agregar_leyenda_flotante(m, items_grad, "Intensidad (Reportes)")
            else:
                # Leyenda de tipos
                agregar_leyenda_flotante(m, colores_tipos, "Tipos de Incidente")

        # 6. Controles Extra
        folium.LayerControl().add_to(m)
        
        return m

    except Exception as e:
        st.error(f"Error mapa: {e}")
        return None

# --- INTERFAZ ---

st.title("🗺️ Visualizador de Riesgos 2.0")

# Session State para persistencia
if 'procesado' not in st.session_state: st.session_state.procesado = False

with st.sidebar:
    st.header("1. Archivos")
    f_data = st.file_uploader("Excel/CSV Incidentes", type=['xlsx','csv'])
    f_geo = st.file_uploader("GeoJSON Colonias", type=['geojson','json'])

    if f_data and f_geo:
        # Carga Rápida
        try:
            if f_data.name.endswith('xlsx'): df_raw = pd.read_excel(f_data)
            else: df_raw = pd.read_csv(f_data)
            gj = json.load(f_geo)
            
            st.header("2. Columnas")
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
                    'c_geo': 'colonia_limpia', # Nombre interno
                    'c_geo_raw': c_geo_raw     # Nombre original en el archivo
                }
                st.session_state.procesado = True
                st.rerun()
                
        except Exception as e: st.error(f"Error lectura: {e}")

if st.session_state.procesado:
    df = st.session_state.df
    gj = st.session_state.gj
    cfg = st.session_state.config

    # FILTROS Y OPCIONES (Fuera del form para actualización instantánea)
    col_ctrl1, col_ctrl2 = st.columns([1, 3])
    
    with col_ctrl1:
        st.subheader("Filtros")
        all_tips = sorted(df[cfg['tip']].unique())
        sel_tips = st.multiselect("Tipos", all_tips, default=all_tips)
        
        st.markdown("---")
        st.subheader("Visualización")
        
        # CHECKBOXES CLAROS Y SEPARADOS
        opt_gradiente = st.checkbox("🔶 Activar Degradado (Colonias)", value=True, help="Colorea las colonias naranja según cantidad")
        opt_calor = st.checkbox("🔥 Activar Mapa de Calor", value=False, help="Muestra manchas de calor rojas/azules")
        opt_leyenda = st.checkbox("📝 Mostrar Leyenda", value=True, help="Muestra el cuadro explicativo flotante")

    with col_ctrl2:
        df_show = df[df[cfg['tip']].isin(sel_tips)]
        
        if not df_show.empty:
            opciones = {
                'gradiente': opt_gradiente,
                'calor': opt_calor,
                'leyenda': opt_leyenda
            }
            
            mapa = crear_mapa(df_show, gj, cfg, opciones)
            st_folium(mapa, width="100%", height=600, returned_objects=[])
            
            # Descarga
            buffer = BytesIO()
            mapa.save(buffer, close_file=False)
            st.download_button("💾 Descargar HTML", buffer.getvalue(), "mapa_riesgos.html", "text/html")
        else:
            st.warning("Sin datos con filtros actuales")

else:
    st.info("👈 Carga tus archivos en el menú lateral")
