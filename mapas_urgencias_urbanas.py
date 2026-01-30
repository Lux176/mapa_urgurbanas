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

        if texto_limpio.startswith('deslizamiento de tierra/talud'):
            return 'deslizamiento de tierra/talud'
        
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
    """Genera un color único para los puntos (incidentes)."""
    try:
        hash_value = int(hashlib.sha256(str(texto).encode()).hexdigest(), 16)
        hue = ((hash_value % 1000) / 1000.0 + (index * 0.618033988749895)) % 1.0
        saturation = 0.7 + 0.2 * (index % 3) / 3.0
        lightness = 0.5 + 0.2 * (index % 4) / 4.0
        r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
        return f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
    except Exception:
        colores_fallback = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#feca57', '#ff9ff3', '#54a0ff', '#5f27cd']
        return colores_fallback[index % len(colores_fallback)]

def obtener_color_naranja_gradiente(valor, maximo):
    """Retorna un color naranja basado en la intensidad (valor vs maximo)."""
    if maximo == 0 or valor == 0:
        return '#ffffff' # Blanco si no hay incidentes
    
    # Paleta de naranjas: Desde muy claro hasta oscuro intenso
    paleta_naranjas = [
        '#FFF3E0', # Naranja muy muy claro (poca incidencia)
        '#FFE0B2',
        '#FFCC80',
        '#FFB74D',
        '#FFA726',
        '#FF9800',
        '#FB8C00',
        '#F57C00',
        '#EF6C00',
        '#E65100'  # Naranja rojizo intenso (máxima incidencia)
    ]
    
    # Calcular índice basado en porcentaje
    ratio = valor / maximo
    indice = int(ratio * (len(paleta_naranjas) - 1))
    return paleta_naranjas[indice]

def agregar_leyenda(mapa, color_map):
    """Agrega leyenda de tipos de incidente."""
    try:
        legend_html = """
        <div style="
            position: fixed;
            bottom: 30px; left: 30px; width: 220px; max-height: 300px; overflow-y: auto;
            z-index:9999; font-size:12px;
            background-color:white;
            border:2px solid grey; border-radius:8px;
            padding:10px; box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
            <b>🟢 Leyenda de Incidentes</b><br>
        """
        for tipo, color in list(color_map.items())[:15]:
            tipo_display = tipo.title() if len(tipo) <= 30 else tipo[:27] + "..."
            legend_html += f'<div style="margin:2px 0;"><span style="background-color:{color};width:12px;height:12px;display:inline-block;margin-right:5px;border:1px solid #000;border-radius:2px;"></span>{tipo_display}</div>'
        
        if len(color_map) > 15:
            legend_html += f'<div style="margin:2px 0; font-style:italic;">... y {len(color_map) - 15} más</div>'
            
        legend_html += "</div>"
        mapa.get_root().html.add_child(folium.Element(legend_html))
    except Exception as e:
        st.error(f"Error al crear leyenda: {e}")

