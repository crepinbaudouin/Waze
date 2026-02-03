import re
import os
import folium
from streamlit_folium import st_folium
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import io
import sys
import logging
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import plotly.graph_objects as go
from pathlib import Path

# Suppress FPDF logging
logging.getLogger('fpdf').setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.ERROR)

ICONES = {
    "Trafic dense": "https://img.icons8.com/color/48/traffic-jam.png",
    "Trafic à l’arrêt": "https://img.icons8.com/color/24/traffic-jam.png",
    "Accident léger": "https://img.icons8.com/color/48/car-crash.png",
    "Accident grave": "https://img.icons8.com/color/48/car-accident.png",
    "Nid-de-poule": "https://img.icons8.com/color/48/road-worker.png",
    "Panne de feu tricolore": "https://img.icons8.com/color/48/traffic-light.png",
    "Inondation": "https://img.icons8.com/color/48/floods.png"
}

# =============================
# GRAVITÉ DES SCÉNARIOS
# =============================
GRAVITE = {
    "Accident grave": 5,
    "Inondation": 4,
    "Bouchon – trafic à l'arrêt": 3,
    "Accident léger": 3,
    "Bouchon – trafic dense": 2,
    "Panne de feu tricolore": 2,
    "Nid-de-poule": 1
}

# =============================
# CONFIG
# =============================
st.set_page_config(
    page_title="Rapport d'Activité Waze",
    layout="wide"
)

# =============================
# VILLES AUTORISÉES
# =============================
VILLES_SERVICE_COMMUN = [
    "Palaiseau", "Orsay", "Villejust", "Ballainvilliers",
    "Verrières-le-Buisson", "La Ville-du-Bois", "Les Ulis",
    "Saclay", "Wissous", "Villebon-sur-Yvette",
    "Saulx-les-Chartreux", "Villiers-le-Bâcle", "Linas",
    "Vauhallan", "Saint-Aubin", "Longjumeau",
    "Marcoussis", "Nozay", "Epinay-sur-Orge", "Igny"
]

# =============================
# SCÉNARIOS
# =============================
FILES = {
    "Waze heavy traffic.csv": "Bouchon – trafic dense",
    "Waze stand still traffic.csv": "Bouchon – trafic à l’arrêt",
    "Waze accident minor.csv": "Accident léger",
    "Waze accident major.csv": "Accident grave",
    "Waze pot_hole.csv": "Nid-de-poule",
    "HAZARD_ON_ROAD_TRAFFIC_LIGHT_FAULT.csv": "Panne de feu tricolore",
    "HAZARD_WEATHER_FLOOD.csv": "Inondation"
}

# --- Helper: extraire latitude/longitude depuis la colonne Location ---
def _parse_location_column(df, location_col="Location"):
    if location_col not in df.columns:
        return df

    def _extract_lat_lon(val):
        if pd.isna(val):
            return (None, None)
        s = str(val)

        m = re.search(r"POINT\s*\(\s*([-+]?\d*\.?\d+)[\s,]+([-+]?\d*\.?\d+)\s*\)", s, re.IGNORECASE)
        if m:
            try:
                lon = float(m.group(1))
                lat = float(m.group(2))
                return (lat, lon)
            except Exception:
                return (None, None)

        m2 = re.search(r"([-+]?\d*\.?\d+)[\s,;]+([-+]?\d*\.?\d+)", s)
        if m2:
            a = float(m2.group(1)); b = float(m2.group(2))
            if 40 <= a <= 60:
                return (a, b)
            if 40 <= b <= 60:
                return (b, a)
            return (a, b)
        return (None, None)

    lats = []
    lons = []
    for v in df[location_col]:
        lat, lon = _extract_lat_lon(v)
        lats.append(lat)
        lons.append(lon)

    df = df.copy()
    df["latitude"] = pd.to_numeric(pd.Series(lats), errors="coerce")
    df["longitude"] = pd.to_numeric(pd.Series(lons), errors="coerce")
    return df


