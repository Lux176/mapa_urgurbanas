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
    """Asigna un color único y consistente a cada tipo de incidente"""
    # Paleta de colores vibrantes y distintivos
    paleta = [
        '#E74C3C', # Rojo (Alarma)
        '#3498DB', # Azul (Agua)
        '#F1C40F', # Amarillo (Precaución)
        '#9B59B6', # Morado
        '#2ECC71', # Verde
        '#E91E63', # Rosa Fuerte
        '#1ABC9C', # Turquesa
        '#34495E', # Azul Oscuro
        '#D35400', # Naranja Quemado
        '#7F8C8D'  # Gris
    ]
    if index < len(paleta): return paleta[index]
    
    # Generador para tipos extra
    h = int(hashlib.sha256(str(texto).encode()).hexdigest(), 16)
    hue = ((h % 1000)/1000.0 + (index * 0.618)) % 1.0
    r,g,b = colorsys.hls_to_rgb(hue, 0.5, 0.6)
    return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))

def agregar_leyenda_dinamica(mapa, items_tipos):
    """Leyenda unificada: el color aplica tanto al punto como a la zona predominante"""
    html = """
    <div style="position: fixed; bottom: 30px; left: 30px; width: 230px; max-height: 350px; 
    overflow-y: auto; z-index:9999; background: white; border: 2px solid grey; border-radius: 8px; padding: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
    <b style="font-size:14px; border-bottom: 1px solid #ccc; display:block; margin-bottom:5px;">Clasificación de Riesgos</b>
    <div style="font-size:10px; color:#555; margin-bottom:8px;">
    <i>El color de la colonia indica el riesgo predominante. La intensidad indica la cantidad.</i>
    </div>
    """
    
    for txt, col in items_tipos.items():
        html += f'<div style="margin:3px 0; font-size:12px; display:flex; align-items:center;"><span style="background:{col};width:12px;height:12px;display:inline-block;margin-right:8px;border-radius:2px;border:1px solid #333;"></span>{txt.title()}</div>'
    
    html += "</div>"
    mapa.get_root().html.add_child(folium.Element(html))

# --- LÓGICA DEL MAPA ---

