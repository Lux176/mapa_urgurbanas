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
st.set_page_config(
    page_title="Visualizador de Riesgos",
    page_icon="🗺️",
    layout="wide"
)

# --- INICIALIZACIÓN DE ESTADO ---
if 'datos_procesados' not in st.session_state:
    st.session_state.datos_procesados = False
if 'mapa_config' not in st.session_state:
    st.session_state.mapa_config = {}

# --- FUNCIONES DE PROCESAMIENTO ---

def limpiar_texto(texto):
    """Normaliza un texto a minúsculas, sin acentos y unifica reportes."""
    if not isinstance(texto, str):
        return texto
    
    try:
        texto_limpio = unicodedata.normalize('NFD', texto) \
            .encode('ascii', 'ignore') \
            .decode('utf-8') \
            .lower() \
            .strip()

        # Unificación básica de ejemplos comunes
        if texto_limpio.startswith('deslizamiento'):
            return 'deslizamiento de tierra'
        
        return texto_limpio
    except Exception:
        return str(texto).lower().strip()

def obtener_centroide(feature):
    """Calcula el centroide del polígono más grande en una feature GeoJSON."""
    try:
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
    except Exception:
        return None

def generar_color_por_texto(texto, index, total):
    """
    Genera un color categórico distintivo para cada tipo de reporte.
    Usa una paleta predefinida para los primeros items y hash para el resto.
    """
    # Paleta de colores de alto contraste para categorías
    paleta_fija = [
        '#E74C3C', # Rojo
        '#3498DB', # Azul
        '#F1C40F', # Amarillo
        '#9B59B6', # Morado
        '#2ECC71', # Verde
        '#E67E22', # Naranja
        '#1ABC9C', # Turquesa
        '#34495E', # Azul Oscuro
        '#D35400', # Calabaza
        '#7F8C8D'  # Gris
    ]
    
    if index < len(paleta_fija):
        return paleta_fija[index]
    
    try:
        # Generación matemática para categorías extra
        hash_value = int(hashlib.sha256(str(texto).encode()).hexdigest(), 16)
        hue = ((hash_value % 1000) / 1000.0 + (index * 0.618033988749895)) % 1.0
        saturation = 0.65
        lightness = 0.55
        r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
        return f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
    except Exception:
        return '#000000'

def obtener_color_naranja_gradiente(valor, maximo):
    """Retorna un color naranja basado en la intensidad."""
    if maximo == 0 or valor == 0:
        return '#ffffff'
    
    paleta_naranjas = [
        '#FFF3E0', '#FFE0B2', '#FFCC80', '#FFB74D', '#FFA726',
        '#FF9800', '#FB8C00', '#F57C00', '#EF6C00', '#E65100'
    ]
    
    ratio = valor / maximo
    indice = int(ratio * (len(paleta_naranjas) - 1))
    return paleta_naranjas[indice]

def agregar_leyenda(mapa, color_map, titulo="Leyenda"):
    """
    Agrega un recuadro flotante con la leyenda.
    """
    try:
        legend_html = f"""
        <div style="
            position: fixed;
            bottom: 30px; left: 30px; width: 250px; max-height: 350px; overflow-y: auto;
            z-index:9999; font-size:12px;
            background-color: rgba(255, 255, 255, 0.9);
            border: 2px solid #ccc; border-radius: 8px;
            padding: 10px; box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
            <div style="margin-bottom: 5px; font-weight: bold; font-size: 14px; border-bottom: 1px solid #ccc;">
                {titulo}
            </div>
        """
        
        for tipo, color in color_map.items():
            tipo_display = tipo.title()
            legend_html += f"""
            <div style="display: flex; align-items: center; margin: 4px 0;">
                <span style="background-color:{color}; width:15px; height:15px; display:inline-block; margin-right:8px; border:1px solid #666; border-radius:3px;"></span>
                <span style="flex: 1; word-wrap: break-word;">{tipo_display}</span>
            </div>
            """
            
        legend_html += "</div>"
        mapa.get_root().html.add_child(folium.Element(legend_html))
    except Exception as e:
        st.error(f"Error al crear leyenda: {e}")

