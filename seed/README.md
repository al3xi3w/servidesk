# Datos ficticios (responsable: Daniel)
- `generate.py`: Faker es_ES -> CSV por tabla y tenant en `seed/out/`.
- `load`: subir `seed/out/` al bucket seed y ejecutar la Lambda `seed-loader` de cada servicio.
Meta: tabla principal de cada servicio = 30 000 filas (10 000 por tenant).