def crear_mapa(df, gj_data, campo_geojson, col_lat, col_lon, col_colonia, col_tipo, col_fecha, usar_intensidad=False):
    """Crea y configura el mapa Folium con todas sus capas."""
    try:
        # Calcular centro del mapa
        centro = [df[col_lat].mean(), df[col_lon].mean()]
        mapa = folium.Map(
            location=centro, 
            zoom_start=13, 
            tiles="CartoDB positron",
            control_scale=True
        )

        # Generar mapa de colores para PUNTOS
        tipos_unicos = df[col_tipo].unique()
        color_map = {
            tipo: generar_color_por_texto(tipo, idx, len(tipos_unicos)) 
            for idx, tipo in enumerate(tipos_unicos)
        }

        # --- LÓGICA DE DENSIDAD POR COLONIA (NUEVO) ---
        conteo_por_colonia = {}
        max_incidentes = 0
        
        if usar_intensidad:
            # Contar incidentes por colonia normalizada
            counts = df[col_colonia].value_counts()
            conteo_por_colonia = counts.to_dict()
            max_incidentes = counts.max() if not counts.empty else 1

        # Procesar GeoJSON y Nombres
        nombres_originales = {}
        for feature in gj_data['features']:
            if campo_geojson in feature['properties']:
                original = feature['properties'][campo_geojson]
                limpio = limpiar_texto(original)
                feature['properties'][campo_geojson] = limpio
                feature['properties']['_conteo_temp'] = conteo_por_colonia.get(limpio, 0) # Guardar conteo en feature
                nombres_originales[limpio] = original

        # --- DEFINIR ESTILO DE POLÍGONOS ---
        def estilo_poligono(feature):
            if usar_intensidad:
                conteo = feature['properties'].get('_conteo_temp', 0)
                color_relleno = obtener_color_naranja_gradiente(conteo, max_incidentes)
                opacidad = 0.7 if conteo > 0 else 0.1
                return {
                    'fillColor': color_relleno,
                    'color': '#FF8F00' if conteo > 0 else '#808080', # Borde naranja oscuro si hay datos
                    'weight': 1 if conteo == 0 else 2,
                    'fillOpacity': opacidad
                }
            else:
                # Estilo Original (Blanco/Gris)
                return {
                    'fillColor': '#ffffff', 
                    'color': '#808080', 
                    'weight': 1, 
                    'fillOpacity': 0.1
                }

        # Agregar Polígonos de colonias
        folium.GeoJson(
            gj_data, 
            name='Intensidad por Colonia' if usar_intensidad else 'Límites de Colonias',
            style_function=estilo_poligono,
            tooltip=folium.GeoJsonTooltip(
                fields=[campo_geojson, '_conteo_temp'] if usar_intensidad else [campo_geojson], 
                aliases=['Colonia:', 'Total Incidentes:'] if usar_intensidad else ['Colonia:'],
                localize=True,
                sticky=False
            )
        ).add_to(mapa)

        # Nombres de colonias (Etiquetas)
        capa_nombres = folium.FeatureGroup(name="Nombres de Colonias", show=False)
        for feature in gj_data['features']:
            centroide = obtener_centroide(feature)
            nombre_limpio = feature['properties'].get(campo_geojson)
            if centroide and nombre_limpio:
                nombre_display = nombres_originales.get(nombre_limpio, nombre_limpio).title()
                folium.Marker(
                    location=centroide,
                    icon=folium.DivIcon(
                        html=f'<div style="font-family: Arial; font-size: 11px; font-weight: bold; color: #333; text-shadow: 1px 1px 1px #FFF; white-space: nowrap;">{nombre_display}</div>'
                    )
                ).add_to(capa_nombres)
        mapa.add_child(capa_nombres)

        # Capa de incidentes (PUNTOS)
        capa_incidentes = folium.FeatureGroup(name="Puntos de Incidentes", show=not usar_intensidad) # Ocultar puntos por defecto si usamos gradiente
        for _, row in df.iterrows():
            try:
                fecha_str = str(row[col_fecha])
                if hasattr(row[col_fecha], 'strftime'):
                    fecha_str = row[col_fecha].strftime('%d/%m/%Y')
                
                tooltip_text = f"{row[col_tipo].title()} - {row[col_colonia].title()}"
                
                popup_html = f"""
                <div style="font-family: Arial; font-size: 12px; max-width: 250px;">
                    <h4 style="margin: 0 0 8px 0; color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px;">
                        Detalles del Incidente
                    </h4>
                    <b>Colonia:</b> {row[col_colonia].title()}<br>
                    <b>Tipo:</b> {row[col_tipo].title()}<br>
                    <b>Fecha:</b> {fecha_str}<br>
                    <b>Coordenadas:</b> {row[col_lat]:.6f}, {row[col_lon]:.6f}
                </div>
                """
                
                folium.CircleMarker(
                    location=[row[col_lat], row[col_lon]],
                    radius=6,
                    color=color_map.get(row[col_tipo], '#000000'),
                    fill=True,
                    fill_color=color_map.get(row[col_tipo], '#000000'),
                    fill_opacity=0.8,
                    weight=1,
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=folium.Tooltip(tooltip_text, sticky=True)
                ).add_to(capa_incidentes)
            except Exception:
                continue

        mapa.add_child(capa_incidentes)

        # Mapa de calor (Heatmap tradicional)
        capa_calor = folium.FeatureGroup(name="Mapa de Calor (Densidad)", show=False)
        HeatMap(
            df[[col_lat, col_lon]].values, 
            radius=15,
            blur=10,
            gradient={0.4: 'blue', 0.6: 'cyan', 0.7: 'lime', 0.8: 'yellow', 1.0: 'red'}
        ).add_to(capa_calor)
        mapa.add_child(capa_calor)

        # Controles y leyenda
        folium.LayerControl(collapsed=True).add_to(mapa)
        agregar_leyenda(mapa, color_map)
        
        return mapa
        
    except Exception as e:
        st.error(f"Error al crear el mapa: {str(e)}")
        return None

