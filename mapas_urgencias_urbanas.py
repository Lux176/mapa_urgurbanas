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
from io import BytesIO

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Visualizador de Riesgos",
    page_icon="🗺️",
    layout="wide"
)

# --- FUNCIONES AUXILIARES ---
def limpiar_texto(texto):
    if not isinstance(texto, str):
        return texto
    texto_limpio = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('utf-8').lower().strip()
    if texto_limpio.startswith('deslizamiento de tierra/talud'):
        return 'deslizamiento de tierra/talud'
    return texto_limpio

def obtener_centroide(feature):
    geom = feature.get("geometry", {})
    gtype, coords = geom.get("type"), geom.get("coordinates", [])
    if gtype == "Polygon":
        polygon_coords = coords[0]
    elif gtype == "MultiPolygon":
        polygon_coords = max([poly[0] for poly in coords], key=len, default=[])
    else:
        return None
    if not polygon_coords:
        return None
    longitudes, latitudes = zip(*polygon_coords)
    return (sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes))

def generar_color_por_texto(texto):
    hash_object = hashlib.sha256(texto.encode())
    return f"#{hash_object.hexdigest()[:6]}"

def agregar_leyenda(mapa, color_map):
    """Añade una leyenda de colores personalizada al mapa."""
    legend_html = """
    <div style="position: fixed; 
                bottom: 30px; left: 30px; width: 200px; 
                background-color: white; border: 2px solid grey; 
                z-index:9999; font-size:12px; border-radius:8px; padding: 10px;">
        <b>🧭 Tipos de Incidente</b><br>
    """
    for tipo, color in color_map.items():
        legend_html += f'<i style="background:{color};width:15px;height:15px;display:inline-block;margin-right:5px;border-radius:3px;"></i>{tipo.title()}<br>'
    legend_html += "</div>"
    mapa.get_root().html.add_child(folium.Element(legend_html))

def crear_mapa(df, gj_data, campo_geojson, col_lat, col_lon, col_colonia, col_tipo):
    centro = [df[col_lat].mean(), df[col_lon].mean()]
    mapa = folium.Map(location=centro, zoom_start=13, tiles="CartoDB positron")

    tipos_unicos = df[col_tipo].unique()
    color_map = {tipo: generar_color_por_texto(tipo) for tipo in tipos_unicos}

    nombres_originales = {}
    for feature in gj_data['features']:
        if campo_geojson in feature['properties']:
            original = feature['properties'][campo_geojson]
            limpio = limpiar_texto(original)
            feature['properties'][campo_geojson] = limpio
            nombres_originales[limpio] = original

    folium.GeoJson(
        gj_data,
        name='Colonias',
        style_function=lambda x: {'fillColor': '#ffffff', 'color': '#808080', 'weight': 1, 'fillOpacity': 0.1},
        tooltip=folium.GeoJsonTooltip(fields=[campo_geojson], aliases=['Colonia:'])
    ).add_to(mapa)

    capa_nombres = folium.FeatureGroup(name="Nombres de Colonias", show=True).add_to(mapa)
    for feature in gj_data['features']:
        centroide = obtener_centroide(feature)
        nombre_limpio = feature['properties'].get(campo_geojson)
        if centroide and nombre_limpio:
            nombre_display = nombres_originales.get(nombre_limpio, nombre_limpio).title()
            folium.Marker(
                location=centroide,
                icon=folium.DivIcon(html=f'<div style="font-family: Arial; font-size: 11px; font-weight: bold; color: #333; text-shadow: 1px 1px 1px #FFF;">{nombre_display}</div>')
            ).add_to(capa_nombres)

    capa_incidentes = folium.FeatureGroup(name="Incidentes", show=True).add_to(mapa)
    for _, row in df.iterrows():
        popup_html = f"<b>Tipo:</b> {row[col_tipo]}<br><b>Colonia:</b> {row[col_colonia].title()}<br><b>Fecha:</b> {row['Fecha Original']}"
        folium.CircleMarker(
            location=[row[col_lat], row[col_lon]],
            radius=6,
            color=color_map.get(row[col_tipo]),
            fill=True,
            fill_color=color_map.get(row[col_tipo]),
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=row[col_tipo]
        ).add_to(capa_incidentes)

    HeatMap(df[[col_lat, col_lon]].values, radius=15).add_to(mapa)
    folium.LayerControl(collapsed=False).add_to(mapa)
    agregar_leyenda(mapa, color_map)
    return mapa

