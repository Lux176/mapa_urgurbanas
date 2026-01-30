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
    """Calcula el centro del polígono para poner la etiqueta de texto"""
    try:
        geom = feature.get("geometry", {})
        gtype, coords = geom.get("type"), geom.get("coordinates", [])
        
        if gtype == "Polygon": 
            poly = coords[0]
        elif gtype == "MultiPolygon": 
            # Tomar el polígono más grande del multipolígono
            poly = max([p[0] for p in coords], key=len, default=[])
        else: 
            return None
            
        if not poly: return None
        
        # Calcular promedio de lats y lons
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
    # Gradiente de blanco a naranja oscuro
    paleta = ['#FFF3E0', '#FFE0B2', '#FFCC80', '#FFB74D', '#FFA726', '#FF9800', '#FB8C00', '#F57C00', '#EF6C00', '#E65100']
    
    # Calcular índice proporcional
    ratio = valor / maximo
    if ratio > 1: ratio = 1
    idx = int(ratio * (len(paleta)-1))
    return paleta[idx]

def agregar_leyenda_flotante(mapa, items, titulo="Leyenda"):
    """Inyecta HTML crudo en el mapa para la leyenda"""
    html = f"""
    <div style="position: fixed; bottom: 30px; left: 30px; width: 220px; max-height: 300px; 
    overflow-y: auto; z-index:9999; background: white; border: 2px solid grey; border-radius: 8px; padding: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
    <b style="font-size:14px; border-bottom: 1px solid #ccc; display:block; margin-bottom:5px;">{titulo}</b>
    """
    for txt, col in items.items():
        html += f'<div style="margin:3px 0; font-size:12px; display:flex; align-items:center;"><span style="background:{col};width:12px;height:12px;display:inline-block;margin-right:8px;border:1px solid #333;border-radius:2px;"></span>{txt.title()}</div>'
    html += "</div>"
    mapa.get_root().html.add_child(folium.Element(html))

# --- FUNCIÓN PRINCIPAL DEL MAPA ---

def crear_mapa(df, gj_data, config, opciones):
    """
    opciones: {'gradiente': bool, 'calor': bool, 'leyenda': bool}
    """
    try:
        centro = [df[config['lat']].mean(), df[config['lon']].mean()]
        m = folium.Map(location=centro, zoom_start=13, tiles="CartoDB positron", control_scale=True)

        # 1. Preparar Datos y Colores
        tipos = sorted(df[config['tip']].unique())
        colores_tipos = {t: generar_color_categoria(t, i) for i, t in enumerate(tipos)}
        
        # Conteo para el degradado
        conteo_colonia = df[config['col']].value_counts().to_dict()
        max_val = max(conteo_colonia.values()) if conteo_colonia else 1

        # 2. Capa Polígonos (Colonias) con Degradado opcional
        def estilo(feature):
            # Usamos el nombre limpio que insertamos en el paso anterior
            nom = feature['properties'].get(config['c_geo'], '') 
            
            if opciones['gradiente']:
                val = conteo_colonia.get(nom, 0)
                color_relleno = color_gradiente(val, max_val)
                borde = '#E65100' if val > 0 else '#bdc3c7'
                grosor = 2 if val > 0 else 1
                opacidad = 0.75 if val > 0 else 0.1
                return {'fillColor': color_relleno, 'color': borde, 'weight': grosor, 'fillOpacity': opacidad}
            else:
                # Estilo plano si no hay degradado
                return {'fillColor': '#ffffff', 'color': '#bdc3c7', 'weight': 1, 'fillOpacity': 0.1}

        # Preprocesar GeoJSON para asegurar match de nombres
        nombres_para_etiquetas = {} # Guardar nombre original para mostrarlo bonito
        
        for f in gj_data['features']:
            orig = f['properties'].get(config['c_geo_raw']) # Nombre tal cual viene en el archivo
            clean = limpiar_texto(orig)
            
            # Guardamos datos en las propiedades del feature para usarlos en estilo y tooltip
            f['properties'][config['c_geo']] = clean 
            f['properties']['_count'] = conteo_colonia.get(clean, 0)
            
            if clean:
                nombres_para_etiquetas[clean] = orig

        # Añadir capa GeoJSON
        folium.GeoJson(
            gj_data,
            name="Colonias (Polígonos)",
            style_function=estilo,
            tooltip=folium.GeoJsonTooltip(
                fields=[config['c_geo_raw'], '_count'] if opciones['gradiente'] else [config['c_geo_raw']], 
                aliases=['Colonia:', 'Incidentes:'] if opciones['gradiente'] else ['Colonia:'], 
                localize=True
            )
        ).add_to(m)

        # 3. Capa de Nombres (Etiquetas) - ¡RECUPERADA!
        fg_nombres = folium.FeatureGroup(name="Etiquetas Colonias", show=False) # Show=False por defecto para no saturar
        for f in gj_data['features']:
            centro = obtener_centroide(f)
            nombre_limpio = f['properties'].get(config['c_geo'])
            
            if centro and nombre_limpio:
                nombre_display = nombres_para_etiquetas.get(nombre_limpio, nombre_limpio).title()
                folium.Marker(
                    location=centro,
                    icon=folium.DivIcon(
                        html=f'<div style="font-family: Arial; font-size: 10px; color: #444; text-shadow: 1px 1px 0px #fff; white-space: nowrap;">{nombre_display}</div>'
                    )
                ).add_to(fg_nombres)
        m.add_child(fg_nombres)

        # 4. Capa Puntos (Incidentes)
        # Si el gradiente está activo, ocultamos los puntos por defecto, pero se pueden activar en el control de capas
        fg_puntos = folium.FeatureGroup(name="Puntos (Reportes)", show=not opciones['gradiente'])
        for _, row in df.iterrows():
            try:
                tipo = row[config['tip']]
                color = colores_tipos.get(tipo, '#333')
                
                popup_content = f"""
                <div style="width:200px">
                    <b style="color:{color}">{tipo.upper()}</b><br>
                    {row[config['col']].title()}<br>
                    <small>{row[config['fec']].date()}</small>
                </div>
                """
                
                folium.CircleMarker(
                    [row[config['lat']], row[config['lon']]],
                    radius=5, color='white', weight=1, fill_color=color, fill_opacity=0.9,
                    popup=folium.Popup(popup_content, max_width=250), 
                    tooltip=tipo
                ).add_to(fg_puntos)
            except: continue
        m.add_child(fg_puntos)

        # 5. Capa Mapa de Calor
        if opciones['calor']:
            heat_data = [[row[config['lat']], row[config['lon']]] for _, row in df.iterrows()]
            fg_calor = folium.FeatureGroup(name="Mapa de Calor", show=True)
            HeatMap(heat_data, radius=15, blur=10).add_to(fg_calor)
            m.add_child(fg_calor)

        # 6. Leyenda (Lógica Condicional Estricta)
        if opciones['leyenda']:
            if opciones['gradiente']:
                # Leyenda de gradiente
                items_grad = {'Alta Incidencia': '#E65100', 'Media': '#FFA726', 'Baja': '#FFF3E0', 'Sin Reportes': '#FFFFFF'}
                agregar_leyenda_flotante(m, items_grad, "Intensidad (Naranja)")
            else:
                # Leyenda de tipos de incidente
                agregar_leyenda_flotante(m, colores_tipos, "Tipos de Incidente")

        # 7. Controles Finales
        folium.LayerControl(collapsed=True).add_to(m)
        
        return m

    except Exception as e:
        st.error(f"Error generando mapa: {e}")
        return None