def crear_mapa(df, gj_data, campo_geojson, col_lat, col_lon, col_colonia, col_tipo, col_fecha, usar_intensidad=False, mostrar_leyenda=True):
    """Crea y configura el mapa Folium."""
    try:
        centro = [df[col_lat].mean(), df[col_lon].mean()]
        mapa = folium.Map(
            location=centro, 
            zoom_start=13, 
            tiles="CartoDB positron",
            control_scale=True
        )

        # 1. Definir Colores por Tipo de Reporte (Para Puntos y Leyenda)
        tipos_unicos = sorted(df[col_tipo].unique())
        color_map_reportes = {
            tipo: generar_color_por_texto(tipo, idx, len(tipos_unicos)) 
            for idx, tipo in enumerate(tipos_unicos)
        }

        # 2. Lógica de Intensidad (Para Polígonos)
        conteo_por_colonia = {}
        max_incidentes = 0
        
        if usar_intensidad:
            counts = df[col_colonia].value_counts()
            conteo_por_colonia = counts.to_dict()
            max_incidentes = counts.max() if not counts.empty else 1

        # Procesar Nombres GeoJSON
        nombres_originales = {}
        for feature in gj_data['features']:
            if campo_geojson in feature['properties']:
                original = feature['properties'][campo_geojson]
                limpio = limpiar_texto(original)
                feature['properties'][campo_geojson] = limpio
                feature['properties']['_conteo_temp'] = conteo_por_colonia.get(limpio, 0)
                nombres_originales[limpio] = original

        # 3. Estilo de Polígonos
        def estilo_poligono(feature):
            if usar_intensidad:
                conteo = feature['properties'].get('_conteo_temp', 0)
                color_relleno = obtener_color_naranja_gradiente(conteo, max_incidentes)
                opacidad = 0.75 if conteo > 0 else 0.1
                weight = 2 if conteo > 0 else 1
                color_borde = '#E65100' if conteo > 0 else '#999'
                return {'fillColor': color_relleno, 'color': color_borde, 'weight': weight, 'fillOpacity': opacidad}
            else:
                return {'fillColor': '#ffffff', 'color': '#808080', 'weight': 1, 'fillOpacity': 0.1}

        folium.GeoJson(
            gj_data, 
            name='Colonias',
            style_function=estilo_poligono,
            tooltip=folium.GeoJsonTooltip(
                fields=[campo_geojson, '_conteo_temp'] if usar_intensidad else [campo_geojson], 
                aliases=['Colonia:', 'Total:'] if usar_intensidad else ['Colonia:'],
                localize=True
            )
        ).add_to(mapa)

        # 4. Capa de Nombres
        capa_nombres = folium.FeatureGroup(name="Etiquetas", show=False)
        for feature in gj_data['features']:
            centroide = obtener_centroide(feature)
            nombre_limpio = feature['properties'].get(campo_geojson)
            if centroide and nombre_limpio:
                nombre_display = nombres_originales.get(nombre_limpio, nombre_limpio).title()
                folium.Marker(
                    location=centroide,
                    icon=folium.DivIcon(
                        html=f'<div style="font-family: Arial; font-size: 10px; color: #444; text-shadow: 1px 1px 0px #fff;">{nombre_display}</div>'
                    )
                ).add_to(capa_nombres)
        mapa.add_child(capa_nombres)

        # 5. Capa de Puntos (Incidentes)
        # Si usamos intensidad (polígonos naranjas), ocultamos los puntos por defecto para no saturar, pero se pueden activar.
        capa_incidentes = folium.FeatureGroup(name="Reportes Individuales", show=not usar_intensidad)
        
        for _, row in df.iterrows():
            try:
                tipo = row[col_tipo]
                color = color_map_reportes.get(tipo, '#333')
                
                popup_html = f"""
                <div style="font-family:sans-serif; width:200px;">
                    <b style="color:{color}">{tipo.upper()}</b><br>
                    <hr style="margin:5px 0;">
                    <b>Colonia:</b> {row[col_colonia].title()}<br>
                    <b>Fecha:</b> {row[col_fecha].strftime('%d/%m/%Y') if pd.notnull(row[col_fecha]) else 'S/F'}
                </div>
                """
                
                folium.CircleMarker(
                    location=[row[col_lat], row[col_lon]],
                    radius=5,
                    color='#FFF',
                    weight=1,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.9,
                    popup=folium.Popup(popup_html, max_width=250),
                    tooltip=f"{tipo.title()}"
                ).add_to(capa_incidentes)
            except Exception:
                continue

        mapa.add_child(capa_incidentes)

        # 6. Leyenda (Controlada por el parámetro mostrar_leyenda)
        if mostrar_leyenda:
            if usar_intensidad:
                # Si es mapa de calor, leyenda simple de intensidad
                # Opcional: Si prefieres ver los tipos aunque sea mapa de calor, cambia esto.
                # Aquí mostramos la leyenda de tipos porque es lo que pediste explícitamente.
                agregar_leyenda(mapa, color_map_reportes, titulo="Tipos de Reporte (Puntos)")
            else:
                # Mapa de puntos normal
                agregar_leyenda(mapa, color_map_reportes, titulo="Categorías de Reporte")

        folium.LayerControl(collapsed=True).add_to(mapa)
        
        return mapa
        
    except Exception as e:
        st.error(f"Error al crear el mapa: {str(e)}")
        return None