# --- INTERFAZ DE STREAMLIT ---
st.title("🗺️ Visualizador de Mapas de Riesgos")
st.markdown("Sube tus archivos de incidentes y el mapa de colonias para generar una visualización interactiva.")

with st.sidebar:
    st.header("⚙️ Configuración")
    uploaded_data_file = st.file_uploader("Archivo de incidentes (Excel o CSV)", type=['xlsx', 'csv'])
    uploaded_geojson_file = st.file_uploader("Archivo de colonias (GeoJSON)", type=['geojson', 'json'])
    df = None
    gj_data = None

    if uploaded_data_file and uploaded_geojson_file:
        try:
            df = pd.read_excel(uploaded_data_file) if uploaded_data_file.name.endswith('.xlsx') else pd.read_csv(uploaded_data_file)
            gj_data = json.load(uploaded_geojson_file)
            st.success("✅ Archivos cargados correctamente.")
        except Exception as e:
            st.error(f"Error al leer archivos: {e}")
            st.stop()

        columnas = df.columns.tolist()
        col_lat = st.selectbox("Columna de LATITUD:", columnas)
        col_lon = st.selectbox("Columna de LONGITUD:", columnas)
        col_colonia = st.selectbox("Columna de COLONIA:", columnas)
        col_fecha = st.selectbox("Columna de FECHA:", columnas)
        col_tipo = st.selectbox("Columna de TIPO DE INCIDENTE:", columnas)
        campos_geojson = list(gj_data['features'][0]['properties'].keys())
        campo_geojson_sel = st.selectbox("Campo de nombre de colonia en GeoJSON:", campos_geojson)

        df[col_colonia] = df[col_colonia].apply(limpiar_texto)
        df[col_tipo] = df[col_tipo].apply(limpiar_texto)
        df['Fecha Original'] = df[col_fecha].astype(str)
        df[col_fecha] = pd.to_datetime(df[col_fecha], errors='coerce')
        df = df.dropna(subset=[col_lat, col_lon, col_fecha])

        st.subheader("📅 Filtros")
        fecha_min, fecha_max = df[col_fecha].min().date(), df[col_fecha].max().date()
        fecha_inicio, fecha_fin = st.date_input("Rango de fechas", (fecha_min, fecha_max))
        tipos_disp = sorted(df[col_tipo].unique())
        tipos_sel = st.multiselect("Tipos de incidente", tipos_disp, default=tipos_disp)

        df_final = df[(df[col_fecha].dt.date >= fecha_inicio) & (df[col_fecha].dt.date <= fecha_fin) & (df[col_tipo].isin(tipos_sel))]

        if not df_final.empty:
            mapa = crear_mapa(df_final, gj_data, campo_geojson_sel, col_lat, col_lon, col_colonia, col_tipo)

            # Guardar el mapa como HTML para descarga
            map_buffer = BytesIO()
            mapa.save(map_buffer, close_file=False)
            map_buffer.seek(0)

            st.sidebar.markdown("---")
            st.sidebar.download_button("📥 Descargar Mapa HTML", data=map_buffer, file_name="mapa_de_riesgos.html", mime="text/html")

            st.sidebar.info("El mapa se descargará sin duplicarse.")

            st_folium(mapa, width=1200, height=600)
        else:
            st.warning("⚠️ No hay datos en el rango o filtros seleccionados.")
    else:
        st.info("👋 Sube tus archivos en la barra lateral para comenzar.")