# --- INTERFAZ STREAMLIT ---

st.title("🗺️ Visualizador de Riesgos")

# Estado de sesión
if 'procesado' not in st.session_state: st.session_state.procesado = False

with st.sidebar:
    st.header("1. Carga de Datos")
    f_data = st.file_uploader("Excel/CSV Incidentes", type=['xlsx','csv'])
    f_geo = st.file_uploader("GeoJSON Colonias", type=['geojson','json'])

    if f_data and f_geo:
        try:
            # Lectura preliminar
            if f_data.name.endswith('xlsx'): df_raw = pd.read_excel(f_data)
            else: df_raw = pd.read_csv(f_data)
            gj = json.load(f_geo)
            
            st.subheader("Configuración de Columnas")
            cols = df_raw.columns.tolist()
            c_lat = st.selectbox("Latitud", cols)
            c_lon = st.selectbox("Longitud", cols)
            c_col = st.selectbox("Colonia (Excel)", cols)
            c_tip = st.selectbox("Tipo Incidente", cols)
            c_fec = st.selectbox("Fecha", cols)
            
            props = list(gj['features'][0]['properties'].keys())
            c_geo_raw = st.selectbox("Colonia (GeoJSON)", props)

            if st.button("Procesar Datos"):
                # Limpieza y guardado en sesión
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
                    'c_geo': 'colonia_limpia_interna', 
                    'c_geo_raw': c_geo_raw
                }
                st.session_state.procesado = True
                st.rerun()
                
        except Exception as e: st.error(f"Error lectura: {e}")

if st.session_state.procesado:
    df = st.session_state.df
    gj = st.session_state.gj
    cfg = st.session_state.config

    # PANEL DE CONTROL (Main Area)
    col_filtros, col_mapa = st.columns([1, 4])
    
    with col_filtros:
        st.subheader("Filtros")
        all_tips = sorted(df[cfg['tip']].unique())
        sel_tips = st.multiselect("Tipos", all_tips, default=all_tips)
        
        st.markdown("---")
        st.subheader("Opciones")
        
        # Checkboxes de control
        opt_gradiente = st.checkbox("🔶 Degradado Naranja", value=True, help="Pinta las colonias según cantidad de incidentes")
        opt_calor = st.checkbox("🔥 Mapa de Calor", value=False, help="Manchas de calor clásicas")
        opt_leyenda = st.checkbox("📝 Ver Leyenda", value=True, help="Muestra/Oculta el cuadro explicativo")
        
        st.info("💡 Tip: Puedes activar las etiquetas de nombres en el icono de capas (arriba-derecha del mapa).")

    with col_mapa:
        df_show = df[df[cfg['tip']].isin(sel_tips)]
        
        if not df_show.empty:
            opciones = {
                'gradiente': opt_gradiente,
                'calor': opt_calor,
                'leyenda': opt_leyenda
            }
            
            # Generar mapa
            mapa = crear_mapa(df_show, gj, cfg, opciones)
            
            # Renderizar
            st_folium(mapa, width="100%", height=650, returned_objects=[])
            
            # Descarga
            buffer = BytesIO()
            mapa.save(buffer, close_file=False)
            st.download_button("💾 Descargar HTML", buffer.getvalue(), "mapa_riesgos.html", "text/html")
        else:
            st.warning("No hay datos para mostrar con los filtros actuales.")

else:
    st.info("👈 Por favor carga tus archivos y configura las columnas en el menú lateral.")
