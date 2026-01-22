```markdown
# Rapport Waze (Streamlit)

Description
- Application Streamlit qui génère un rapport Waze et permet d'exporter un PDF.

Comment exécuter localement
1. Créez un environnement virtuel :
   - python -m venv .venv
   - source .venv/bin/activate  (Windows: .venv\Scripts\activate)
2. Installez les dépendances :
   - pip install -r requirements.txt
3. Lancez l'app :
   - streamlit run dashboard_waze.py

Déployer sur Streamlit Cloud
1. Poussez ce repo sur GitHub (voir étapes dans le README principal).
2. Allez sur https://share.streamlit.io et connectez-vous avec votre compte GitHub.
3. Cliquez sur "New app" → sélectionnez le repo, la branche et le fichier `dashboard_waze.py`.
4. Cliquez sur "Deploy".

Notes
- Si vos CSV sont volumineux (>100 MB) ou contiennent des données sensibles, ne les committez pas dans le repo public. Hébergez-les sur S3/GCS ou utilisez Git LFS / le système de secrets de Streamlit (ou uploader via l'UI).
- Assurez-vous que `load_data()` résout les chemins relatifs depuis le dossier du script (`Path(__file__).parent`) pour éviter les erreurs de CWD.