# --- INTERFAZ DE STREAMLIT ---

st.title("🗺️ Visualizador de Mapas de Riesgos")
st.markdown("Sube tus archivos de incidentes y el mapa de colonias para generar una visualización interactiva.")

with st.sidebar:
    st.header("⚙️ Configuración")
    st.subheader("1. Carga tus archivos")
    
    uploaded_data_file = st.file_uploader("Archivo de incidentes (Excel o CSV)", type=['xlsx', 'csv'], key="data_uploader")
    uploaded_geojson_file = st.file_uploader("Archivo de colonias (GeoJSON)", type=['geojson', 'json'], key="geojson_uploader")

    if uploaded_data_file and uploaded_geojson_file:
        try:
            if uploaded_data_file.name.endswith('.xlsx'):
                df = pd.read_excel(uploaded_data_file)
            else:
                df = pd.read_csv(uploaded_data_file)
                
            gj_data = json.load(uploaded_geojson_file)
            st.success("✅ Archivos cargados correctamente.")
            
        except Exception as e:
            st.error(f"Error al leer archivos: {e}")
            st.stop()

        st.subheader("2. Asigna las columnas")
        columnas_disponibles = df.columns.tolist()
        
        col_lat = st.selectbox("Columna de LATITUD:", columnas_disponibles, index=None, key="lat_select")
        col_lon = st.selectbox("Columna de LONGITUD:", columnas_disponibles, index=None, key="lon_select")
        col_colonia = st.selectbox("Columna de COLONIA:", columnas_disponibles, index=None, key="colonia_select")
        col_fecha = st.selectbox("Columna de FECHA:", columnas_disponibles, index=None, key="fecha_select")
        col_tipo = st.selectbox("Columna de TIPO DE INCIDENTE:", columnas_disponibles, index=None, key="tipo_select")

        try:
            campos_geojson = list(gj_data['features'][0]['properties'].keys())
            campo_geojson_sel = st.selectbox("Campo de nombre de colonia en GeoJSON:", campos_geojson, index=None, key="geojson_select")
        except (IndexError, KeyError):
            st.error("Archivo GeoJSON no válido.")
            st.stop()
            
        # Validar columnas
        columnas_esenciales = [col_lat, col_lon, col_colonia, col_fecha, col_tipo, campo_geojson_sel]
        
        if all(columnas_esenciales):
            try:
                df_proc = df.copy()
                df_proc['Fecha_Original_Str'] = df_proc[col_fecha].astype(str)
                df_proc[col_fecha] = pd.to_datetime(df_proc[col_fecha], errors='coerce')
                df_proc[col_lat] = pd.to_numeric(df_proc[col_lat], errors='coerce')
                df_proc[col_lon] = pd.to_numeric(df_proc[col_lon], errors='coerce')
                df_proc[col_colonia] = df_proc[col_colonia].apply(limpiar_texto)
                df_proc[col_tipo] = df_proc[col_tipo].apply(limpiar_texto)
                df_proc = df_proc.dropna(subset=[col_lat, col_lon, col_fecha, col_colonia, col_tipo])
                
                if df_proc.empty:
                    st.warning("⚠️ No hay datos válidos después del procesamiento.")
                    st.session_state.datos_procesados = False
                else:
                    st.session_state.datos_procesados = True
                    st.session_state.df_proc = df_proc
                    st.session_state.config = {
                        'gj_data': gj_data,
                        'campo_geojson': campo_geojson_sel,
                        'col_lat': col_lat,
                        'col_lon': col_lon,
                        'col_colonia': col_colonia,
                        'col_fecha': col_fecha,
                        'col_tipo': col_tipo
                    }

            except Exception as e:
                st.error(f"Error al procesar datos: {e}")
                st.session_state.datos_procesados = False

        if st.session_state.datos_procesados:
            st.subheader("3. Filtra los datos")
            df_proc = st.session_state.df_proc
            config = st.session_state.config
            
            fecha_min_data = df_proc[config['col_fecha']].min().date()
            fecha_max_data = df_proc[config['col_fecha']].max().date()
            
            fecha_inicio, fecha_fin = st.date_input("Rango de fechas:", value=(fecha_min_data, fecha_max_data), min_value=fecha_min_data, max_value=fecha_max_data, key="date_filter")
            tipos_disponibles = sorted(df_proc[config['col_tipo']].unique())
            tipos_seleccionados = st.multiselect("Tipos de incidente a mostrar:", options=tipos_disponibles, default=tipos_disponibles, key="tipo_filter")

            # --- NUEVA OPCIÓN DE VISUALIZACIÓN ---
            st.subheader("4. Estilo de Mapa")
            usar_choropleth = st.checkbox("🎨 Colorear Colonias por Intensidad (Naranjas)", value=True, help="Colorea las colonias más fuerte según tengan más incidentes.")

            if fecha_inicio and fecha_fin and tipos_seleccionados:
                df_filtrado = df_proc[
                    (df_proc[config['col_fecha']].dt.date >= fecha_inicio) &
                    (df_proc[config['col_fecha']].dt.date <= fecha_fin) &
                    (df_proc[config['col_tipo']].isin(tipos_seleccionados))
                ]
                st.session_state.df_filtrado = df_filtrado
                st.session_state.tipos_seleccionados = tipos_seleccionados
                st.session_state.usar_choropleth = usar_choropleth

