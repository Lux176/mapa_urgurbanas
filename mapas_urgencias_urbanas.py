# --- IMPORTS NECESARIOS ---
import streamlit as st
import pandas as pd
import numpy as np
import json
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import unicodedata
from io import BytesIO

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Visualizador de Riesgos",
    page_icon="🗺️",
    layout="wide"
)

# --- FUNCIONES DE PROCESAMIENTO ---

def limpiar_texto(texto):
    """Normaliza un texto a minúsculas, sin acentos y unifica reportes."""
    if not isinstance(texto, str):
        return texto
    
    texto_limpio = unicodedata.normalize('NFD', texto) \
        .encode('ascii', 'ignore') \
        .decode('utf-8') \
        .lower() \
        .strip()

    if texto_limpio.startswith('deslizamiento de tierra/talud'):
        return 'deslizamiento de tierra/talud'
    
    return texto_limpio

def obtener_centroide(feature):
    """Calcula el centroide del polígono más grande en una feature GeoJSON."""
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

# --- FUNCIÓN PARA AGREGAR LA LEYENDA (CSS MODIFICADO PARA LAYOUT HORIZONTAL) ---
def agregar_leyenda_html(mapa, color_map):
    items_html = ""
    for tipo, color in color_map.items():
        # Cada elemento de la leyenda ahora tiene un margen a la derecha para espaciado horizontal
        items_html += f'<li style="margin-right: 15px;"><span style="background-color:{color};"></span>{tipo}</li>'

    leyenda_html = f"""
     <div id="maplegend" class="maplegend">
       <div class="legend-title">Tipo de Incidente</div>
       <ul class="legend-labels">{items_html}</ul>
     </div>
    """
    css_html = """
    <style type='text/css'>
      .maplegend { 
          position: fixed; 
          z-index:9999; 
          bottom: 20px; /* Un poco más arriba del borde */
          left: 50%; 
          transform: translateX(-50%);
          background-color: rgba(255, 255, 255, 0.85); 
          border-radius: 8px; 
          border: 2px solid #bbb;
          padding: 10px 15px; /* Más ancho que alto */
          font-family: Arial, sans-serif; 
          box-shadow: 0 0 15px rgba(0,0,0,0.2); 
      }
      .maplegend .legend-title { 
          display: none; /* Ocultamos el título para un look más limpio y horizontal */
      }
      .maplegend .legend-labels { 
          list-style: none; 
          margin: 0; 
          padding: 0; 
          display: flex; /* La clave para el layout horizontal */
          flex-direction: row; /* Asegura que los items se pongan en fila */
          align-items: center; 
      }
      .maplegend .legend-labels li { 
          display: flex; 
          align-items: center; 
          font-size: 14px; 
      }
      .maplegend .legend-labels span { 
          display: inline-block; 
          width: 16px; 
          height: 16px; 
          margin-right: 8px; /* Espacio entre el color y el texto */
          border-radius: 50%; 
          border: 1px solid #777; 
      }
    </style>
    """
    mapa.get_root().header.add_child(folium.Element(css_html))
    mapa.get_root().html.add_child(folium.Element(leyenda_html))


