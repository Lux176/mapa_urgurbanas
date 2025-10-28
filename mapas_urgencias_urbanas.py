# --- IMPORTS NECESARIOS ---
import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
from io import BytesIO
import base64
import unicodedata

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Mapa de Urgencias Urbanas",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- ESTILOS PERSONALIZADOS ---
st.markdown("""
    <style>
        .main {
            background-color: #f8f9fa;
        }
        h1 {
            text-align: center;
            color: #1e3a8a;
            font-size: 2.3em;
            font-weight: bold;
        }
        .legend {
            position: fixed;
            bottom: 40px;
            left: 40px;
            background-color: white;
            padding: 10px 14px;
            border-radius: 10px;
            box-shadow: 2px 2px 10px rgba(0,0,0,0.3);
            font-size: 14px;
            color: #333;
        }
        .legend h4 {
            margin: 0;
            font-size: 15px;
            color: #1e3a8a;
        }
    </style>
""", unsafe_allow_html=True)

# --- FUNCIÓN PARA NORMALIZAR TEXTO ---
def normalizar_texto(texto):
    if pd.isna(texto):
        return ""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("utf-8")
    return texto.title()

# --- PANEL DE CARGA ---
st.sidebar.header("📂 Carga de Archivo")
archivo = st.sidebar.file_uploader("Sube tu archivo CSV", type=["csv"])

# --- PANEL DE DESCARGA ---
st.sidebar.markdown("---")
st.sidebar.header("⬇️ Descargas")

# --- FUNCIÓN PARA DESCARGAR EL HTML ---
def generar_descarga_html(mapa):
    mapa_html = mapa.get_root().render()
    buffer = BytesIO(mapa_html.encode("utf-8"))
    b64 = base64.b64encode(buffer.getvalue()).decode()
    href = f'<a href="data:text/html;base64,{b64}" download="Mapa_Urgencias.html" style="font-size:16px; color:#1e3a8a; text-decoration:none;">📥 Descargar Mapa HTML</a>'
    st.sidebar.markdown(href, unsafe_allow_html=True)

# --- FUNCIÓN PRINCIPAL PARA CREAR EL MAPA ---
def crear_mapa(df, campo_colonia, campo_tipo, lat_col, lon_col):
    df = df.dropna(subset=[lat_col, lon_col])
    df[campo_colonia] = df[campo_colonia].apply(normalizar_texto)
    df[campo_tipo] = df[campo_tipo].apply(normalizar_texto)

    centro = [df[lat_col].mean(), df[lon_col].mean()]
    mapa = folium.Map(location=centro, zoom_start=13, tiles="CartoDB positron")

    colores = {
        "Incendio": "red",
        "Inundacion": "blue",
        "Derrumbe": "orange",
        "Accidente": "green",
        "Otro": "purple"
    }

    for _, fila in df.iterrows():
        tipo = fila[campo_tipo]
        color = colores.get(tipo, "gray")
        popup_info = f"""
        <b>Colonia:</b> {fila[campo_colonia]}<br>
        <b>Tipo:</b> {tipo}<br>
        <b>Latitud:</b> {fila[lat_col]:.5f}<br>
        <b>Longitud:</b> {fila[lon_col]:.5f}
        """
        folium.CircleMarker(
            location=[fila[lat_col], fila[lon_col]],
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.85,
            popup=popup_info,
        ).add_to(mapa)

    # --- HEATMAP ---
    HeatMap(df[[lat_col, lon_col]].values, radius=20, blur=15).add_to(mapa)

    # --- LEYENDA ---
    legend_html = """
    <div class="legend">
        <h4>Leyenda de Colores</h4>
        <i style="background:red;width:12px;height:12px;float:left;margin-right:8px"></i> Incendio<br>
        <i style="background:blue;width:12px;height:12px;float:left;margin-right:8px"></i> Inundación<br>
        <i style="background:orange;width:12px;height:12px;float:left;margin-right:8px"></i> Derrumbe<br>
        <i style="background:green;width:12px;height:12px;float:left;margin-right:8px"></i> Accidente<br>
        <i style="background:purple;width:12px;height:12px;float:left;margin-right:8px"></i> Otro<br>
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(legend_html))
    return mapa

# --- INTERFAZ PRINCIPAL ---
st.title("🗺️ Mapa Interactivo de Urgencias Urbanas")

if archivo:
    df = pd.read_csv(archivo)
    st.success("✅ Archivo cargado correctamente")

    columnas = list(df.columns)

    # --- SELECCIÓN DE COLUMNAS ---
    st.sidebar.subheader("⚙️ Configuración del Mapa")
    col_lat = st.sidebar.selectbox("Columna de Latitud", columnas)
    col_lon = st.sidebar.selectbox("Columna de Longitud", columnas)
    col_colonia = st.sidebar.selectbox("Columna de Colonia", columnas)
    col_tipo = st.sidebar.selectbox("Columna de Tipo de Incidente", columnas)

    # --- FILTROS INTERACTIVOS ---
    df[col_colonia] = df[col_colonia].apply(normalizar_texto)
    df[col_tipo] = df[col_tipo].apply(normalizar_texto)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Filtros Interactivos")

    colonias_disp = sorted(df[col_colonia].dropna().unique())
    tipos_disp = sorted(df[col_tipo].dropna().unique())

    colonia_sel = st.sidebar.multiselect("Filtrar por Colonia", colonias_disp)
    tipo_sel = st.sidebar.multiselect("Filtrar por Tipo de Incidente", tipos_disp)

    df_filtrado = df.copy()
    if colonia_sel:
        df_filtrado = df_filtrado[df_filtrado[col_colonia].isin(colonia_sel)]
    if tipo_sel:
        df_filtrado = df_filtrado[df_filtrado[col_tipo].isin(tipo_sel)]

    # --- CREAR MAPA ---
    if st.sidebar.button("🧭 Generar Mapa"):
        if df_filtrado.empty:
            st.warning("⚠️ No hay datos que coincidan con los filtros seleccionados.")
        else:
            with st.spinner("Generando mapa..."):
                mapa = crear_mapa(df_filtrado, col_colonia, col_tipo, col_lat, col_lon)
                st_folium(mapa, width=1200, height=650)
                generar_descarga_html(mapa)
else:
    st.info("👈 Sube un archivo CSV desde la barra lateral para comenzar.")
