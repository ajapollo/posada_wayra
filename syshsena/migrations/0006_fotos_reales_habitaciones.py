"""Asigna las fotos REALES a las habitaciones 01, 02, 03 y 04."""
from django.db import migrations

FOTOS = {
    "01": "habitaciones/01.jpg",
    "02": "habitaciones/02.jpg",
    "03": "habitaciones/03.jpg",
    "04": "habitaciones/04.jpg",
}


def asignar_fotos(apps, schema_editor):
    Habitacion = apps.get_model("syshsena", "Habitacion")
    
    # 1. Limpia cualquier foto en la habitación 06
    Habitacion.objects.filter(numero="06").update(imagen="")
    
    # 2. Asigna las fotos reales a las habitaciones 01, 02, 03 y 04
    for numero, ruta in FOTOS.items():
        Habitacion.objects.filter(numero=numero).update(imagen=ruta)


def quitar_fotos(apps, schema_editor):
    Habitacion = apps.get_model("syshsena", "Habitacion")
    for numero in FOTOS.keys():
        Habitacion.objects.filter(numero=numero).update(imagen="")


class Migration(migrations.Migration):

    dependencies = [
        ("syshsena", "0004_habitacion_imagen"),  # <-- Asegúrate de que este sea el nombre exacto de tu migración anterior
    ]

    operations = [
        migrations.RunPython(asignar_fotos, quitar_fotos),
    ]