def crear_mapa(df, gj_data, campo_geojson, col_lat, col_lon, col_colonia, col_tipo):
    """Crea y configura el mapa Folium con todas sus capas."""
    centro = [df[col_lat].mean(), df[col_lon].mean()]
    mapa = folium.Map(location=centro, zoom_start=13, tiles="CartoDB positron")

    tipos_unicos = df[col_tipo].unique()
    colores = ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628', '#f781bf']
    color_map = {tipo: colores[i % len(colores)] for i, tipo in enumerate(tipos_unicos)}

    nombres_originales = {}
    for feature in gj_data['features']:
        if campo_geojson in feature['properties']:
            original = feature['properties'][campo_geojson]
            limpio = limpiar_texto(original)
            feature['properties'][campo_geojson] = limpio
            nombres_originales[limpio] = original

    folium.GeoJson(
        gj_data, name='Colonias',
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
                icon=folium.DivIcon(html=f'<div style="font-family: Arial; font-size: 11px; font-weight: bold; color: #333; text-shadow: 1px 1px 1px #FFF; white-space: nowrap;">{nombre_display}</div>')
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

    capa_calor = folium.FeatureGroup(name="Mapa de Calor", show=True).add_to(mapa)
    HeatMap(df[[col_lat, col_lon]].values, radius=15).add_to(capa_calor)

    folium.LayerControl(collapsed=False).add_to(mapa)
    agregar_leyenda_html(mapa, color_map)

    return mapa

# --- INTERFAZ DE STREAMLIT ---

st.title("🗺️ Visualizador de Mapas de Riesgos")
st.markdown("Sube tus archivos de incidentes y el mapa de colonias para generar una visualización interactiva.")

with st.sidebar:
    st.header("⚙️ Configuración")

    st.subheader("1. Carga tus archivos")
    uploaded_data_file = st.file_uploader("Archivo de incidentes (Excel o CSV)", type=['xlsx', 'csv'])
    uploaded_geojson_file = st.file_uploader("Archivo de colonias (GeoJSON)", type=['geojson', 'json'])

    df = None
    gj_data = None

    if uploaded_data_file and uploaded_geojson_file:
        try:
            df = pd.read_excel(uploaded_data_file) if uploaded_data_file.name.endswith('.xlsx') else pd.read_csv(uploaded_data_file)
            gj_data = json.load(uploaded_geojson_file)
            st.success("✅ Archivos cargados.")
        except Exception as e:
            st.error(f"Error al leer archivos: {e}")
            st.stop()

        st.subheader("2. Asigna las columnas")
        columnas_disponibles = df.columns.tolist()
        col_lat = st.selectbox("Columna de LATITUD:", columnas_disponibles, index=None)
        col_lon = st.selectbox("Columna de LONGITUD:", columnas_disponibles, index=None)
        col_colonia = st.selectbox("Columna de COLONIA:", columnas_disponibles, index=None)
        col_fecha = st.selectbox("Columna de FECHA:", columnas_disponibles, index=None)
        col_tipo = st.selectbox("Columna de TIPO DE INCIDENTE:", columnas_disponibles, index=None)

        try:
            campos_geojson = list(gj_data['features'][0]['properties'].keys())
            campo_geojson_sel = st.selectbox("Campo de nombre de colonia en GeoJSON:", campos_geojson, index=None)
        except (IndexError, KeyError):
            st.error("Archivo GeoJSON no válido.")
            st.stop()
            
        columnas_esenciales = [col_lat, col_lon, col_colonia, col_fecha, col_tipo, campo_geojson_sel]
        
        if all(columnas_esenciales):
            df_proc = df.copy()
            df_proc['Fecha Original'] = df_proc[col_fecha].astype(str)
            df_proc[col_fecha] = pd.to_datetime(df_proc[col_fecha], errors='coerce')
            
            df_proc[col_lat] = pd.to_numeric(df_proc[col_lat], errors='coerce')
            df_proc[col_lon] = pd.to_numeric(df_proc[col_lon], errors='coerce')

            df_proc = df_proc.dropna(subset=[col_lat, col_lon, col_fecha, col_colonia, col_tipo])
            
            df_proc[col_colonia] = df_proc[col_colonia].apply(limpiar_texto)
            df_proc[col_tipo] = df_proc[col_tipo].apply(limpiar_texto)

            st.subheader("3. Filtra los datos")
            
            if not df_proc.empty and col_fecha in df_proc.columns:
                fecha_min_data = df_proc[col_fecha].min().date()
                fecha_max_data = df_proc[col_fecha].max().date()
                fecha_inicio, fecha_fin = st.date_input(
                    "Rango de fechas:", value=(fecha_min_data, fecha_max_data),
                    min_value=fecha_min_data, max_value=fecha_max_data
                )
            else:
                st.warning("No hay datos de fecha válidos para filtrar.")
                fecha_inicio, fecha_fin = None, None
                df_final = pd.DataFrame() 
            
            tipos_disponibles = sorted(df_proc[col_tipo].unique())
            tipos_seleccionados = st.multiselect(
                "Tipos de incidente a mostrar:",
                options=tipos_disponibles,
                default=tipos_disponibles
            )
            
            if fecha_inicio and fecha_fin:
                df_final = df_proc[
                    (df_proc[col_fecha].dt.date >= fecha_inicio) &
                    (df_proc[col_fecha].dt.date <= fecha_fin) &
                    (df_proc[col_tipo].isin(tipos_seleccionados))
                ]
            else:
                df_final = pd.DataFrame() 

# --- ÁREA PRINCIPAL PARA MOSTRAR EL MAPA ---
if 'df_final' in locals() and not df_final.empty:
    st.success(f"Mostrando {len(df_final)} incidentes en el mapa.")
    
    col1, col2 = st.columns(2)
    col1.metric("Total de Incidentes", f"{len(df_final)}")
    col2.metric("Tipos de Incidentes Seleccionados", f"{len(tipos_seleccionados)}")
    
    mapa_final = crear_mapa(df_final, gj_data, campo_geojson_sel, col_lat, col_lon, col_colonia, col_tipo)
    
    st_folium(mapa_final, width=1200, height=600, returned_objects=[])

    st.markdown("---")
    st.subheader("Descargar Mapa")
    
    mapa_html_bytes = mapa_final._repr_html_().encode("utf-8")
    
    st.download_button(
        label="📥 Descargar Mapa como HTML",
        data=mapa_html_bytes,
        file_name="mapa_de_riesgos.html",
        mime="text/html"
    )

elif 'uploaded_data_file' in locals() and uploaded_data_file and uploaded_geojson_file:
    st.warning("⚠️ Faltan asignaciones de columnas o los filtros no devuelven resultados. Por favor, revisa tus selecciones en la barra lateral.")
else:
    st.info("👋 Sube tus archivos en la barra lateral para
