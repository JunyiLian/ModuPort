# Acceso en español a ModuPort

ModuPort es un solucionador mecánico de superelementos para el análisis y el cribado de configuraciones de estructuras modulares porticadas de varias plantas. La interfaz incluye análisis estático y modal de un modelo, un editor de huella de 50 × 50, enumeración de configuraciones H/V factibles y exploración KX–KY, del frente de Pareto y de la configuración de rigidez equilibrada.

## Inicio

```bash
python -m pip install -e ".[ui]"
python -m streamlit run web/streamlit_app.py
```

Seleccione « Español » en la barra lateral. El idioma no modifica los datos estructurales, la huella, los resultados numéricos ni la semántica de las exportaciones. Se mantiene el sistema de unidades mm–N y los símbolos E, G, Iy, Iz, KX, KY y Hz. Consulte el [README en inglés](../README.md) para la API, el ámbito, las limitaciones y la licencia.
