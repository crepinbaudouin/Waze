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

# --- Helper: extraire latitude/longitude depuis la colonne Location (WKT POINT lon lat) ---
def _parse_location_column(df, location_col="Location"):
    """
    Remplit df['latitude'] et df['longitude'] à partir de la colonne Location
    qui contient des valeurs du type: Point(2.287962 48.73947)
    Retourne le DataFrame modifié.
    """
    if location_col not in df.columns:
        return df

    def _extract_lat_lon(val):
        if pd.isna(val):
            return (None, None)
        s = str(val)
        # Cherche WKT POINT(lon lat) (lon puis lat)
        m = re.search(r"POINT\s*\(\s*([-+]?\d*\.?\d+)[\s,]+([-+]?\d*\.?\d+)\s*\)", s, re.IGNORECASE)
        if m:
            try:
                lon = float(m.group(1))
                lat = float(m.group(2))
                return (lat, lon)
            except Exception:
                return (None, None)
        # fallback: tente "lat,lon" ou "lon,lat"
        m2 = re.search(r"([-+]?\d*\.?\d+)[\s,;]+([-+]?\d*\.?\d+)", s)
        if m2:
            a = float(m2.group(1)); b = float(m2.group(2))
            # heuristique: si une coordonnée est dans l'intervalle typique de latitudes FR (~41..51)
            if 40 <= a <= 60:
                return (a, b)
            if 40 <= b <= 60:
                return (b, a)
            # sinon on retourne a as lat
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
# --- Remplacez la partie de load_data où vous lisez chaque CSV par ceci ---
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
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception as e:
            st.error(f"Erreur lecture {file_name}: {e}")
            raise

        # Normalisation colonnes attendues
        # Certains fichiers ont 'City' vide : on remplit par 'Inconnue'
        if "City" not in df.columns:
            df["City"] = "Inconnue"
        else:
            df["City"] = df["City"].fillna("Inconnue")

        # S'assurer que Street et Date existent
        if "Street" not in df.columns:
            df["Street"] = ""
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
        else:
            df["Date"] = pd.NaT

        # Extraire latitude/longitude depuis 'Location' (si présent)
        df = _parse_location_column(df, location_col="Location")

        # Ajout du scenario (issu du nom du fichier)
        df["scenario"] = scenario

        dfs.append(df)

    if missing:
        st.warning(f"Fichiers absents dans {base_dir}: {', '.join(missing)}")

    if not dfs:
        # fallback upload via UI (inchangé - conserve votre logique existante)
        st.error("Aucun fichier Waze trouvé dans le dossier du script.")
        uploaded = st.file_uploader(
            "Uploader un ou plusieurs fichiers CSV (fallback)",
            accept_multiple_files=True,
            type=["csv"]
        )
        if uploaded:
            for f in uploaded:
                try:
                    df = pd.read_csv(f, low_memory=False)
                except Exception as e:
                    st.error(f"Impossible de lire {f.name}: {e}")
                    raise
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
                df = _parse_location_column(df, location_col="Location")
                scenario = FILES.get(f.name, "Upload")
                df["scenario"] = scenario
                dfs.append(df)
            if not dfs:
                raise FileNotFoundError("Aucun CSV valide uploadé.")
        else:
            raise FileNotFoundError(
                f"Aucun des fichiers attendus ({', '.join(FILES.keys())}) "
                f"n'a été trouvé dans le dossier {base_dir}. "
                "Placez les fichiers dans ce dossier ou uploadez-les via l'interface."
            )

    # Concaténation et filtrage final
    waze = pd.concat(dfs, ignore_index=True)

    # Si la colonne 'City' existe avec valeurs vides après concat, on normalise
    if "City" in waze.columns:
        waze["City"] = waze["City"].fillna("Inconnue")
    else:
        waze["City"] = "Inconnue"

    waze_filtered = waze[waze["City"].isin(VILLES_SERVICE_COMMUN)].copy()
    # map gravité en tenant compte des scénarios absents
    waze_filtered["gravite"] = waze_filtered["scenario"].map(GRAVITE).fillna(1).astype(int)
    return waze_filtered

