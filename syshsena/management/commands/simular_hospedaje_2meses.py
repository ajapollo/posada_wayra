import random
from datetime import datetime, timedelta, date, time
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from syshsena.models import (
    Habitacion,
    Huesped,
    Pago,
    Reserva,
    Servicio,
    ServicioReserva,
)


def _dt(fecha, hora):
    """Construye un datetime compatible tanto si USE_TZ es True como False."""
    dt = datetime.combine(fecha, hora)
    if getattr(settings, "USE_TZ", False):
        return timezone.make_aware(dt)
    return dt


HUESPEDES_DEMO = [
    ("CC", "1065842101", "Camila", "Mendoza", "3004128890", "camila.mendoza@ejemplo.com", "Colombiana", "Bogotá", "Colombia", False),
    ("CC", "1121893402", "Andrés", "Ríos", "3115239901", "andres.rios@ejemplo.com", "Colombiana", "Medellín", "Colombia", False),
    ("CC", "84092115", "Carlos", "Iguarán", "3156782341", "carlos.iguaran@ejemplo.com", "Colombiana", "Riohacha", "Colombia", False),
    ("CC", "1045712890", "Valentina", "Pineda", "3018904512", "valen.pineda@ejemplo.com", "Colombiana", "Barranquilla", "Colombia", False),
    ("CE", "458921", "Lucas", "Martin", "3209871122", "lucas.martin@ejemplo.com", "Francesa", "París", "Francia", True),
    ("PA", "US8943120", "Emily", "Carter", "3147789021", "emily.carter@ejemplo.com", "Estadounidense", "Miami", "Estados Unidos", True),
    ("CC", "1082945120", "Mateo", "Gutiérrez", "3124567890", "mateo.g@ejemplo.com", "Colombiana", "Santa Marta", "Colombia", False),
    ("CC", "52891430", "Diana", "Ospina", "3183451290", "diana.ospina@ejemplo.com", "Colombiana", "Cali", "Colombia", False),
    ("PA", "DE9920145", "Hannah", "Weber", "3176540987", "hannah.weber@ejemplo.com", "Alemana", "Berlín", "Alemania", True),
    ("CC", "1065901234", "Santiago", "Daza", "3024456677", "santiago.daza@ejemplo.com", "Colombiana", "Valledupar", "Colombia", False),
    ("CC", "1018456902", "Laura", "Restrepo", "3102348765", "laura.restrepo@ejemplo.com", "Colombiana", "Bucaramanga", "Colombia", False),
    ("CE", "782341", "Matteo", "Rossi", "3198765432", "matteo.rossi@ejemplo.com", "Italiana", "Milán", "Italia", True),
]