# --- INTERFAZ DE STREAMLIT ---

st.title("🗺️ Visualizador de Riesgos")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    # 1. Carga
    st.subheader("1. Datos")
    uploaded_data = st.file_uploader("Excel/CSV Incidentes", type=['xlsx', 'csv'])
    uploaded_json = st.file_uploader("GeoJSON Colonias", type=['geojson', 'json'])

    if uploaded_data and uploaded_json:
        # Carga preliminar
        try:
            if uploaded_data.name.endswith('.xlsx'):
                df = pd.read_excel(uploaded_data)
            else:
                df = pd.read_csv(uploaded_data)
            gj_data = json.load(uploaded_json)
        except Exception as e:
            st.error(f"Error de archivo: {e}")
            st.stop()

        # 2. Columnas
        st.subheader("2. Mapeo de Columnas")
        cols = df.columns.tolist()
        c_lat = st.selectbox("Latitud", cols, key="lat")
        c_lon = st.selectbox("Longitud", cols, key="lon")
        c_col = st.selectbox("Colonia (Datos)", cols, key="col")
        c_tip = st.selectbox("Tipo de Reporte", cols, key="tip")
        c_fec = st.selectbox("Fecha", cols, key="fec")
        
        try:
            props = list(gj_data['features'][0]['properties'].keys())
            c_geo = st.selectbox("Colonia (GeoJSON)", props, key="geo")
        except:
            st.error("GeoJSON inválido")
            st.stop()

        # Procesamiento
        if st.button("Procesar Datos"):
            try:
                df[c_lat] = pd.to_numeric(df[c_lat], errors='coerce')
                df[c_lon] = pd.to_numeric(df[c_lon], errors='coerce')
                df[c_fec] = pd.to_datetime(df[c_fec], errors='coerce')
                df[c_col] = df[c_col].apply(limpiar_texto)
                df[c_tip] = df[c_tip].apply(limpiar_texto)
                df = df.dropna(subset=[c_lat, c_lon, c_tip])
                
                st.session_state.df_proc = df
                st.session_state.config = {
                    'gj': gj_data, 'c_geo': c_geo, 
                    'lat': c_lat, 'lon': c_lon, 
                    'col': c_col, 'tip': c_tip, 'fec': c_fec
                }
                st.session_state.datos_procesados = True
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

# Lógica Principal
if st.session_state.datos_procesados:
    df = st.session_state.df_proc
    conf = st.session_state.config
    
    # Filtros en Sidebar
    with st.sidebar:
        st.subheader("3. Filtros y Estilo")
        
        # Filtro de Tipos
        tipos = sorted(df[conf['tip']].unique())
        sel_tipos = st.multiselect("Filtrar por Tipo", tipos, default=tipos)
        
        # Opciones de Visualización
        st.markdown("---")
        st.markdown("**Estilo del Mapa**")
        usar_gradiente = st.checkbox("🎨 Modo Mapa de Calor (Colonias Naranjas)", value=False)
        mostrar_leyenda = st.checkbox("📝 Mostrar Leyenda Explicativa", value=True)
    
    # Filtrado del DF
    df_final = df[df[conf['tip']].isin(sel_tipos)]
    
    if not df_final.empty:
        st.metric("Total Reportes Visibles", len(df_final))
        
        mapa = crear_mapa(
            df_final, 
            conf['gj'], conf['c_geo'], 
            conf['lat'], conf['lon'], conf['col'], 
            conf['tip'], conf['fec'],
            usar_intensidad=usar_gradiente,
            mostrar_leyenda=mostrar_leyenda  # <--- Pasamos el control aquí
        )
        
        st_folium(mapa, width=1200, height=600, returned_objects=[])
        
        # Descarga
        if st.button("Descargar HTML"):
            buffer = BytesIO()
            mapa.save(buffer, close_file=False)
            st.download_button("Guardar Mapa", buffer.getvalue(), "mapa.html", "text/html")
            
    else:
        st.warning("No hay datos con los filtros actuales.")
else:
    st.info("Por favor carga los archivos y procesa los datos en el menú lateral.")
