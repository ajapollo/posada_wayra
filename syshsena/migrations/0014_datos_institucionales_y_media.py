from django.db import migrations


SERVICIOS_IMAGENES = {
    "arepa": "servicios/arepahuevo.jpg",
    "mote": "servicios/motequeso.webp",
    "pescado": "servicios/arrozcoco.jpg",
    "posta": "servicios/postacartagena.jpg",
}


def aplicar_datos(apps, schema_editor):
    ConfiguracionHotel = apps.get_model("syshsena", "ConfiguracionHotel")
    Alojamiento = apps.get_model("syshsena", "Alojamiento")
    Servicio = apps.get_model("syshsena", "Servicio")
    Habitacion = apps.get_model("syshsena", "Habitacion")

    configuracion, _ = ConfiguracionHotel.objects.get_or_create(pk=1)
    configuracion.nombre = "Posada Wayra"
    configuracion.direccion = "Cl. 1 # 9-95, Riohacha, La Guajira, Colombia"
    configuracion.ciudad = "Riohacha"
    configuracion.departamento = "La Guajira"
    configuracion.pais = "Colombia"
    configuracion.telefono = "+57 322 220 352"
    configuracion.whatsapp = "+57 322 220 352"
    configuracion.email = "posadawayra@gmail.com"
    configuracion.horario_checkin = "3:00 p.m."
    configuracion.horario_checkout = "11:00 a.m."
    configuracion.politicas = (
        "Check-in desde las 3:00 p.m. y check-out hasta las 11:00 a.m. "
        "Para garantizar la reserva se requiere abonar mínimo 1 noche. "
        "El huésped debe presentarse el primer día pactado; de no realizar el "
        "check-in durante ese día, la reserva se cancela automáticamente sin "
        "derecho a reembolso. No se permite fumar dentro de las habitaciones. "
        "El documento de identidad es obligatorio al registrar la llegada."
    )
    configuracion.save()

    principal = (
        Alojamiento.objects.filter(habitaciones__isnull=False)
        .distinct()
        .order_by("id")
        .first()
    ) or Alojamiento.objects.order_by("id").first()

    if principal:
        principal.nombre = "Posada Wayra"
        principal.municipio = "Riohacha"
        principal.direccion = "Cl. 1 # 9-95, Riohacha, La Guajira, Colombia"
        principal.telefono = "+57 322 220 352"
        principal.email = "posadawayra@gmail.com"
        principal.save()

    duplicados = Alojamiento.objects.exclude(pk=principal.pk if principal else None).filter(
        nombre__icontains="Cabo Vela"
    )
    for duplicado in duplicados:
        sin_dependencias = (
            not Habitacion.objects.filter(alojamiento_id=duplicado.pk).exists()
            and not Servicio.objects.filter(alojamiento_id=duplicado.pk).exists()
        )
        if sin_dependencias:
            duplicado.delete()
        else:
            duplicado.nombre = "Posada Wayra"
            duplicado.save(update_fields=["nombre"])

    for servicio in Servicio.objects.all():
        nombre = (servicio.nombre or "").lower()
        for clave, ruta in SERVICIOS_IMAGENES.items():
            if clave in nombre:
                servicio.imagen = ruta
                servicio.imagen_url = None
                servicio.save(update_fields=["imagen", "imagen_url"])
                break


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("syshsena", "0013_configuracionhotel_usuario_avatar_and_more"),
    ]

    operations = [
        migrations.RunPython(aplicar_datos, revertir),
    ]
