# Accès français à ModuPort

ModuPort est un solveur mécanique par superéléments pour l’analyse et le criblage de configurations de structures modulaires multiétagées à ossature. L’interface comprend l’analyse statique et modale d’un modèle, un éditeur d’emprise 50 × 50, l’énumération des configurations H/V réalisables et l’exploration KX–KY, du front de Pareto et de la configuration à rigidité équilibrée.

## Démarrage

```bash
python -m pip install -e ".[ui]"
python -m streamlit run web/streamlit_app.py
```

Sélectionnez « Français » dans la barre latérale. La langue ne modifie ni les données structurales, ni l’emprise, ni les résultats numériques, ni la sémantique des exports. Les unités restent mm–N et les symboles E, G, Iy, Iz, KX, KY et Hz sont conservés. Consultez le [README anglais](../README.md) pour l’API, le domaine de validité, les limites et la licence.