class Command(BaseCommand):
    help = "Simula 2 meses de operación hotelera (reservas, estadías, servicios y pagos) sin overbooking."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limpiar",
            action="store_true",
            help="Borra reservas, pagos y consumos previos antes de generar la simulación.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        habitaciones = list(
            Habitacion.objects.select_related("tipo", "alojamiento")
            .exclude(estado=Habitacion.MANTENIMIENTO)
            .order_by("numero")
        )
        if not habitaciones:
            self.stdout.write(self.style.ERROR("No hay habitaciones registradas para simular."))
            return

        if options["limpiar"]:
            Pago.objects.all().delete()
            ServicioReserva.objects.all().delete()
            Reserva.objects.all().delete()
            Habitacion.objects.exclude(estado=Habitacion.MANTENIMIENTO).update(estado=Habitacion.DISPONIBLE)
            self.stdout.write(self.style.WARNING("Historial previo limpiado."))

        # 1. Crear o recuperar huéspedes de demostración
        huespedes = []
        for doc_tipo, doc_num, nom, ape, tel, mail, nac, ciu, pais, ext in HUESPEDES_DEMO:
            huesped, _ = Huesped.objects.get_or_create(
                numero_documento=doc_num,
                defaults={
                    "tipo_documento": doc_tipo,
                    "nombre": nom,
                    "apellido": ape,
                    "telefono": tel,
                    "email": mail,
                    "nacionalidad": nac,
                    "ciudad_residencia": ciu,
                    "pais_residencia": pais,
                    "es_extranjero": ext,
                },
            )
            huespedes.append(huesped)

        todos_huespedes = list(Huesped.objects.all()) or huespedes
        servicios = list(Servicio.objects.all())
        metodos = [Pago.EFECTIVO, Pago.TRANSFERENCIA, Pago.TARJETA]

        hoy = date.today()
        inicio_sim = hoy - timedelta(days=45)
        fin_sim = hoy + timedelta(days=15)

        total_reservas = 0
        total_pagos = 0
        total_consumos = 0

        # 2. Recorrer habitación por habitación generando bloques sin solapamiento
        for idx_hab, hab in enumerate(habitaciones):
            cursor = inicio_sim + timedelta(days=random.randint(0, 2))
            hab_tiene_estadia_hoy = False

            while cursor < fin_sim:
                noches = random.randint(1, 4)
                entrada = cursor
                salida = entrada + timedelta(days=noches)
                huesped = random.choice(todos_huespedes)
                personas = random.randint(1, max(1, hab.capacidad))

                if salida <= hoy:
                    estado = Reserva.FINALIZADA if random.random() < 0.85 else Reserva.CANCELADA
                elif entrada <= hoy < salida:
                    if idx_hab % 2 == 0:
                        estado = Reserva.EN_ESTADIA
                        hab_tiene_estadia_hoy = True
                    else:
                        cursor = hoy + timedelta(days=1)
                        continue
                elif entrada == hoy:
                    estado = random.choice([Reserva.CONFIRMADA, Reserva.PENDIENTE])
                else:
                    estado = random.choices(
                        [Reserva.CONFIRMADA, Reserva.PENDIENTE, Reserva.CANCELADA],
                        weights=[60, 30, 10],
                        k=1,
                    )[0]

                reserva = Reserva.objects.create(
                    huesped=huesped,
                    habitacion=hab,
                    num_personas=personas,
                    fecha_inicio=entrada,
                    fecha_fin=salida,
                    estado=estado,
                )

                dias_anticipacion = random.randint(1, 7)
                fecha_crea = _dt(
                    entrada - timedelta(days=dias_anticipacion),
                    time(random.randint(9, 20), random.randint(0, 59)),
                )
                Reserva.objects.filter(id=reserva.id).update(fecha_creacion=fecha_crea)

                if estado in (Reserva.EN_ESTADIA, Reserva.FINALIZADA):
                    reserva.fecha_checkin = _dt(entrada, time(15, random.randint(0, 45)))
                if estado == Reserva.FINALIZADA:
                    reserva.fecha_checkout = _dt(salida, time(11, random.randint(0, 30)))
                if estado in (Reserva.EN_ESTADIA, Reserva.FINALIZADA):
                    reserva.save(update_fields=["fecha_checkin", "fecha_checkout"])

                total_servicios = Decimal("0")
                if servicios and estado in (Reserva.EN_ESTADIA, Reserva.FINALIZADA):
                    for _ in range(random.randint(1, 3)):
                        srv = random.choice(servicios)
                        cant = random.randint(1, 2)
                        ServicioReserva.objects.create(
                            reserva=reserva,
                            servicio=srv,
                            cantidad=cant,
                            precio_unitario=srv.precio,
                        )
                        total_servicios += srv.precio * cant
                        total_consumos += 1

                total_hospedaje = hab.precio_noche * noches
                gran_total = total_hospedaje + total_servicios

                if estado == Reserva.FINALIZADA:
                    abono = hab.precio_noche
                    saldo = gran_total - abono
                    p1 = Pago.objects.create(
                        reserva=reserva,
                        monto=abono,
                        metodo_pago=random.choice(metodos),
                        observacion="Abono inicial de reserva",
                    )
                    Pago.objects.filter(id=p1.id).update(fecha_pago=fecha_crea)
                    total_pagos += 1

                    if saldo > 0:
                        p2 = Pago.objects.create(
                            reserva=reserva,
                            monto=saldo,
                            metodo_pago=random.choice(metodos),
                            observacion="Liquidación en check-out",
                        )
                        Pago.objects.filter(id=p2.id).update(fecha_pago=_dt(salida, time(10, 50)))
                        total_pagos += 1

                elif estado in (Reserva.EN_ESTADIA, Reserva.CONFIRMADA, Reserva.PENDIENTE):
                    abono = min(hab.precio_noche, gran_total)
                    p1 = Pago.objects.create(
                        reserva=reserva,
                        monto=abono,
                        metodo_pago=random.choice(metodos),
                        observacion="Garantía mínima de 1 noche",
                    )
                    Pago.objects.filter(id=p1.id).update(fecha_pago=fecha_crea)
                    total_pagos += 1

                total_reservas += 1
                cursor = salida + timedelta(days=random.randint(1, 3))

            hab.estado = Habitacion.OCUPADA if hab_tiene_estadia_hoy else Habitacion.DISPONIBLE
            hab.save(update_fields=["estado"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Simulación de 2 meses completada: {total_reservas} reservas, "
                f"{total_consumos} consumos de servicios y {total_pagos} pagos registrados."
            )
        )