def crear_mapa(df, gj_data, config, opciones):
    try:
        centro = [df[config['lat']].mean(), df[config['lon']].mean()]
        m = folium.Map(location=centro, zoom_start=13, tiles="CartoDB positron", control_scale=True)

        # 1. Definir Colores (Mapa de Categorías)
        tipos = sorted(df[config['tip']].unique())
        colores_tipos = {t: generar_color_categoria(t, i) for i, t in enumerate(tipos)}
        
        # 2. Análisis por Colonia (Dominancia y Cantidad)
        # Agrupamos para saber: Total de incidentes Y cuál es el más común (Moda)
        grupo_colonia = df.groupby(config['col'])[config['tip']].agg(
            total='count',
            moda=lambda x: x.mode().iloc[0] if not x.mode().empty else None
        )
        
        dict_total = grupo_colonia['total'].to_dict()
        dict_moda = grupo_colonia['moda'].to_dict()
        max_val = max(dict_total.values()) if dict_total else 1

        # 3. Capa Polígonos (Colonias) - LÓGICA NUEVA
        def estilo(feature):
            nom = feature['properties'].get(config['c_geo'], '') 
            
            if opciones['gradiente']:
                cantidad = dict_total.get(nom, 0)
                tipo_predominante = dict_moda.get(nom)
                
                if cantidad > 0 and tipo_predominante:
                    # Obtenemos el color del tipo de incidente predominante
                    color_base = colores_tipos.get(tipo_predominante, '#808080')
                    
                    # Calculamos opacidad basada en la cantidad (Gradiente de intensidad)
                    # Mínimo 0.2 (para que se vea algo) hasta 0.8 (muy sólido)
                    ratio = cantidad / max_val
                    opacidad = 0.2 + (0.6 * ratio)
                    
                    return {
                        'fillColor': color_base,
                        'color': color_base, # El borde del mismo color
                        'weight': 2,
                        'fillOpacity': opacidad
                    }
                else:
                    return {'fillColor': '#ffffff', 'color': '#bdc3c7', 'weight': 1, 'fillOpacity': 0.05}
            else:
                return {'fillColor': '#ffffff', 'color': '#bdc3c7', 'weight': 1, 'fillOpacity': 0.05}

        # Preparar GeoJSON
        nombres_etiquetas = {}
        for f in gj_data['features']:
            orig = f['properties'].get(config['c_geo_raw'])
            clean = limpiar_texto(orig)
            f['properties'][config['c_geo']] = clean 
            
            # Datos para Tooltip
            cant = dict_total.get(clean, 0)
            tipo_dom = dict_moda.get(clean, 'N/A')
            f['properties']['_info'] = f"{cant} (Mayoría: {tipo_dom.title()})" if cant > 0 else "Sin reportes"
            
            if clean: nombres_etiquetas[clean] = orig

        folium.GeoJson(
            gj_data,
            name="Colonias (Riesgo Predominante)",
            style_function=estilo,
            tooltip=folium.GeoJsonTooltip(
                fields=[config['c_geo_raw'], '_info'], 
                aliases=['Colonia:', 'Detalle:'], 
                localize=True
            )
        ).add_to(m)

        # 4. Capa Puntos (Incidentes)
        fg_puntos = folium.FeatureGroup(name="Puntos Individuales", show=True)
        for _, row in df.iterrows():
            try:
                tipo = row[config['tip']]
                color = colores_tipos.get(tipo, '#333')
                
                popup_content = f"""
                <div style="font-family:sans-serif; width:180px;">
                    <b style="color:{color}; font-size:13px;">{tipo.upper()}</b><br>
                    <div style="background:{color}; height:2px; margin:2px 0;"></div>
                    {row[config['col']].title()}<br>
                    <small style="color:#666">{row[config['fec']].strftime('%d/%m/%Y')}</small>
                </div>
                """
                
                folium.CircleMarker(
                    [row[config['lat']], row[config['lon']]],
                    radius=5, 
                    color='white', # Borde blanco vital para contraste sobre fondo de color
                    weight=1.5,
                    fill=True,
                    fill_color=color,
                    fill_opacity=1.0, # Punto sólido
                    popup=folium.Popup(popup_content, max_width=200), 
                    tooltip=tipo.title()
                ).add_to(fg_puntos)
            except: continue
        m.add_child(fg_puntos)

        # 5. Etiquetas de Nombres
        fg_nombres = folium.FeatureGroup(name="Etiquetas Nombres", show=False)
        for f in gj_data['features']:
            centro = obtener_centroide(f)
            nombre = f['properties'].get(config['c_geo'])
            if centro and nombre:
                display = nombres_etiquetas.get(nombre, nombre).title()
                folium.Marker(
                    location=centro,
                    icon=folium.DivIcon(html=f'<div style="font-size:10px; font-weight:bold; color:#444; text-shadow:1px 1px 0 rgba(255,255,255,0.8);">{display}</div>')
                ).add_to(fg_nombres)
        m.add_child(fg_nombres)

        # 6. Mapa de Calor
        if opciones['calor']:
            heat_data = [[row[config['lat']], row[config['lon']]] for _, row in df.iterrows()]
            HeatMap(heat_data, radius=15, blur=12, name="Mapa de Calor").add_to(m)

        # 7. Leyenda
        if opciones['leyenda']:
            agregar_leyenda_dinamica(m, colores_tipos)

        folium.LayerControl(collapsed=True).add_to(m)
        return m

    except Exception as e:
        st.error(f"Error generando mapa: {e}")
        return None

# --- INTERFAZ STREAMLIT ---

st.title("🗺️ Mapa de Riesgos Predominantes")

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
        st.subheader("Visualización")
        
        st.markdown("**Estilo de Colonias**")
        opt_gradiente = st.checkbox("🎨 Colorear por Riesgo Predominante", value=True, help="La colonia toma el color del incidente más frecuente.")
        
        st.markdown("**Capas Extra**")
        opt_calor = st.checkbox("🔥 Mapa de Calor", value=False)
        opt_leyenda = st.checkbox("📝 Mostrar Leyenda", value=True)

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
            st.download_button("💾 Descargar Mapa HTML", buffer.getvalue(), "mapa_riesgo_predominante.html", "text/html")
        else:
            st.warning("No hay datos visibles.")
else:
    st.info("Sube tus archivos para comenzar.")