waze = load_data()

# --- Remplacez generate_waze_map par cette version robuste (utilise les colonnes créées ci‑dessus) ---
def generate_waze_map(df):
    # Afficher colonnes utiles pour debug (décommentez si besoin)
    # st.write("Colonnes disponibles (carte):", list(df.columns))

    # On travaille sur une copie
    df = df.copy()

    # Si latitude/longitude absentes, informer et retourner une carte vide
    if "latitude" not in df.columns or "longitude" not in df.columns:
        st.warning("Aucune colonne latitude/longitude détectée — la carte ne peut pas être affichée.")
        return folium.Map(location=[48.7, 2.25], zoom_start=11, tiles="CartoDB positron")

    # Filtrer les lignes avec coordonnées valides
    df = df.dropna(subset=["latitude", "longitude"])
    if df.empty:
        st.info("Aucun point géolocalisé à afficher pour la sélection.")
        return folium.Map(location=[48.7, 2.25], zoom_start=11, tiles="CartoDB positron")

    # Créer la carte centrée sur la moyenne des points
    try:
        center = [df["latitude"].astype(float).mean(), df["longitude"].astype(float).mean()]
    except Exception:
        center = [48.7, 2.25]

    m = folium.Map(location=center, zoom_start=11, tiles="CartoDB positron")

    for _, row in df.iterrows():
        lat = row.get("latitude")
        lon = row.get("longitude")
        if pd.isna(lat) or pd.isna(lon):
            continue
        try:
            lat = float(lat); lon = float(lon)
        except Exception:
            continue

        # Icone: utilisez URL si fourni dans ICONES, sinon icone par défaut
        icon_path = ICONES.get(row.get("scenario", ""), None)
        icon = None
        if icon_path:
            try:
                if isinstance(icon_path, str) and icon_path.startswith(("http://", "https://")):
                    icon = folium.CustomIcon(icon_image=icon_path, icon_size=(28, 28))
                elif os.path.exists(icon_path):
                    icon = folium.CustomIcon(icon_path, icon_size=(28, 28))
            except Exception:
                icon = None
        if icon is None:
            icon = folium.Icon(icon="info-sign")

        popup_html = "<div>"
        popup_html += f"<b>Scénario :</b> {row.get('scenario','')}<br>"
        popup_html += f"<b>Ville :</b> {row.get('City','')}<br>"
        popup_html += f"<b>Rue :</b> {row.get('Street','')}<br>"
        popup_html += f"<b>Date :</b> {row.get('Date','')}"
        popup_html += "</div>"

        folium.Marker(location=[lat, lon], icon=icon, popup=popup_html).add_to(m)

    return m

