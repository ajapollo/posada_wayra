from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from syshsena.models import Habitacion, Reserva


class Command(BaseCommand):
    help = "Lista llegadas vencidas; sólo --aplicar cancela las reservas sin check-in."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Aplicar las cancelaciones de no-show.")

    def handle(self, *args, **options):
        pendientes = Reserva.objects.filter(
            estado__in=[Reserva.PENDIENTE, Reserva.CONFIRMADA],
            fecha_inicio__lt=date.today(), fecha_checkin__isnull=True,
        ).order_by("pk")
        candidatos = list(pendientes.values_list("pk", "habitacion_id"))
        if not options["aplicar"]:
            self.stdout.write(f"Simulación: {len(candidatos)} reservas vencidas. No se modificó ningún dato.")
            self.stdout.write("Reservas: " + ", ".join(str(pk) for pk, _ in candidatos))
            return
        procesadas = 0
        for pk, habitacion_id in candidatos:
            with transaction.atomic():
                Habitacion.objects.select_for_update().get(pk=habitacion_id)
                reserva = pendientes.select_for_update().filter(pk=pk, habitacion_id=habitacion_id).first()
                if reserva is None:
                    continue
                reserva.estado = Reserva.CANCELADA
                reserva.cancelacion_solicitada = False
                reserva.save(update_fields=["estado", "cancelacion_solicitada"])
                procesadas += 1
        self.stdout.write(self.style.SUCCESS(f"Canceladas: {procesadas}. Pagos e historial conservados."))
