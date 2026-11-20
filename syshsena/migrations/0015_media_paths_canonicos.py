from pathlib import PurePosixPath

from django.core.files.storage import default_storage
from django.db import migrations, models


RUTAS_GALERIA = {
    "riohacha-atardecer.jpg": "sitios/riohacha-atardecer.jpg",
    "riohacha-cabo.jpg": "sitios/riohacha-cabo.jpg",
    "riohacha-dunas.jpg": "sitios/riohacha-dunas.jpg",
    "wayra-fondo.jpg": "alojamientos/wayra-fondo.jpg",
}


def _archivos_iguales(storage, origen, destino):
    with storage.open(origen, "rb") as archivo_origen, storage.open(destino, "rb") as archivo_destino:
        while True:
            bloque_origen = archivo_origen.read(64 * 1024)
            bloque_destino = archivo_destino.read(64 * 1024)
            if bloque_origen != bloque_destino:
                return False
            if not bloque_origen:
                return True


def _normalizar_campo(modelo, campo, prefijo, construir_destino, alias_db):
    storage = default_storage
    for pk, valor in modelo.objects.using(alias_db).values_list("pk", campo).iterator():
        if not valor or not valor.startswith(prefijo):
            continue

        nombre = PurePosixPath(valor).name
        destino = construir_destino(nombre)
        if storage.exists(valor):
            if storage.exists(destino):
                if not _archivos_iguales(storage, valor, destino):
                    destino = storage.get_available_name(destino)
                    with storage.open(valor, "rb") as origen:
                        destino = storage.save(destino, origen)
                else:
                    storage.delete(valor)
            else:
                with storage.open(valor, "rb") as origen:
                    destino = storage.save(destino, origen)
                storage.delete(valor)
        elif not storage.exists(destino):
            continue

        modelo.objects.using(alias_db).filter(pk=pk).update(**{campo: destino})


def normalizar_archivos_media(apps, schema_editor):
    alias_db = schema_editor.connection.alias
    fotografia = apps.get_model("syshsena", "FotografiaAlojamiento")
    servicio = apps.get_model("syshsena", "Servicio")
    configuracion = apps.get_model("syshsena", "ConfiguracionHotel")

    _normalizar_campo(
        fotografia,
        "imagen",
        "alojamientos/galeria/",
        lambda nombre: RUTAS_GALERIA.get(nombre, f"alojamientos/galeria_{nombre}"),
        alias_db,
    )
    _normalizar_campo(
        servicio,
        "imagen",
        "servicios/",
        lambda nombre: (
            f"alojamientos/{nombre}"
            if nombre in {
                "arepahuevo.jpg",
                "arrozcoco.jpg",
                "motequeso.webp",
                "postacartagena.jpg",
            }
            else f"alojamientos/servicio_{nombre}"
        ),
        alias_db,
    )
    for campo in ("logo", "banner"):
        _normalizar_campo(
            configuracion,
            campo,
            "configuracion/",
            lambda nombre: f"alojamientos/configuracion_{nombre}",
            alias_db,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("syshsena", "0014_datos_institucionales_y_media"),
    ]

    operations = [
        migrations.AlterField(
            model_name="configuracionhotel",
            name="logo",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="alojamientos/",
                verbose_name="Logo",
            ),
        ),
        migrations.AlterField(
            model_name="configuracionhotel",
            name="banner",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="alojamientos/",
                verbose_name="Banner principal",
            ),
        ),
        migrations.AlterField(
            model_name="fotografiaalojamiento",
            name="imagen",
            field=models.ImageField(upload_to="alojamientos/", verbose_name="Fotografía"),
        ),
        migrations.AlterField(
            model_name="servicio",
            name="imagen",
            field=models.ImageField(blank=True, null=True, upload_to="alojamientos/"),
        ),
        migrations.RunPython(normalizar_archivos_media, migrations.RunPython.noop),
    ]