# =============================
# FONCTION D'EXPORT PDF
# =============================
def _generate_pdf_report(ville, df):
    """Internal PDF generation function without caching"""
    # Redirect stdout to suppress any output from FPDF
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    
    try:
        pdf = FPDF()
        pdf.add_page()
        
        # Couleurs
        color_header = (52, 152, 219)  # Bleu
        color_light = (236, 240, 241)  # Gris clair
        color_text = (44, 62, 80)  # Gris foncé
        
        # ===== EN-TÊTE =====
        pdf.set_fill_color(*color_header)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", "B", 22)
        clean_ville = ville.encode('ascii', 'ignore').decode('ascii')
        pdf.cell(0, 20, f"RAPPORT WAZE", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.set_font("helvetica", "", 14)
        pdf.cell(0, 12, f"{clean_ville}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.ln(5)
        
        # ===== INFOS RAPPORT =====
        pdf.set_text_color(*color_text)
        pdf.set_font("helvetica", "", 10)
        rapport_date = datetime.now().strftime('%d/%m/%Y à %H:%M')
        pdf.cell(0, 8, f"Date du rapport: {rapport_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        if len(df) > 0:
            date_min = df['Date'].min().date()
            date_max = df['Date'].max().date()
            pdf.cell(0, 8, f"Periode analysee: {date_min} au {date_max}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)
        
        # ===== SECTION 1: RÉSUMÉ STATISTIQUE =====
        pdf.set_fill_color(*color_light)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "1. RESUME STATISTIQUE", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.ln(2)
        
        pdf.set_font("helvetica", "", 10)
        total_alerts = len(df)
        pdf.cell(0, 8, f"Total de signalements: {total_alerts}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        if len(df) > 0:
            avg_per_day = total_alerts / ((df['Date'].max() - df['Date'].min()).days + 1)
            pdf.cell(0, 8, f"Moyenne par jour: {avg_per_day:.1f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.ln(5)
        
        # ===== SECTION 2: TABLEAU SCENARIOS =====
        pdf.set_fill_color(*color_light)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "2. REPARTITION PAR SCENARIO", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.ln(2)
        
        # En-tête du tableau
        pdf.set_font("helvetica", "B", 9)
        pdf.set_fill_color(*color_header)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(130, 8, "Scenario", border=1, fill=True)
        pdf.cell(50, 8, "Nombre", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True, align="C")
        
        # Données du tableau
        pdf.set_text_color(*color_text)
        pdf.set_font("helvetica", "", 9)
        pdf.set_fill_color(245, 245, 245)
        
        scenario_counts = df["scenario"].value_counts().sort_values(ascending=False)
        fill = False
        for idx, (scenario, count) in enumerate(scenario_counts.items()):
            clean_scenario = scenario.encode('ascii', 'ignore').decode('ascii')
            percentage = (count / total_alerts * 100) if total_alerts > 0 else 0
            
            pdf.set_fill_color(245, 245, 245) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(130, 7, clean_scenario, border=1, fill=fill)
            pdf.cell(50, 7, f"{count} ({percentage:.1f}%)", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=fill, align="C")
            fill = not fill
        
        pdf.ln(5)
        
        # ===== SECTION 3: TOP RUES =====n        pdf.set_fill_color(*color_light)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "3. TOP 10 RUES LES PLUS ACTIVES", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.ln(2)
        
        # En-tête du tableau
        pdf.set_font("helvetica", "B", 9)
        pdf.set_fill_color(*color_header)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(130, 8, "Rue", border=1, fill=True)
        pdf.cell(50, 8, "Signalements", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True, align="C")
        
        # Données du tableau
        pdf.set_text_color(*color_text)
        pdf.set_font("helvetica", "", 8)
        top_streets = df["Street"].value_counts().head(10)
        fill = False
        for street, count in top_streets.items():
            clean_street = str(street).encode('ascii', 'ignore').decode('ascii')[:50]
            pdf.set_fill_color(245, 245, 245) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(130, 7, clean_street, border=1, fill=fill)
            pdf.cell(50, 7, f"{count}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=fill, align="C")
            fill = not fill
        
        pdf.ln(5)
        
        # ===== SECTION 4: ANALYSE PAR SCENARIO =====
        pdf.set_fill_color(*color_light)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "4. ANALYSE DETAILLEE PAR TYPE", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.ln(3)
        
        pdf.set_font("helvetica", "", 9)
        scenarios_to_analyze = [
            ("Accident", "Accidents"),
            ("Inondation", "Inondations"),
            ("Bouchon", "Bouchons")
        ]
        
        for keyword, label in scenarios_to_analyze:
            df_filtered = df[df["scenario"].str.contains(keyword, na=False)]
            if len(df_filtered) > 0:
                pdf.set_font("helvetica", "B", 10)
                pdf.cell(0, 8, f"{label}: {len(df_filtered)} signalements", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                
                top_streets_scenario = df_filtered["Street"].value_counts().head(5)
                pdf.set_font("helvetica", "", 8)
                for street, count in top_streets_scenario.items():
                    clean_street = str(street).encode('ascii', 'ignore').decode('ascii')[:60]
                    pdf.cell(0, 6, f"   - {clean_street}: {count}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(2)
        
        # ===== SECTION 5: CONCLUSION =====
        pdf.add_page()
        pdf.set_fill_color(*color_light)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "5. CONCLUSION", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.ln(3)
        
        pdf.set_font("helvetica", "", 10)
        conclusion_text = (
            "Ce rapport d'activite Waze fournit une analyse detaillee des incidents routiers "
            "et des evenements signales. Les donnees collectees permettent d'identifier les "
            "zones et types d'evenements prioritaires pour orienter les actions de prevention "
            "et de gestion du trafic."
        )
        
        pdf.multi_cell(0, 5, conclusion_text)
        pdf.ln(5)
        
        # ===== PIED DE PAGE =====
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 10, "Rapport genere automatiquement - Donnees Waze", 
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        
        return bytes(pdf.output())
    finally:
        sys.stdout = old_stdout


def generate_pdf_report(ville, df):
    """Wrapper function that suppresses all output"""
    # Suppress all output including stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    
    try:
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        result = _generate_pdf_report(ville, df)
        return result
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


@st.cache_data
def get_cached_pdf(ville, date_tuple):
    """Cached PDF generation"""
    date_min, date_max = date_tuple
    # Handle single or multiple cities
    if isinstance(ville, list):
        ville_str = ville[0] if ville else "Rapport"
        df_filtered = waze[waze["City"].isin(ville)].copy()
    else:
        ville_str = ville
        df_filtered = waze[waze["City"] == ville].copy()
    df_filtered = df_filtered[(df_filtered["Date"].dt.date >= date_min) & (df_filtered["Date"].dt.date <= date_max)]
    return generate_pdf_report(ville_str, df_filtered)

# =============================
# SIDEBAR
# =============================
st.sidebar.title("Paramètres du rapport")

ville = st.sidebar.multiselect(
    "Ville(s)",
    sorted(waze["City"].unique()),
    default=["Palaiseau"]
)

# Sélecteur de date
st.sidebar.markdown("### 📅 Filtre par Date")
date_range = st.sidebar.date_input(
    "Sélectionner la plage de dates",
    value=(waze["Date"].min().date(), waze["Date"].max().date()),
    min_value=waze["Date"].min().date(),
    max_value=waze["Date"].max().date()
)

df = waze[waze["City"].isin(ville)].copy() if isinstance(ville, list) else waze[waze["City"] == ville].copy()

# Appliquer le filtre de date
if isinstance(date_range, tuple) and len(date_range) == 2:
    df = df[(df["Date"].dt.date >= date_range[0]) & (df["Date"].dt.date <= date_range[1])]
elif isinstance(date_range, type(pd.Timestamp.now().date())):
    df = df[df["Date"].dt.date == date_range]

st.sidebar.markdown("---")
st.sidebar.markdown("### 📥 Exporter")

# Generate PDF without showing output
pdf_placeholder = st.sidebar.empty()
with pdf_placeholder.container():
    if isinstance(date_range, tuple) and len(date_range) == 2:
        pdf_data = get_cached_pdf(ville, date_range)
    else:
        pdf_data = get_cached_pdf(ville, (date_range, date_range))
    pdf_placeholder.empty()

st.sidebar.download_button(
    label="📄 Télécharger en PDF",
    data=pdf_data,
    file_name=f"Rapport_Waze_{ville}_{datetime.now().strftime('%Y%m%d')}.pdf",
    mime="application/pdf"
)

# =============================
# TITRE AVEC LOGOS
# =============================
col_logo_left, col_title, col_logo_right = st.columns([1, 3, 1])

with col_logo_left:
    try:
        st.image("logo paris saclay.png", width=120)
    except:
        pass

with col_title:
    st.title("📄 Rapport d'Activité Waze")
    ville_display = ", ".join(ville) if isinstance(ville, list) else ville
    st.subheader(f"Ville : {ville_display}")

with col_logo_right:
    logo_ville = f"{ville[0]}.png" if isinstance(ville, list) else f"{ville}.png"
    try:
        st.image(logo_ville, width=120)
    except:
        st.info("Logo non disponible")

st.divider()

# =============================
# 1. INTRODUCTION
# =============================
st.markdown("""
### 📊 1. Introduction

Ce rapport présente une analyse approfondie des données Waze liées aux incidents
routiers et événements signalés. 
Les données Waze, collectées en temps réel, offrent des perspectives précieuses
pour la gestion des incidents et l'amélioration de la sécurité routière locale.
""")

st.info("💡 Ce rapport fournit des insights clés pour optimiser la gestion du trafic et des incidents routiers.")

# =============================
# 2. ANALYSE DES DONNÉES
# =============================
st.markdown("### 2️⃣ Analyse des Données Filtrées")

# If multiple cities are selected, show comparison
if isinstance(ville, list) and len(ville) > 1:
    st.markdown("#### 📊 Comparaison entre les villes")
    
    cols = st.columns(len(ville))
    for idx, (col, v) in enumerate(zip(cols, ville)):
        df_v = df[df["City"] == v]
        with col:
            col.subheader(v)
            if len(df_v) > 0:
                col.metric("Événements", len(df_v))
                col.metric("Gravité totale", int(df_v["gravite"].sum()))
                col.metric("Gravité moy.", f"{df_v['gravite'].mean():.2f}")
            else:
                col.info("Aucune donnée")
    st.divider()

col1, col2, col3, col4 = st.columns(4)

with col1:
    col1.metric("📊 Nombre total", len(df))
with col2:
    if len(df) > 0:
        col2.metric("📅 Début", str(df["Date"].min().date()))
    else:
        col2.metric("📅 Début", "N/A")
with col3:
    if len(df) > 0:
        col3.metric("📅 Fin", str(df["Date"].max().date()))
    else:
        col3.metric("📅 Fin", "N/A")

# Calcul indicateur de gravité
with col4:
    if len(df) > 0:
        gravite_totale = df["gravite"].sum()
        gravite_moyenne = df["gravite"].mean()
        
        if gravite_moyenne > 3:
            severity_color = "🔴"
            severity_text = "Élevée"
        elif gravite_moyenne > 1.5:
            severity_color = "🟡"
            severity_text = "Modérée"
        else:
            severity_color = "🟢"
            severity_text = "Faible"
        
        col4.metric("⚠️ Gravité Moy.", f"{severity_color} {gravite_moyenne:.2f}", f"Total: {gravite_totale}")
    else:
        col4.metric("⚠️ Gravité Moy.", "N/A")

st.divider()

# =============================
# 3. VISUALISATIONS
# =============================
st.markdown("### 3️⃣ Visualisations")

if len(df) == 0:
    st.warning("⚠️ Aucune donnée disponible pour les paramètres sélectionnés.")
else:
    # 3.1 Évolution temporelle
    st.markdown("#### 3.1 Évolution temporelle des scénarios")

    df_time = (
        df.groupby([df["Date"].dt.date, "scenario"])
        .size()
        .reset_index(name="count")
    )

    fig = px.line(
        df_time,
        x="Date",
        y="count",
        color="scenario",
        markers=True,
        title="📈 Tendance des incidents routiers"
    )
    st.plotly_chart(fig, use_container_width=True)

    # 3.2 Distribution
    st.markdown("#### 3.2 Distribution des scénarios par type")

    dist_data = df["scenario"].value_counts().reset_index()
    fig = px.bar(
        dist_data,
        x="scenario",
        y="count",
        labels={"scenario": "Scénario", "count": "Nombre"},
        color="count",
        color_continuous_scale="Viridis",
        title="📊 Répartition des signalements par type"
    )
    st.plotly_chart(fig, use_container_width=True)

    # 3.3 Top rues Inondations
    st.markdown("#### 3.3 Top 10 des rues avec inondations")

    df_inond = df[df["scenario"] == "Inondation"]
    if len(df_inond) > 0:
        inond_counts = df_inond["Street"].value_counts().head(10).reset_index()
        fig = px.bar(inond_counts, x="Street", y="count", labels={"Street": "Rue", "count": "Nombre"},
                     color="count", color_continuous_scale="Blues", title="🌊 Inondations par rue")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Aucune inondation signalée pour cette période.")

    # 3.4 Nids de poule
    st.markdown("#### 3.4 Top 10 des rues avec nids de poule")

    df_pothole = df[df["scenario"] == "Nid-de-poule"]
    if len(df_pothole) > 0:
        pothole_counts = df_pothole["Street"].value_counts().head(10).reset_index()
        fig = px.bar(pothole_counts, x="Street", y="count", labels={"Street": "Rue", "count": "Nombre"},
                     color="count", color_continuous_scale="Greys", title="🕳️ Nids de poule par rue")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Aucun nid de poule signalé pour cette période.")

    # 3.5 Accidents
    st.markdown("#### 3.5 Top 10 des rues avec accidents")

    df_acc = df[df["scenario"].str.contains("Accident", na=False)]
    if len(df_acc) > 0:
        acc_counts = df_acc["Street"].value_counts().head(10).reset_index()
        fig = px.bar(acc_counts, x="Street", y="count", labels={"Street": "Rue", "count": "Nombre"},
                     color="count", color_continuous_scale="Reds", title="⚠️ Accidents par rue")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Aucun accident signalé pour cette période.")

    # 3.5 Bouchons
    st.markdown("#### 3.6 Top 10 des rues avec bouchons")

    df_bouchons = df[df["scenario"].str.contains("Bouchon", na=False)]
    if len(df_bouchons) > 0:
        bouchons_counts = df_bouchons["Street"].value_counts().head(10).reset_index()
        fig = px.bar(bouchons_counts, x="Street", y="count", labels={"Street": "Rue", "count": "Nombre"},
                     color="count", color_continuous_scale="Oranges", title="🚗 Bouchons par rue")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Aucun bouchon signalé pour cette période.")

    # 3.6 Tous scénarios
    st.markdown("#### 3.7 Top 10 des rues avec le plus de scénarios")

    all_streets = df["Street"].value_counts().head(10).reset_index()
    fig = px.bar(all_streets, x="Street", y="count", labels={"Street": "Rue", "count": "Nombre"},
                 color="count", color_continuous_scale="Purples", title="📍 Rues les plus actives")
    st.plotly_chart(fig, use_container_width=True)

    # 3.7 Corrélation
    st.markdown("#### 3.8 Matrice de corrélation des scénarios quotidiens")

    pivot = (
        df.groupby([df["Date"].dt.date, "scenario"])
        .size()
        .unstack(fill_value=0)
    )

    corr = pivot.corr()

    fig = px.imshow(
        corr,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="RdBu",
        title="🔗 Corrélations entre types d'incidents"
    )
    st.plotly_chart(fig, use_container_width=True)

# =============================
# 4. ANALYSE
# =============================
st.divider()
st.markdown("""
### 4️⃣ Analyse de la Matrice de Corrélation

Cette matrice permet d'identifier les scénarios susceptibles de se produire
simultanément, indiquant des relations potentielles entre événements routiers.
""")

# =============================
# 5. CONCLUSION
# =============================
st.divider()
st.markdown("""
### 5️⃣ Conclusion

Les données Waze constituent un outil puissant pour l'analyse de la mobilité et
des incidents routiers. 
Ce rapport permet d'identifier les zones et types d'événements prioritaires afin
d'orienter les actions de prévention et de gestion du trafic.
""")

st.divider()
st.markdown("""
### 6️⃣ Carte Interactive Waze
""")

if len(df) == 0:
    st.warning("📍 Aucune donnée à afficher sur la carte.")
else:
    waze_map = generate_waze_map(df)
    st_folium(
        waze_map,
        height=600,
        use_container_width=True
    )
st.markdown("<p style='text-align: center; color: #888;'>📊 Rapport généré avec  les données Waze</p>", unsafe_allow_html=True)