# --- MOSTRAR EL MAPA ---
if (st.session_state.datos_procesados and 'df_filtrado' in st.session_state and not st.session_state.df_filtrado.empty):
    
    df_final = st.session_state.df_filtrado
    config = st.session_state.config
    tipos_seleccionados = st.session_state.tipos_seleccionados
    usar_intensidad = st.session_state.get('usar_choropleth', False)
    
    st.success(f"🗺️ Mostrando {len(df_final)} incidentes en el mapa.")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total de Incidentes", f"{len(df_final)}")
    col2.metric("Tipos de Incidentes", f"{len(tipos_seleccionados)}")
    col3.metric("Modo Intensidad", "Activado" if usar_intensidad else "Desactivado")
    
    with st.spinner("Generando mapa..."):
        mapa_final = crear_mapa(
            df_final, 
            config['gj_data'], 
            config['campo_geojson'], 
            config['col_lat'], 
            config['col_lon'], 
            config['col_colonia'],
            config['col_tipo'],
            config['col_fecha'],
            usar_intensidad=usar_intensidad
        )
    
    if mapa_final:
        st_folium(mapa_final, width=1200, height=600, returned_objects=[], key="mapa_principal")
        
        st.markdown("---")
        st.subheader("💾 Descargar Mapa")
        if st.button("📥 Descargar Mapa como HTML", key="download_button"):
            with st.spinner("Preparando archivo para descarga..."):
                try:
                    map_buffer = BytesIO()
                    mapa_final.save(map_buffer, close_file=False)
                    map_buffer.seek(0)
                    st.download_button(
                        label="⬇️ Descargar Archivo HTML",
                        data=map_buffer.getvalue(),
                        file_name="mapa_riesgos_gradiente.html",
                        mime="text/html",
                        key="final_download"
                    )
                except Exception as e:
                    st.error(f"Error al generar archivo de descarga: {e}")
    else:
        st.error("❌ No se pudo generar el mapa. Verifica los datos y configuración.")

elif st.session_state.datos_procesados and 'df_filtrado' in st.session_state and st.session_state.df_filtrado.empty:
    st.warning("⚠️ No hay datos que coincidan con los filtros seleccionados.")
else:
    st.info("👋 Sube tus archivos en la barra lateral y configura las opciones para comenzar.")