# =============================
# CHARGEMENT DES DONNÉES
# =============================
@st.cache_data
def load_data():
    base_dir = Path(__file__).resolve().parent
    dfs = []
    missing = []

    for file_name, scenario in FILES.items():
        path = base_dir / file_name
        if not path.exists():
            missing.append(file_name)
            continue

        df = pd.read_csv(path, low_memory=False)

        if "City" not in df.columns:
            df["City"] = "Inconnue"
        else:
            df["City"] = df["City"].fillna("Inconnue")

        if "Street" not in df.columns:
            df["Street"] = ""
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
        else:
            df["Date"] = pd.NaT

        df = _parse_location_column(df, "Location")
        df["scenario"] = scenario
        dfs.append(df)

    if missing:
        st.warning(f"Fichiers absents dans {base_dir}: {', '.join(missing)}")

    if not dfs:
        raise FileNotFoundError("Aucun CSV valide trouvé.")

    waze = pd.concat(dfs, ignore_index=True)
    waze["City"] = waze["City"].fillna("Inconnue")

    waze_filtered = waze[waze["City"].isin(VILLES_SERVICE_COMMUN)].copy()
    waze_filtered["gravite"] = waze_filtered["scenario"].map(GRAVITE).fillna(1).astype(int)

    return waze_filtered

# 👉 IMPORTANT : Appel initial
waze = load_data()

# =============================
# CARTE
# =============================
def generate_waze_map(df):
    df = df.copy()

    if "latitude" not in df.columns or "longitude" not in df.columns:
        st.warning("Aucune colonne latitude/longitude détectée.")
        return folium.Map(location=[48.7, 2.25], zoom_start=11)

    df = df.dropna(subset=["latitude", "longitude"])
    if df.empty:
        st.info("Aucun point géolocalisé.")
        return folium.Map(location=[48.7, 2.25], zoom_start=11)

    try:
        center = [df["latitude"].astype(float).mean(), df["longitude"].astype(float).mean()]
    except Exception:
        center = [48.7, 2.25]

    m = folium.Map(location=center, zoom_start=11)

    for _, row in df.iterrows():
        lat = row["latitude"]
        lon = row["longitude"]

        icon_path = ICONES.get(row.get("scenario", ""), None)
        icon = folium.Icon(icon="info-sign")

        if icon_path:
            try:
                if isinstance(icon_path, str) and icon_path.startswith(("http://","https://")):
                    icon = folium.CustomIcon(icon_image=icon_path, icon_size=(28,28))
            except:
                pass

        popup_html = f"""
        <div>
        <b>Scénario :</b> {row.get('scenario')}<br>
        <b>Ville :</b> {row.get('City')}<br>
        <b>Rue :</b> {row.get('Street')}<br>
        <b>Date :</b> {row.get('Date')}
        </div>
        """

        folium.Marker([lat, lon], icon=icon, popup=popup_html).add_to(m)

    return m


# =============================
# SIDEBAR
# =============================
st.sidebar.title("Paramètres du rapport")

# 👉 OPTION A — Bouton recharger les données
if st.sidebar.button("🔄 Recharger les données"):
    st.cache_data.clear()
    st.experimental_rerun()

ville = st.sidebar.multiselect(
    "Ville(s)",
    sorted(waze["City"].unique()),
    default=["Palaiseau"]
)

st.sidebar.markdown("### 📅 Filtre par Date")
date_range = st.sidebar.date_input(
    "Sélectionner la plage",
    value=(waze["Date"].min().date(), waze["Date"].max().date()),
    min_value=waze["Date"].min().date(),
    max_value=waze["Date"].max().date()
)

df = waze[waze["City"].isin(ville)].copy()

if isinstance(date_range, tuple):
    df = df[(df["Date"].dt.date >= date_range[0]) & (df["Date"].dt.date <= date_range[1])]


# =============================
# AFFICHE STATISTIQUES
# =============================
st.title("📄 Rapport d'Activité Waze")

# ... (tout ton reste de code identique, inchangé) ...


# =============================
# 6️⃣ Carte Interactive Waze
# =============================
st.divider()
st.markdown("### 6️⃣ Carte Interactive Waze")

# Filtre scénario — carte uniquement
scenarios_disponibles = sorted(df["scenario"].dropna().unique())

scenario_carte = st.multiselect(
    "🎯 Filtrer les scénarios (agit uniquement sur la carte)",
    options=scenarios_disponibles,
    default=scenarios_disponibles
)

df_map = df[df["scenario"].isin(scenario_carte)].copy()

if len(df_map) == 0:
    st.warning("📍 Aucune donnée à afficher.")
else:
    waze_map = generate_waze_map(df_map)
    st_folium(waze_map, height=800, use_container_width=True)
