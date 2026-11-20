"""Carga la identidad regional de La Guajira en alojamientos y sitios turísticos."""
from django.db import migrations

INFORMACION_TURISTICA = (
    "Riohacha, capital de La Guajira, combina las playas del Caribe, la cultura "
    "Wayuu y la tradición del vallenato. Desde Posada Wayra puedes caminar hasta "
    "el Muelle y el paseo de la playa, o emprender tours a las Dunas de Taroa, el "
    "Cabo de la Vela y el Santuario de Fauna y Flora Los Flamencos. La mejor época "
    "para visitar es entre diciembre y abril."
)

SITIOS = [
    {
        "nombre": "Atardeceres en el Muelle",
        "descripcion": "El paseo del Muelle de Riohacha es el punto ideal para ver el atardecer sobre el mar Caribe y probar la gastronomía local.",
        "municipio": "Riohacha",
        "distancia_km": 0.5,
        "imagen": "sitios/riohacha-atardecer.jpg",
        "orden": 1,
    },
    {
        "nombre": "Santuario Los Flamencos",
        "descripcion": "Reserva natural en Camarones donde habitan flamencos rosados y aves migratorias entre manglares y lagunas.",
        "municipio": "Camarones",
        "distancia_km": 25,
        "imagen": "sitios/riohacha-flamencos.jpg",
        "orden": 2,
    },
    {
        "nombre": "Cabo de la Vela",
        "descripcion": "Paraíso desértico frente al mar, con playas como Pilón de Azúcar y la energía espiritual del pueblo Wayuu.",
        "municipio": "Uribia",
        "distancia_km": 160,
        "imagen": "sitios/riohacha-cabo.jpg",
        "orden": 3,
    },
    {
        "nombre": "Dunas de Taroa",
        "descripcion": "Inmensas dunas doradas que caen al mar en la Alta Guajira; se recorren en 4x4 junto a guías de la comunidad.",
        "municipio": "Uribia",
        "distancia_km": 300,
        "imagen": "sitios/riohacha-dunas.jpg",
        "orden": 4,
    },
]

FOTOS = [
    ("Fachada y zonas comunes", "alojamientos/galeria/wayra-fondo.jpg", 1),
    ("Atardecer frente al mar", "alojamientos/galeria/riohacha-atardecer.jpg", 2),
    ("Playas de La Guajira", "alojamientos/galeria/riohacha-cabo.jpg", 3),
    ("Dunas y desierto", "alojamientos/galeria/riohacha-dunas.jpg", 4),
]


def cargar_datos(apps, schema_editor):
    Alojamiento = apps.get_model("syshsena", "Alojamiento")
    SitioTuristico = apps.get_model("syshsena", "SitioTuristico")
    FotografiaAlojamiento = apps.get_model("syshsena", "FotografiaAlojamiento")

    sitios = []
    for datos in SITIOS:
        sitio, _ = SitioTuristico.objects.get_or_create(
            nombre=datos["nombre"], defaults=datos
        )
        sitios.append(sitio)

    for alojamiento in Alojamiento.objects.all():
        cambios = []
        if not alojamiento.informacion_turistica:
            alojamiento.informacion_turistica = INFORMACION_TURISTICA
            cambios.append("informacion_turistica")
        if not alojamiento.imagen:
            alojamiento.imagen = "alojamientos/wayra-fondo.jpg"
            cambios.append("imagen")
        if cambios:
            alojamiento.save(update_fields=cambios)

        alojamiento.sitios_turisticos.add(*sitios)

        if not FotografiaAlojamiento.objects.filter(alojamiento=alojamiento).exists():
            for titulo, imagen, orden in FOTOS:
                FotografiaAlojamiento.objects.create(
                    alojamiento=alojamiento,
                    titulo=titulo,
                    imagen=imagen,
                    orden=orden,
                )


def revertir(apps, schema_editor):
    Alojamiento = apps.get_model("syshsena", "Alojamiento")
    SitioTuristico = apps.get_model("syshsena", "SitioTuristico")
    FotografiaAlojamiento = apps.get_model("syshsena", "FotografiaAlojamiento")

    FotografiaAlojamiento.objects.all().delete()
    for alojamiento in Alojamiento.objects.all():
        alojamiento.sitios_turisticos.clear()
        alojamiento.informacion_turistica = None
        alojamiento.imagen = None
        alojamiento.save(update_fields=["informacion_turistica", "imagen"])
    SitioTuristico.objects.filter(
        nombre__in=[s["nombre"] for s in SITIOS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("syshsena", "0010_modulo_completo_wayra"),
    ]

    operations = [
        migrations.RunPython(cargar_datos, revertir),
    ]
