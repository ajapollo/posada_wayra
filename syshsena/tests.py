from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import ImporteForm, OcupacionForm, validar_imagen
from .models import (
    Alojamiento,
    ConfiguracionHotel,
    FotografiaHabitacion,
    Huesped,
    Habitacion,
    Pago,
    Reserva,
    Rol,
    Servicio,
    ServicioReserva,
    SitioTuristico,
    TipoHabitacion,
    Usuario,
)
from .view import _crear_pago, _habitaciones_ocupadas, _habitaciones_publicas


class AuditoriaBase(TestCase):
    password = "Viento!Seguro-4827"

    def setUp(self):
        super().setUp()
        # Nunca ejecutar la limpieza de seeds con la configuración de producción.
        self.assertEqual(settings.SETTINGS_MODULE, "syshsena.test_settings")
        self.assertEqual(connection.vendor, "sqlite")
        nombre_db = str(connection.settings_dict["NAME"])
        self.assertTrue(
            nombre_db == ":memory:"
            or (nombre_db.startswith("file:") and "mode=memory" in nombre_db),
            "Esta suite sólo puede modificar la base SQLite de pruebas en memoria.",
        )
        self.media_temporal = TemporaryDirectory(prefix="wayra-auditoria-")
        self.addCleanup(self.media_temporal.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_temporal.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        # TestCase revierte esta limpieza y los escenarios al terminar cada prueba.
        # El orden respeta las FK PROTECT y elimina los datos históricos del seed.
        for modelo in (
            Pago, ServicioReserva, Reserva, Huesped, Usuario,
            FotografiaHabitacion, Habitacion, TipoHabitacion, Servicio,
            Alojamiento, SitioTuristico, ConfiguracionHotel, Rol,
        ):
            modelo.objects.all().delete()

        self.hoy = date.today()
        self.entrada = self.hoy + timedelta(days=10)
        self.salida = self.entrada + timedelta(days=3)
        self.rol_admin = Rol.objects.create(nombre=Rol.ADMINISTRADOR)
        self.rol_cliente = Rol.objects.create(nombre=Rol.CLIENTE)
        self.rol_recepcion = Rol.objects.create(nombre=Rol.RECEPCIONISTA)
        self.rol_gerente = Rol.objects.create(nombre=Rol.GERENTE)
        self.admin = Usuario.objects.create_user(
            username="administracion_prueba", password=self.password,
            email="admin@example.com", rol=self.rol_admin, is_staff=True,
        )
        self.cliente_usuario = Usuario.objects.create_user(
            username="viajera_prueba", password=self.password,
            first_name="Ana", last_name="Prueba", email="ana@example.com",
            rol=self.rol_cliente,
        )
        self.otro_usuario = Usuario.objects.create_user(
            username="otro_viajero", password=self.password,
            first_name="Luis", last_name="Prueba", email="luis@example.com",
            rol=self.rol_cliente,
        )
        self.huesped = self.cliente_usuario.huesped
        self.huesped.numero_documento = "AUD-10001"
        self.huesped.save()
        self.otro_huesped = self.otro_usuario.huesped
        self.otro_huesped.numero_documento = "AUD-10002"
        self.otro_huesped.save()
        self.alojamiento = Alojamiento.objects.create(nombre="Posada de pruebas")
        self.individual = TipoHabitacion.objects.create(
            nombre="Individual", capacidad=2, max_adultos=1, max_ninos=1,
        )
        self.doble = TipoHabitacion.objects.create(
            nombre="Doble", capacidad=3, max_adultos=2, max_ninos=1,
        )
        self.independiente = TipoHabitacion.objects.create(
            nombre="Total independiente", capacidad=3, max_adultos=3, max_ninos=2,
        )
        self.sin_ninos = TipoHabitacion.objects.create(
            nombre="Sólo adultos", capacidad=2, max_adultos=2, max_ninos=0,
        )
        self.habitacion = self.nueva_habitacion("101", self.doble)
        self.habitacion_individual = self.nueva_habitacion("102", self.individual)
        self.habitacion_independiente = self.nueva_habitacion("103", self.independiente)
        self.habitacion_sin_ninos = self.nueva_habitacion("104", self.sin_ninos)
        self.servicio = Servicio.objects.create(
            nombre="Desayuno de prueba", precio=Decimal("15000.00"),
            alojamiento=self.alojamiento,
        )
        self.sitio = SitioTuristico.objects.create(nombre="Sitio de prueba")
        self.alojamiento.sitios_turisticos.add(self.sitio)
        self.staff = Client()
        self.staff.force_login(self.admin)
        self.guest = Client()
        self.guest.force_login(self.cliente_usuario)

    def nueva_habitacion(self, numero, tipo):
        return Habitacion.objects.create(
            numero=numero, tipo=tipo, alojamiento=self.alojamiento,
            precio_noche=Decimal("100000.00"), imagen="",
        )

    def nueva_reserva(self, **cambios):
        datos = {
            "huesped": self.huesped, "habitacion": self.habitacion,
            "fecha_inicio": self.entrada, "fecha_fin": self.salida,
            "num_adultos": 2, "num_ninos": 1, "num_personas": 3,
        }
        datos.update(cambios)
        return Reserva.objects.create(**datos)

    def datos_reserva(self, **cambios):
        datos = {
            "habitacion": str(self.habitacion.pk), "huesped": str(self.huesped.pk),
            "fecha_entrada": self.entrada.isoformat(), "fecha_salida": self.salida.isoformat(),
            "adultos": "2", "ninos": "1", "monto_abono": "100000.00",
            "metodo_pago": Pago.EFECTIVO,
        }
        datos.update(cambios)
        return datos

    def datos_habitacion(self, habitacion=None, **cambios):
        habitacion = habitacion or self.habitacion
        datos = {
            "numero": habitacion.numero, "tipo": str(habitacion.tipo_id),
            "alojamiento": str(habitacion.alojamiento_id),
            "precio_noche": str(habitacion.precio_noche), "piso": str(habitacion.piso),
            "estado": habitacion.estado,
        }
        datos.update(cambios)
        return datos

    def datos_registro(self, **cambios):
        datos = {
            "username": "nueva_viajera", "nombre": "Marina", "apellido": "Rojas",
            "correo": "marina@example.com", "tipo_documento": "CC",
            "numero_documento": "AUD-20001", "password": self.password,
            "password2": self.password,
        }
        datos.update(cambios)
        return datos

    def imagen(self, nombre="foto.png", formato="PNG", tamano=None):
        contenido = BytesIO()
        Image.new("RGB", (16, 16), color=(25, 120, 180)).save(contenido, format=formato)
        datos = contenido.getvalue()
        if tamano is not None:
            datos += b"\0" * max(0, tamano - len(datos))
        return SimpleUploadedFile(nombre, datos, content_type=Image.MIME[formato])

    def foto_galeria(self, habitacion=None, orden=0):
        return FotografiaHabitacion.objects.create(
            habitacion=habitacion or self.habitacion, imagen=self.imagen(), orden=orden,
        )

    def assert_rechazo_reserva(self, cliente, ruta, datos):
        antes = (Reserva.objects.count(), Pago.objects.count())
        respuesta = cliente.post(reverse(ruta), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        self.assertEqual((Reserva.objects.count(), Pago.objects.count()), antes)
        return respuesta


class OcupacionModelosTests(AuditoriaBase):
    def test_individual_admite_un_adulto_con_o_sin_nino(self):
        for adultos, ninos, esperado in ((1, 0, True), (1, 1, True), (2, 0, False), (1, 2, False), (0, 1, False)):
            with self.subTest(adultos=adultos, ninos=ninos):
                self.assertEqual(self.individual.admite(adultos, ninos), esperado)

    def test_doble_admite_dos_adultos_y_un_nino(self):
        for adultos, ninos, esperado in ((2, 1, True), (2, 0, True), (1, 1, True), (3, 0, False), (2, 2, False)):
            with self.subTest(adultos=adultos, ninos=ninos):
                self.assertEqual(self.doble.admite(adultos, ninos), esperado)

    def test_capacidad_total_independiente_de_maximos(self):
        self.independiente.full_clean()
        self.assertEqual(self.independiente.capacidad, 3)
        self.assertTrue(self.independiente.admite(2, 1))
        self.assertTrue(self.independiente.admite(1, 2))
        self.assertTrue(self.independiente.admite(3, 0))
        self.assertFalse(self.independiente.admite(3, 1))
        self.assertFalse(self.independiente.admite(2, 2))

    def test_cero_ninos_es_valido_y_se_conserva(self):
        self.sin_ninos.full_clean()
        self.sin_ninos.refresh_from_db()
        self.assertEqual(self.sin_ninos.max_ninos, 0)
        self.assertTrue(self.sin_ninos.admite(2, 0))
        self.assertFalse(self.sin_ninos.admite(1, 1))
        self.assertEqual(self.habitacion_sin_ninos.max_ninos, 0)

    def test_tipo_rechaza_limites_inconsistentes(self):
        for capacidad, adultos, ninos in ((0, 1, 0), (2, 0, 0), (2, 3, 0), (2, 1, 2), (2, 1, -1)):
            with self.subTest(capacidad=capacidad, adultos=adultos, ninos=ninos):
                tipo = TipoHabitacion(nombre="Inválido", capacidad=capacidad, max_adultos=adultos, max_ninos=ninos)
                with self.assertRaises(ValidationError):
                    tipo.full_clean()

    def test_tipo_malformado_produce_validationerror_no_typeerror(self):
        for campo in ("capacidad", "max_adultos", "max_ninos"):
            for valor in ("no-es-entero", None):
                with self.subTest(campo=campo, valor=valor):
                    tipo = TipoHabitacion(nombre="Malformado", capacidad=3, max_adultos=2, max_ninos=1)
                    setattr(tipo, campo, valor)
                    with self.assertRaises(ValidationError):
                        tipo.full_clean()

    def test_reserva_historica_sin_desglose_sigue_valida(self):
        reserva = self.nueva_reserva(num_adultos=None, num_ninos=None, num_personas=2)
        reserva.full_clean()
        reserva.refresh_from_db()
        self.assertIsNone(reserva.num_adultos)
        self.assertIsNone(reserva.num_ninos)
        self.assertEqual(reserva.num_personas, 2)

    def test_reserva_rechaza_desglose_incompleto(self):
        for adultos, ninos in ((None, 0), (1, None)):
            with self.subTest(adultos=adultos, ninos=ninos):
                reserva = Reserva(
                    huesped=self.huesped, habitacion=self.habitacion, fecha_inicio=self.entrada,
                    fecha_fin=self.salida, num_personas=1, num_adultos=adultos, num_ninos=ninos,
                )
                with self.assertRaises(ValidationError):
                    reserva.full_clean()

    def test_reserva_rechaza_total_inconsistente_y_combinacion_excesiva(self):
        for adultos, ninos, total in ((2, 1, 2), (3, 0, 3), (0, 1, 1), (2, 2, 4)):
            with self.subTest(adultos=adultos, ninos=ninos, total=total):
                reserva = Reserva(
                    huesped=self.huesped, habitacion=self.habitacion, fecha_inicio=self.entrada,
                    fecha_fin=self.salida, num_personas=total, num_adultos=adultos, num_ninos=ninos,
                )
                with self.assertRaises(ValidationError):
                    reserva.full_clean()

    def test_form_ocupacion_no_convierte_datos_invalidos_en_defaults(self):
        for datos in ({}, {"adultos": "0", "ninos": "1"}, {"adultos": "2.5", "ninos": "0"},
                      {"adultos": "NaN", "ninos": "0"}, {"adultos": "1", "ninos": "-1"}):
            with self.subTest(datos=datos):
                self.assertFalse(OcupacionForm(datos).is_valid())
        form = OcupacionForm({"adultos": "1", "ninos": "0"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data, {"adultos": 1, "ninos": 0})


class ReservasPostTests(AuditoriaBase):
    def test_cliente_crea_reserva_futura_con_desglose_y_abono(self):
        respuesta = self.guest.post(reverse("cliente_reservar"), self.datos_reserva())
        self.assertRedirects(respuesta, reverse("cliente_mis_reservas"), fetch_redirect_response=False)
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.huesped, self.huesped)
        self.assertEqual((reserva.num_adultos, reserva.num_ninos, reserva.num_personas), (2, 1, 3))
        self.assertEqual((reserva.fecha_inicio, reserva.fecha_fin), (self.entrada, self.salida))
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        self.assertEqual(reserva.tarifa_noche, Decimal("100000.00"))
        self.assertEqual(reserva.pagos.get().monto, Decimal("100000.00"))

    def test_staff_crea_reserva_pendiente_sin_pago_implicito(self):
        respuesta = self.staff.post(reverse("registrar_reserva"), self.datos_reserva())
        reserva = Reserva.objects.get()
        self.assertRedirects(respuesta, reverse("ver_reserva", args=[reserva.pk]), fetch_redirect_response=False)
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        self.assertEqual((reserva.num_adultos, reserva.num_ninos, reserva.num_personas), (2, 1, 3))
        self.assertFalse(reserva.pagos.exists())

    def test_ambos_portales_rechazan_adultos_ausentes_o_no_positivos(self):
        for cliente, ruta in ((self.guest, "cliente_reservar"), (self.staff, "registrar_reserva")):
            for valor in (None, "", "0", "-1", "2.5", "texto", "NaN"):
                with self.subTest(ruta=ruta, adultos=valor):
                    datos = self.datos_reserva(adultos=valor or "")
                    if valor is None:
                        datos.pop("adultos")
                    self.assert_rechazo_reserva(cliente, ruta, datos)

    def test_ambos_portales_rechazan_ninos_invalidos_o_adicionales(self):
        for cliente, ruta in ((self.guest, "cliente_reservar"), (self.staff, "registrar_reserva")):
            for valor in (None, "", "-1", "1.5", "texto", "2"):
                with self.subTest(ruta=ruta, ninos=valor):
                    datos = self.datos_reserva(ninos=valor or "")
                    if valor is None:
                        datos.pop("ninos")
                    self.assert_rechazo_reserva(cliente, ruta, datos)

    def test_ambos_portales_respetan_individual_doble_y_total_independiente(self):
        for cliente, ruta in ((self.guest, "cliente_reservar"), (self.staff, "registrar_reserva")):
            for habitacion, adultos, ninos in ((self.habitacion_individual, "2", "0"),
                                               (self.habitacion, "3", "0"),
                                               (self.habitacion_independiente, "3", "1")):
                with self.subTest(ruta=ruta, habitacion=habitacion.numero):
                    self.assert_rechazo_reserva(
                        cliente, ruta, self.datos_reserva(habitacion=str(habitacion.pk), adultos=adultos, ninos=ninos),
                    )

    def test_cliente_puede_reservar_tipo_sin_ninos(self):
        respuesta = self.guest.post(reverse("cliente_reservar"), self.datos_reserva(
            habitacion=str(self.habitacion_sin_ninos.pk), ninos="0",
        ))
        self.assertEqual(respuesta.status_code, 302)
        reserva = Reserva.objects.get()
        self.assertEqual((reserva.num_adultos, reserva.num_ninos, reserva.num_personas), (2, 0, 2))

    def test_solapamiento_rechazado_cliente_y_staff(self):
        respuesta = self.guest.post(reverse("cliente_reservar"), self.datos_reserva())
        self.assertEqual(respuesta.status_code, 302)
        for cliente, ruta in ((self.guest, "cliente_reservar"), (self.staff, "registrar_reserva")):
            with self.subTest(ruta=ruta):
                self.assert_rechazo_reserva(cliente, ruta, self.datos_reserva(
                    fecha_entrada=(self.entrada + timedelta(days=1)).isoformat(),
                    fecha_salida=(self.salida + timedelta(days=1)).isoformat(),
                ))
        self.assertEqual(Reserva.objects.count(), 1)
        self.assertEqual(Pago.objects.count(), 1)

    def test_cancelacion_libera_fechas_sin_borrar_historial(self):
        reserva = self.nueva_reserva()
        pago = Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        respuesta = self.staff.post(reverse("cancelar_reserva", args=[reserva.pk]))
        self.assertEqual(respuesta.status_code, 302)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.CANCELADA)
        self.assertTrue(Pago.objects.filter(pk=pago.pk).exists())
        self.assertEqual(self.guest.post(reverse("cliente_reservar"), self.datos_reserva()).status_code, 302)
        self.assertEqual(Reserva.objects.count(), 2)

    def test_fechas_adyacentes_no_son_solapamiento(self):
        self.nueva_reserva()
        respuesta = self.staff.post(reverse("registrar_reserva"), self.datos_reserva(
            fecha_entrada=self.salida.isoformat(), fecha_salida=(self.salida + timedelta(days=2)).isoformat(),
        ))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Reserva.objects.count(), 2)

    def test_ambos_portales_rechazan_fechas_invalidas_sin_reservar_hoy(self):
        escenarios = (
            {"fecha_entrada": "no-es-fecha"}, {"fecha_salida": "2026-02-30"},
            {"fecha_entrada": ""}, {"fecha_salida": ""},
            {"fecha_salida": self.entrada.isoformat()},
            {"fecha_salida": (self.entrada - timedelta(days=1)).isoformat()},
            {"fecha_entrada": (self.hoy - timedelta(days=1)).isoformat()},
        )
        for cliente, ruta in ((self.guest, "cliente_reservar"), (self.staff, "registrar_reserva")):
            for cambios in escenarios:
                with self.subTest(ruta=ruta, cambios=cambios):
                    self.assert_rechazo_reserva(cliente, ruta, self.datos_reserva(**cambios))

    def test_staff_no_puede_crear_reserva_confirmada_o_en_estadia_por_post(self):
        for estado in (Reserva.CONFIRMADA, Reserva.EN_ESTADIA, Reserva.FINALIZADA):
            with self.subTest(estado=estado):
                self.assert_rechazo_reserva(self.staff, "registrar_reserva", self.datos_reserva(estado=estado))

    def test_editar_no_permite_saltarse_acciones_de_estado(self):
        reserva = self.nueva_reserva()
        respuesta = self.staff.post(reverse("editar_reserva", args=[reserva.pk]), self.datos_reserva(estado=Reserva.EN_ESTADIA))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        self.assertIsNone(reserva.fecha_checkin)

    def test_tarifa_snapshot_se_conserva_tras_cambio_y_edicion(self):
        reserva = self.nueva_reserva()
        self.habitacion.precio_noche = Decimal("175000.00")
        self.habitacion.save(update_fields=["precio_noche"])
        reserva.refresh_from_db()
        self.assertEqual(reserva.tarifa_noche, Decimal("100000.00"))
        self.assertEqual(reserva.valor_habitacion_total, Decimal("300000.00"))
        respuesta = self.staff.post(reverse("editar_reserva", args=[reserva.pk]), self.datos_reserva())
        self.assertEqual(respuesta.status_code, 302)
        reserva.refresh_from_db()
        self.assertEqual(reserva.tarifa_noche, Decimal("100000.00"))
        nueva = self.nueva_reserva(fecha_inicio=self.salida, fecha_fin=self.salida + timedelta(days=1))
        self.assertEqual(nueva.tarifa_noche, Decimal("175000.00"))

    def test_reserva_no_puede_suplantar_huesped_desde_portal_cliente(self):
        respuesta = self.guest.post(reverse("cliente_reservar"), self.datos_reserva(huesped=str(self.otro_huesped.pk)))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Reserva.objects.get().huesped_id, self.huesped.pk)


class DisponibilidadTests(AuditoriaBase):
    def test_estadia_actual_bloquea_solapamiento_futuro_programado(self):
        reserva = self.nueva_reserva(
            fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=20),
            estado=Reserva.EN_ESTADIA, fecha_checkin=timezone.now(),
        )
        self.assertIn(reserva.habitacion_id, _habitaciones_ocupadas(self.entrada, self.salida))
        self.assertFalse(_habitaciones_publicas(self.entrada, self.salida, 2, 1).filter(pk=self.habitacion.pk).exists())

    def test_estadia_vencida_sin_checkout_bloquea_hoy_no_todo_el_futuro(self):
        self.nueva_reserva(
            fecha_inicio=self.hoy - timedelta(days=5), fecha_fin=self.hoy - timedelta(days=1),
            estado=Reserva.EN_ESTADIA, fecha_checkin=timezone.now() - timedelta(days=5),
        )
        self.assertIn(self.habitacion.pk, _habitaciones_ocupadas(self.hoy, self.hoy + timedelta(days=1)))
        self.assertNotIn(self.habitacion.pk, _habitaciones_ocupadas(self.entrada, self.salida))
        self.assertTrue(_habitaciones_publicas(self.entrada, self.salida, 2, 1).filter(pk=self.habitacion.pk).exists())

    def test_checkout_real_evitar_bloqueo_por_estadia_vencida(self):
        self.nueva_reserva(
            fecha_inicio=self.hoy - timedelta(days=5), fecha_fin=self.hoy - timedelta(days=1),
            estado=Reserva.EN_ESTADIA, fecha_checkin=timezone.now() - timedelta(days=5),
            fecha_checkout=timezone.now() - timedelta(days=1),
        )
        self.assertNotIn(self.habitacion.pk, _habitaciones_ocupadas(self.hoy, self.hoy + timedelta(days=1)))

    def test_disponibilidad_respeta_total_y_cero_ninos(self):
        ids = set(_habitaciones_publicas(self.entrada, self.salida, 2, 1).values_list("pk", flat=True))
        self.assertEqual(ids, {self.habitacion.pk, self.habitacion_independiente.pk})
        self.assertFalse(_habitaciones_publicas(self.entrada, self.salida, 3, 1).exists())
        self.assertTrue(_habitaciones_publicas(self.entrada, self.salida, 2, 0).filter(pk=self.habitacion_sin_ninos.pk).exists())

    def test_limpieza_bloquea_hoy_pero_no_reserva_futura_mantenimiento_siempre(self):
        self.habitacion.estado = Habitacion.LIMPIEZA
        self.habitacion.save(update_fields=["estado"])
        self.assertFalse(_habitaciones_publicas(self.hoy, self.hoy + timedelta(days=1), 2, 1).filter(pk=self.habitacion.pk).exists())
        self.assertTrue(_habitaciones_publicas(self.entrada, self.salida, 2, 1).filter(pk=self.habitacion.pk).exists())
        self.habitacion.estado = Habitacion.MANTENIMIENTO
        self.habitacion.save(update_fields=["estado"])
        self.assertFalse(_habitaciones_publicas(self.entrada, self.salida, 2, 1).filter(pk=self.habitacion.pk).exists())

    def test_get_publicos_y_staff_no_cancelan_no_shows(self):
        reserva = self.nueva_reserva(fecha_inicio=self.hoy - timedelta(days=2), fecha_fin=self.hoy + timedelta(days=1))
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        antes = list(Reserva.objects.values("pk", "estado", "cancelacion_solicitada", "fecha_checkin", "fecha_checkout"))
        for cliente, ruta, args in (
            (self.client, "posada_wayra", []), (self.client, "posada_habitaciones", []),
            (self.client, "posada_ver_habitacion", [self.habitacion.pk]),
            (self.guest, "cliente_mis_reservas", []),
            (self.guest, "cliente_ver_reserva", [reserva.pk]),
            (self.staff, "listar_reservas", []), (self.staff, "rutina_dia", []),
            (self.staff, "disponibilidad", []),
        ):
            with self.subTest(ruta=ruta):
                respuesta = cliente.get(reverse(ruta, args=args))
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(list(Reserva.objects.values("pk", "estado", "cancelacion_solicitada", "fecha_checkin", "fecha_checkout")), antes)
                self.assertEqual(Pago.objects.count(), 1)


class ImportesPagosTests(AuditoriaBase):
    importes_invalidos = ("NaN", "sNaN", "Infinity", "-Infinity", "-0.01", "1.001", "10000000000.00", "1e100", "", "texto")

    def test_importe_form_rechaza_no_finitos_negativos_precision_y_limite(self):
        for monto in self.importes_invalidos:
            with self.subTest(monto=monto):
                self.assertFalse(ImporteForm({"monto": monto}).is_valid())

    def test_importe_form_admite_cero_y_maximo_finito_doce_digitos(self):
        for monto in ("0", "0.01", "9999999999.99"):
            with self.subTest(monto=monto):
                form = ImporteForm({"monto": monto})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["monto"], Decimal(monto))
                self.assertTrue(form.cleaned_data["monto"].is_finite())

    def test_crear_pago_rechaza_importes_sin_escrituras(self):
        reserva = self.nueva_reserva()
        for monto in self.importes_invalidos + ("0", "300000.01"):
            with self.subTest(monto=monto):
                self.assertTrue(_crear_pago(reserva, monto, Pago.EFECTIVO))
                self.assertFalse(reserva.pagos.exists())

    def test_endpoints_pago_rechazan_importes_inseguros(self):
        reserva = self.nueva_reserva()
        for ruta, args in (("registrar_pago", [reserva.pk]), ("pagos", [])):
            for monto in self.importes_invalidos + ("0", "300000.01"):
                with self.subTest(ruta=ruta, monto=monto):
                    respuesta = self.staff.post(reverse(ruta, args=args), {
                        "reserva": str(reserva.pk), "monto": monto, "metodo_pago": Pago.EFECTIVO,
                    })
                    self.assertEqual(respuesta.status_code, 302)
                    self.assertFalse(reserva.pagos.exists())

    def test_cliente_rechaza_abono_inseguro_inferior_y_superior_sin_reserva_parcial(self):
        for monto in self.importes_invalidos + ("0", "99999.99", "300000.01"):
            with self.subTest(monto=monto):
                self.assert_rechazo_reserva(self.guest, "cliente_reservar", self.datos_reserva(monto_abono=monto))

    def test_metodo_invalido_rechazado_en_helper_y_ambos_endpoints(self):
        reserva = self.nueva_reserva()
        self.assertTrue(_crear_pago(reserva, "100000.00", "CRIPTO"))
        for ruta, args in (("registrar_pago", [reserva.pk]), ("pagos", [])):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.staff.post(reverse(ruta, args=args), {
                    "reserva": str(reserva.pk), "monto": "100000.00", "metodo_pago": "CRIPTO",
                }).status_code, 302)
                self.assertFalse(reserva.pagos.exists())
        self.assert_rechazo_reserva(self.guest, "cliente_reservar", self.datos_reserva(
            habitacion=str(self.habitacion_independiente.pk), metodo_pago="CRIPTO",
        ))

    def test_pago_valido_y_segundo_exceso_usa_saldo_actual(self):
        reserva = self.nueva_reserva()
        self.assertIsNone(_crear_pago(reserva, "200000.00", Pago.TRANSFERENCIA, "REF-AUD"))
        self.assertTrue(_crear_pago(reserva, "100000.01", Pago.EFECTIVO))
        self.assertIsNone(_crear_pago(reserva, "100000.00", Pago.TARJETA))
        self.assertTrue(_crear_pago(reserva, "0.01", Pago.EFECTIVO))
        self.assertEqual(reserva.total_pagado, Decimal("300000.00"))
        self.assertEqual(reserva.saldo_pendiente, Decimal("0.00"))
        self.assertEqual(reserva.pagos.count(), 2)

    def test_helper_relee_reserva_y_no_confia_en_instancia_obsoleta(self):
        reserva = self.nueva_reserva()
        Reserva.objects.filter(pk=reserva.pk).update(estado=Reserva.CANCELADA)
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        self.assertTrue(_crear_pago(reserva, "100000.00", Pago.EFECTIVO))
        self.assertFalse(reserva.pagos.exists())

    def test_helper_valida_referencia_antes_de_insertar(self):
        reserva = self.nueva_reserva()
        self.assertTrue(_crear_pago(reserva, "100000.00", Pago.EFECTIVO, comprobante="X" * 101))
        self.assertFalse(reserva.pagos.exists())


class OperacionSeguridadTests(AuditoriaBase):
    def test_mutaciones_staff_get_devuelve_405_a_administrador_autorizado(self):
        reserva = self.nueva_reserva()
        pago = Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        consumo = ServicioReserva.objects.create(reserva=reserva, servicio=self.servicio)
        foto = self.foto_galeria()
        rutas = (
            ("cancelar_reserva", [reserva.pk]), ("confirmar_reserva", [reserva.pk]),
            ("checkin_reserva", [reserva.pk]), ("checkout_reserva", [reserva.pk]),
            ("registrar_pago", [reserva.pk]), ("eliminar_pago", [pago.pk]),
            ("agregar_servicio_reserva", [reserva.pk]), ("eliminar_servicio_reserva", [consumo.pk]),
            ("cambiar_estado_habitacion", [self.habitacion.pk]),
            ("eliminar_habitacion", [self.habitacion.pk]), ("eliminar_fotografia_habitacion", [foto.pk]),
            ("eliminar_huesped", [self.huesped.pk]), ("eliminar_tipo", [self.doble.pk]),
            ("eliminar_servicio", [self.servicio.pk]), ("eliminar_usuario", [self.otro_usuario.pk]),
            ("eliminar_rol", [self.rol_cliente.pk]), ("eliminar_sitio", [self.sitio.pk]), ("logout", []),
        )
        for ruta, args in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.staff.get(reverse(ruta, args=args)).status_code, 405)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        self.assertEqual((Pago.objects.count(), ServicioReserva.objects.count(), FotografiaHabitacion.objects.count()), (1, 1, 1))

    def test_mutaciones_cliente_get_devuelve_405_sin_cambiar_datos(self):
        reserva = self.nueva_reserva()
        for ruta, args in (("cliente_reservar", []), ("cliente_solicitar_cancelacion", [reserva.pk]), ("logout", [])):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.guest.get(reverse(ruta, args=args)).status_code, 405)
        reserva.refresh_from_db()
        self.assertFalse(reserva.cancelacion_solicitada)
        self.assertEqual(Reserva.objects.count(), 1)

    def test_csrf_obligatorio_en_mutaciones_staff(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        reserva = self.nueva_reserva()
        pago = Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        consumo = ServicioReserva.objects.create(reserva=reserva, servicio=self.servicio)
        foto = self.foto_galeria()
        rutas = (
            ("cancelar_reserva", [reserva.pk]), ("confirmar_reserva", [reserva.pk]),
            ("checkin_reserva", [reserva.pk]), ("checkout_reserva", [reserva.pk]),
            ("registrar_pago", [reserva.pk]), ("pagos", []), ("eliminar_pago", [pago.pk]),
            ("agregar_servicio_reserva", [reserva.pk]), ("eliminar_servicio_reserva", [consumo.pk]),
            ("cambiar_estado_habitacion", [self.habitacion.pk]),
            ("registrar_habitacion", []), ("editar_habitacion", [self.habitacion.pk]),
            ("eliminar_fotografia_habitacion", [foto.pk]), ("eliminar_huesped", [self.huesped.pk]),
            ("registrar_tipo", []), ("editar_tipo", [self.doble.pk]), ("registrar_reserva", []),
            ("editar_reserva", [reserva.pk]), ("perfil", []), ("logout", []),
        )
        for ruta, args in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.post(reverse(ruta, args=args), {"estado": Habitacion.DISPONIBLE}).status_code, 403)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        self.assertEqual((Pago.objects.count(), ServicioReserva.objects.count(), FotografiaHabitacion.objects.count()), (1, 1, 1))

    def test_csrf_obligatorio_cliente_y_signup(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.cliente_usuario)
        reserva = self.nueva_reserva()
        for ruta, args in (("cliente_reservar", []), ("cliente_solicitar_cancelacion", [reserva.pk]), ("perfil", [])):
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.post(reverse(ruta, args=args), self.datos_reserva()).status_code, 403)
        anonimo = Client(enforce_csrf_checks=True)
        self.assertEqual(anonimo.post(reverse("registro_cliente"), self.datos_registro()).status_code, 403)
        reserva.refresh_from_db()
        self.assertFalse(reserva.cancelacion_solicitada)
        self.assertEqual(Reserva.objects.count(), 1)

    def test_csrf_token_valido_permite_cancelacion_post(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        reserva = self.nueva_reserva()
        self.assertEqual(cliente.get(reverse("ver_reserva", args=[reserva.pk])).status_code, 200)
        token = cliente.cookies[settings.CSRF_COOKIE_NAME].value
        respuesta = cliente.post(reverse("cancelar_reserva", args=[reserva.pk]), {"csrfmiddlewaretoken": token})
        self.assertEqual(respuesta.status_code, 302)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.CANCELADA)

    def test_confirmar_requiere_una_noche_de_abono_snapshot(self):
        reserva = self.nueva_reserva()
        self.assertEqual(self.staff.post(reverse("confirmar_reserva", args=[reserva.pk])).status_code, 302)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        pago = Pago.objects.create(reserva=reserva, monto=Decimal("99999.99"))
        self.staff.post(reverse("confirmar_reserva", args=[reserva.pk]))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        pago.monto = Decimal("100000.00")
        pago.save()
        self.habitacion.precio_noche = Decimal("200000.00")
        self.habitacion.save()
        self.staff.post(reverse("confirmar_reserva", args=[reserva.pk]))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.CONFIRMADA)

    def test_checkin_requiere_abono_y_actualiza_habitacion(self):
        reserva = self.nueva_reserva(fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=2), estado=Reserva.CONFIRMADA)
        self.staff.post(reverse("checkin_reserva", args=[reserva.pk]))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.CONFIRMADA)
        self.assertIsNone(reserva.fecha_checkin)
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        self.staff.post(reverse("checkin_reserva", args=[reserva.pk]))
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.EN_ESTADIA)
        self.assertIsNotNone(reserva.fecha_checkin)
        self.assertEqual(self.habitacion.estado, Habitacion.OCUPADA)
        fecha_checkin = reserva.fecha_checkin
        self.staff.post(reverse("checkin_reserva", args=[reserva.pk]))
        reserva.refresh_from_db()
        self.assertEqual(reserva.fecha_checkin, fecha_checkin)

    def test_checkin_no_permite_llegada_futura_ni_pendiente(self):
        for estado, entrada in ((Reserva.PENDIENTE, self.hoy), (Reserva.CONFIRMADA, self.entrada)):
            with self.subTest(estado=estado, entrada=entrada):
                reserva = self.nueva_reserva(estado=estado, fecha_inicio=entrada, fecha_fin=entrada + timedelta(days=2))
                Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
                self.staff.post(reverse("checkin_reserva", args=[reserva.pk]))
                reserva.refresh_from_db()
                self.assertEqual(reserva.estado, estado)
                self.assertIsNone(reserva.fecha_checkin)
                reserva.estado = Reserva.CANCELADA
                reserva.save()

    def test_checkin_rechaza_habitacion_en_limpieza_o_mantenimiento(self):
        reserva = self.nueva_reserva(fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=2), estado=Reserva.CONFIRMADA)
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        for estado in (Habitacion.LIMPIEZA, Habitacion.MANTENIMIENTO):
            with self.subTest(estado=estado):
                self.habitacion.estado = estado
                self.habitacion.save()
                self.staff.post(reverse("checkin_reserva", args=[reserva.pk]))
                reserva.refresh_from_db()
                self.assertEqual(reserva.estado, Reserva.CONFIRMADA)
                self.assertIsNone(reserva.fecha_checkin)

    def test_checkout_requiere_saldo_cero_y_deja_limpieza(self):
        reserva = self.nueva_reserva(fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=2), estado=Reserva.EN_ESTADIA, fecha_checkin=timezone.now())
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        self.staff.post(reverse("checkout_reserva", args=[reserva.pk]))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.EN_ESTADIA)
        self.assertIsNone(reserva.fecha_checkout)
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        self.staff.post(reverse("checkout_reserva", args=[reserva.pk]))
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.FINALIZADA)
        self.assertIsNotNone(reserva.fecha_checkout)
        self.assertEqual(self.habitacion.estado, Habitacion.LIMPIEZA)

    def test_no_puede_fabricar_estado_ocupada_sin_checkin(self):
        respuesta = self.staff.post(reverse("cambiar_estado_habitacion", args=[self.habitacion.pk]), {"estado": Habitacion.OCUPADA})
        self.assertEqual(respuesta.status_code, 302)
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, Habitacion.DISPONIBLE)
        respuesta = self.staff.post(reverse("registrar_habitacion"), self.datos_habitacion(numero="999", estado=Habitacion.OCUPADA))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Habitacion.objects.filter(numero="999").exists())

    def test_habitacion_ocupada_no_se_libera_desde_estado_o_edicion_admin(self):
        self.nueva_reserva(estado=Reserva.EN_ESTADIA, fecha_checkin=timezone.now())
        for estado in (Habitacion.DISPONIBLE, Habitacion.LIMPIEZA, Habitacion.MANTENIMIENTO):
            with self.subTest(estado=estado):
                self.staff.post(reverse("cambiar_estado_habitacion", args=[self.habitacion.pk]), {"estado": estado})
                self.habitacion.refresh_from_db()
                self.assertEqual(self.habitacion.estado, Habitacion.OCUPADA)
                respuesta = self.staff.post(reverse("editar_habitacion", args=[self.habitacion.pk]), self.datos_habitacion(estado=estado, precio_noche="999.00"))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["error"])
                self.habitacion.refresh_from_db()
                self.assertEqual(self.habitacion.estado, Habitacion.OCUPADA)
                self.assertEqual(self.habitacion.precio_noche, Decimal("100000.00"))

    def test_pago_de_garantia_no_puede_eliminarse_durante_estadia(self):
        reserva = self.nueva_reserva(estado=Reserva.EN_ESTADIA, fecha_checkin=timezone.now())
        pago = Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        self.staff.post(reverse("eliminar_pago", args=[pago.pk]))
        self.assertTrue(Pago.objects.filter(pk=pago.pk).exists())

    def test_cliente_y_gerente_no_pueden_mutar_reservas_staff(self):
        gerente = Usuario.objects.create_user(username="gerente_prueba", password=self.password, rol=self.rol_gerente)
        cliente_gerente = Client()
        cliente_gerente.force_login(gerente)
        reserva = self.nueva_reserva()
        for cliente in (self.guest, cliente_gerente):
            for ruta in ("cancelar_reserva", "confirmar_reserva", "checkin_reserva", "checkout_reserva", "registrar_pago", "agregar_servicio_reserva"):
                with self.subTest(usuario=cliente.session["_auth_user_id"], ruta=ruta):
                    self.assertEqual(cliente.post(reverse(ruta, args=[reserva.pk]), {
                        "monto": "100000.00", "metodo_pago": Pago.EFECTIVO,
                        "servicio": str(self.servicio.pk), "cantidad": "1",
                    }).status_code, 302)
                    reserva.refresh_from_db()
                    self.assertEqual(reserva.estado, Reserva.PENDIENTE)
                    self.assertFalse(reserva.pagos.exists())
                    self.assertFalse(reserva.servicios_consumidos.exists())

    def test_factura_terminal_pagos_consumos_y_reserva_inmutables(self):
        for estado in (Reserva.CANCELADA, Reserva.FINALIZADA):
            with self.subTest(estado=estado):
                reserva = self.nueva_reserva(estado=estado)
                pago = Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
                consumo = ServicioReserva.objects.create(reserva=reserva, servicio=self.servicio, cantidad=2)
                antes = (reserva.tarifa_noche, reserva.gran_total, reserva.total_pagado, reserva.fecha_inicio, reserva.fecha_fin)
                for ruta, args, datos in (
                    ("registrar_pago", [reserva.pk], {"monto": "1.00", "metodo_pago": Pago.EFECTIVO}),
                    ("pagos", [], {"reserva": str(reserva.pk), "monto": "1.00", "metodo_pago": Pago.EFECTIVO}),
                    ("eliminar_pago", [pago.pk], {}),
                    ("agregar_servicio_reserva", [reserva.pk], {"servicio": str(self.servicio.pk), "cantidad": "1"}),
                    ("eliminar_servicio_reserva", [consumo.pk], {}),
                    ("editar_reserva", [reserva.pk], self.datos_reserva(adultos="1", ninos="0")),
                    ("cancelar_reserva", [reserva.pk], {}), ("confirmar_reserva", [reserva.pk], {}),
                    ("checkin_reserva", [reserva.pk], {}), ("checkout_reserva", [reserva.pk], {}),
                ):
                    with self.subTest(ruta=ruta):
                        self.assertEqual(self.staff.post(reverse(ruta, args=args), datos).status_code, 302)
                        reserva.refresh_from_db()
                        self.assertEqual(reserva.estado, estado)
                        self.assertEqual((reserva.tarifa_noche, reserva.gran_total, reserva.total_pagado, reserva.fecha_inicio, reserva.fecha_fin), antes)
                        self.assertTrue(Pago.objects.filter(pk=pago.pk).exists())
                        self.assertTrue(ServicioReserva.objects.filter(pk=consumo.pk).exists())

    def test_servicio_rechaza_cantidad_invalida_y_otro_alojamiento(self):
        reserva = self.nueva_reserva()
        otro_alojamiento = Alojamiento.objects.create(nombre="Otro establecimiento")
        otro_servicio = Servicio.objects.create(nombre="Ajeno", precio=Decimal("100.00"), alojamiento=otro_alojamiento)
        for servicio, cantidad in ((self.servicio, "0"), (self.servicio, "-1"), (self.servicio, "1.5"),
                                   (self.servicio, "2147483648"), (otro_servicio, "1")):
            with self.subTest(servicio=servicio.pk, cantidad=cantidad):
                self.assertEqual(self.staff.post(reverse("agregar_servicio_reserva", args=[reserva.pk]), {
                    "servicio": str(servicio.pk), "cantidad": cantidad,
                }).status_code, 302)
                self.assertFalse(reserva.servicios_consumidos.exists())


class NoShowsHistorialTests(AuditoriaBase):
    def test_comando_no_shows_default_simula_sin_mutaciones(self):
        reserva = self.nueva_reserva(fecha_inicio=self.hoy - timedelta(days=3), fecha_fin=self.hoy - timedelta(days=1))
        pago = Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        salida = StringIO()
        call_command("procesar_no_shows", stdout=salida)
        self.assertIn("Simulación", salida.getvalue())
        self.assertIn(str(reserva.pk), salida.getvalue())
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)
        self.assertEqual(self.habitacion.estado, Habitacion.DISPONIBLE)
        self.assertTrue(Pago.objects.filter(pk=pago.pk).exists())

    def test_comando_aplicar_solo_cancela_vencidas_sin_checkin_conserva_pagos(self):
        pendiente = self.nueva_reserva(fecha_inicio=self.hoy - timedelta(days=3), fecha_fin=self.hoy - timedelta(days=1), cancelacion_solicitada=True)
        confirmada = self.nueva_reserva(habitacion=self.habitacion_independiente, estado=Reserva.CONFIRMADA, fecha_inicio=self.hoy - timedelta(days=2), fecha_fin=self.hoy + timedelta(days=1))
        hoy = self.nueva_reserva(fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=1))
        futura = self.nueva_reserva()
        estadia = self.nueva_reserva(habitacion=self.habitacion_individual, num_adultos=1, num_ninos=1, num_personas=2, estado=Reserva.EN_ESTADIA, fecha_inicio=self.hoy - timedelta(days=4), fecha_fin=self.hoy - timedelta(days=1), fecha_checkin=timezone.now() - timedelta(days=4))
        con_checkin = self.nueva_reserva(estado=Reserva.CONFIRMADA, fecha_inicio=self.hoy - timedelta(days=2), fecha_fin=self.hoy + timedelta(days=1), fecha_checkin=timezone.now() - timedelta(days=2))
        cancelada = self.nueva_reserva(estado=Reserva.CANCELADA, fecha_inicio=self.hoy - timedelta(days=2))
        finalizada = self.nueva_reserva(estado=Reserva.FINALIZADA, fecha_inicio=self.hoy - timedelta(days=2))
        pago = Pago.objects.create(reserva=pendiente, monto=Decimal("100000.00"))
        salida = StringIO()
        call_command("procesar_no_shows", aplicar=True, stdout=salida)
        self.assertIn("Canceladas: 2", salida.getvalue())
        for reserva in (pendiente, confirmada):
            reserva.refresh_from_db()
            self.assertEqual(reserva.estado, Reserva.CANCELADA)
            self.assertFalse(reserva.cancelacion_solicitada)
        for reserva, esperado in ((hoy, Reserva.PENDIENTE), (futura, Reserva.PENDIENTE), (estadia, Reserva.EN_ESTADIA),
                                   (con_checkin, Reserva.CONFIRMADA), (cancelada, Reserva.CANCELADA), (finalizada, Reserva.FINALIZADA)):
            reserva.refresh_from_db()
            self.assertEqual(reserva.estado, esperado)
        self.assertEqual(Reserva.objects.count(), 8)
        self.assertTrue(Pago.objects.filter(pk=pago.pk, monto=Decimal("100000.00")).exists())
        self.habitacion_individual.refresh_from_db()
        self.assertEqual(self.habitacion_individual.estado, Habitacion.OCUPADA)
        segunda = StringIO()
        call_command("procesar_no_shows", aplicar=True, stdout=segunda)
        self.assertIn("Canceladas: 0", segunda.getvalue())

    def test_fk_huesped_protect_incluso_reserva_cancelada(self):
        for estado in (Reserva.PENDIENTE, Reserva.CANCELADA, Reserva.FINALIZADA):
            with self.subTest(estado=estado):
                reserva = self.nueva_reserva(estado=estado)
                with self.assertRaises(ProtectedError):
                    self.huesped.delete()
                self.assertTrue(Reserva.objects.filter(pk=reserva.pk).exists())
                self.assertTrue(Huesped.objects.filter(pk=self.huesped.pk).exists())

    def test_endpoint_eliminar_huesped_preserva_reservas_y_pagos(self):
        reserva = self.nueva_reserva(estado=Reserva.CANCELADA)
        pago = Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        respuesta = self.staff.post(reverse("eliminar_huesped", args=[self.huesped.pk]))
        self.assertRedirects(respuesta, reverse("listar_huespedes"), fetch_redirect_response=False)
        self.assertTrue(Huesped.objects.filter(pk=self.huesped.pk).exists())
        self.assertTrue(Reserva.objects.filter(pk=reserva.pk).exists())
        self.assertTrue(Pago.objects.filter(pk=pago.pk).exists())

    def test_cliente_no_puede_ver_ni_cancelar_reserva_de_otro_404(self):
        reserva = self.nueva_reserva(huesped=self.otro_huesped)
        self.assertEqual(self.guest.get(reverse("cliente_ver_reserva", args=[reserva.pk])).status_code, 404)
        self.assertEqual(self.guest.post(reverse("cliente_solicitar_cancelacion", args=[reserva.pk])).status_code, 404)
        reserva.refresh_from_db()
        self.assertFalse(reserva.cancelacion_solicitada)
        self.assertEqual(reserva.estado, Reserva.PENDIENTE)

    def test_mis_reservas_solo_muestra_propias_y_solicitud_no_cancela_automaticamente(self):
        propia = self.nueva_reserva()
        ajena = self.nueva_reserva(huesped=self.otro_huesped, habitacion=self.habitacion_independiente)
        respuesta = self.guest.get(reverse("cliente_mis_reservas"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(set(respuesta.context["vigentes"].values_list("pk", flat=True)), {propia.pk})
        self.assertNotIn(ajena.pk, respuesta.context["historial"].values_list("pk", flat=True))
        self.assertEqual(self.guest.post(reverse("cliente_solicitar_cancelacion", args=[propia.pk])).status_code, 302)
        propia.refresh_from_db()
        self.assertTrue(propia.cancelacion_solicitada)
        self.assertEqual(propia.estado, Reserva.PENDIENTE)
        self.assertIn(self.habitacion.pk, _habitaciones_ocupadas(self.entrada, self.salida))


class RegistroCredencialesTests(AuditoriaBase):
    def test_signup_dos_usuarios_documentos_distintos_y_password_hasheado(self):
        for username, documento in (("alta_primera", "AUD-30001"), ("alta_segunda", "AUD-30002")):
            with self.subTest(username=username):
                cliente = Client()
                respuesta = cliente.post(reverse("registro_cliente"), self.datos_registro(
                    username=username, numero_documento=documento, correo=f"{username}@example.com",
                ))
                self.assertEqual(respuesta.status_code, 302)
                usuario = Usuario.objects.get(username=username)
                self.assertEqual(usuario.rol, self.rol_cliente)
                self.assertTrue(usuario.check_password(self.password))
                self.assertNotEqual(usuario.password, self.password)
                self.assertEqual(usuario.huesped.numero_documento, documento)
                self.assertEqual(usuario.huesped.email, f"{username}@example.com")
                self.assertEqual(cliente.session["_auth_user_id"], str(usuario.pk))
        self.assertEqual(Huesped.objects.filter(numero_documento__in=["AUD-30001", "AUD-30002"]).count(), 2)

    def test_signup_password_debil_email_invalido_y_confirmacion_no_crean_datos(self):
        for cambios in ({"password": "12345678", "password2": "12345678"},
                        {"correo": "no-es-email"}, {"password2": "Otra!Clave-5839"}):
            with self.subTest(cambios=cambios):
                antes = (Usuario.objects.count(), Huesped.objects.count())
                respuesta = self.client.post(reverse("registro_cliente"), self.datos_registro(**cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["error"])
                self.assertEqual((Usuario.objects.count(), Huesped.objects.count()), antes)
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_signup_documento_duplicado_revierte_usuario_y_perfil_de_senal(self):
        antes = (Usuario.objects.count(), Huesped.objects.count())
        respuesta = self.client.post(reverse("registro_cliente"), self.datos_registro(numero_documento=self.huesped.numero_documento))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        self.assertEqual((Usuario.objects.count(), Huesped.objects.count()), antes)
        self.assertFalse(Usuario.objects.filter(username="nueva_viajera").exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_senal_crea_documentos_provisionales_unicos(self):
        primero = Usuario.objects.create_user(username="senal_primera", rol=self.rol_cliente)
        segundo = Usuario.objects.create_user(username="senal_segunda", rol=self.rol_cliente)
        self.assertEqual(primero.huesped.numero_documento, f"PEND-{primero.pk}")
        self.assertEqual(segundo.huesped.numero_documento, f"PEND-{segundo.pk}")
        self.assertNotEqual(primero.huesped.numero_documento, segundo.huesped.numero_documento)

    def test_staff_alta_usuario_valida_password_y_email_sin_perfil_parcial(self):
        for cambios in ({"password": "12345678"}, {"email": "invalido"}):
            with self.subTest(cambios=cambios):
                datos = {"username": "alta_staff", "password": self.password, "email": "alta@example.com", "rol": str(self.rol_cliente.pk)}
                datos.update(cambios)
                antes = (Usuario.objects.count(), Huesped.objects.count())
                respuesta = self.staff.post(reverse("registrar_usuario"), datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["error"])
                self.assertEqual((Usuario.objects.count(), Huesped.objects.count()), antes)

    def test_perfil_password_incorrecta_debil_y_confirmacion_no_alteran_hash(self):
        hash_original = self.cliente_usuario.password
        for actual, nueva, confirmacion in (("incorrecta", self.password, self.password),
                                            (self.password, "12345678", "12345678"),
                                            (self.password, "Nueva!Segura-9128", "Distinta!Segura-8137")):
            with self.subTest(actual=actual, nueva=nueva):
                respuesta = self.guest.post(reverse("perfil"), {
                    "accion": "password", "password_actual": actual,
                    "password_nueva": nueva, "password_confirmar": confirmacion,
                })
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["error"])
                self.cliente_usuario.refresh_from_db()
                self.assertEqual(self.cliente_usuario.password, hash_original)

    def test_perfil_password_valida_actualiza_y_conserva_sesion(self):
        nueva = "Nueva!Segura-9128"
        respuesta = self.guest.post(reverse("perfil"), {
            "accion": "password", "password_actual": self.password,
            "password_nueva": nueva, "password_confirmar": nueva,
        })
        self.assertRedirects(respuesta, reverse("perfil"), fetch_redirect_response=False)
        self.cliente_usuario.refresh_from_db()
        self.assertTrue(self.cliente_usuario.check_password(nueva))
        self.assertEqual(self.guest.get(reverse("perfil")).status_code, 200)

    def test_perfil_email_invalido_no_modifica_usuario_ni_huesped(self):
        antes = (self.cliente_usuario.first_name, self.cliente_usuario.email, self.huesped.nombre, self.huesped.email)
        respuesta = self.guest.post(reverse("perfil"), {"accion": "datos", "first_name": "Cambiado", "email": "invalido"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        self.cliente_usuario.refresh_from_db()
        self.huesped.refresh_from_db()
        self.assertEqual((self.cliente_usuario.first_name, self.cliente_usuario.email, self.huesped.nombre, self.huesped.email), antes)


class FotosCapacidadAdminTests(AuditoriaBase):
    def test_validar_imagen_admite_jpeg_png_webp_y_rebobina(self):
        for formato, nombre in (("JPEG", "foto.jpg"), ("PNG", "foto.png"), ("WEBP", "foto.webp")):
            with self.subTest(formato=formato):
                archivo = validar_imagen(self.imagen(nombre, formato))
                self.assertEqual(archivo.image.format, formato)
                self.assertEqual(archivo.tell(), 0)

    def test_validar_imagen_rechaza_falso_archivo_gif_y_mas_de_8mb(self):
        archivos = (
            SimpleUploadedFile("falso.jpg", b"no es una imagen", content_type="image/jpeg"),
            self.imagen("animacion.gif", "GIF"),
            self.imagen(tamano=8 * 1024 * 1024 + 1),
        )
        for archivo in archivos:
            with self.subTest(archivo=archivo.name, tamano=archivo.size):
                with self.assertRaises(ValidationError):
                    validar_imagen(archivo)

    def test_validar_imagen_limite_exactamente_8mb(self):
        archivo = validar_imagen(self.imagen(tamano=8 * 1024 * 1024))
        self.assertEqual(archivo.size, 8 * 1024 * 1024)
        self.assertEqual(archivo.tell(), 0)

    def test_alta_habitacion_varias_fotos_y_principal_en_media_temporal(self):
        datos = self.datos_habitacion(numero="201")
        datos.update(imagen=self.imagen("principal.jpg", "JPEG"), fotografias=[self.imagen("uno.png"), self.imagen("dos.webp", "WEBP")])
        respuesta = self.staff.post(reverse("registrar_habitacion"), datos)
        self.assertRedirects(respuesta, reverse("listar_habitaciones"), fetch_redirect_response=False)
        habitacion = Habitacion.objects.get(numero="201")
        fotos = list(habitacion.fotografias.all())
        self.assertEqual(len(fotos), 2)
        self.assertEqual([foto.orden for foto in fotos], [0, 1])
        for archivo in [habitacion.imagen] + [foto.imagen for foto in fotos]:
            self.assertTrue(Path(archivo.path).is_relative_to(Path(self.media_temporal.name)))
            self.assertTrue(Path(archivo.path).is_file())
            with Image.open(archivo.path) as imagen:
                imagen.verify()

    def test_alta_una_foto_invalida_no_guarda_habitacion_ni_galeria_parcial(self):
        datos = self.datos_habitacion(numero="202")
        datos.update(imagen=self.imagen("principal.png"), fotografias=[self.imagen("buena.png"), SimpleUploadedFile("mala.png", b"invalida", content_type="image/png")])
        antes = (Habitacion.objects.count(), FotografiaHabitacion.objects.count())
        respuesta = self.staff.post(reverse("registrar_habitacion"), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        self.assertEqual((Habitacion.objects.count(), FotografiaHabitacion.objects.count()), antes)
        self.assertFalse(Habitacion.objects.filter(numero="202").exists())
        self.assertFalse(any(Path(self.media_temporal.name).rglob("*.*")))

    def test_edicion_una_foto_invalida_revierte_tarifa_orden_y_nuevas_fotos(self):
        foto = self.foto_galeria(orden=4)
        antes_archivos = set(Path(self.media_temporal.name).rglob("*.*"))
        datos = self.datos_habitacion(precio_noche="222000.00", numero="CAMBIO")
        datos.update({f"orden_foto_{foto.pk}": "0", "imagen": self.imagen("nueva.png"),
                      "fotografias": [self.imagen("buena.png"), self.imagen("prohibida.gif", "GIF")]})
        respuesta = self.staff.post(reverse("editar_habitacion", args=[self.habitacion.pk]), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        self.habitacion.refresh_from_db()
        foto.refresh_from_db()
        self.assertEqual((self.habitacion.numero, self.habitacion.precio_noche, foto.orden), ("101", Decimal("100000.00"), 4))
        self.assertEqual(self.habitacion.fotografias.count(), 1)
        self.assertEqual(set(Path(self.media_temporal.name).rglob("*.*")), antes_archivos)

    def test_edicion_galeria_reordena_selecciona_principal_y_agrega_varias(self):
        foto = self.foto_galeria(orden=2)
        datos = self.datos_habitacion()
        datos.update({f"orden_foto_{foto.pk}": "5", "foto_principal": str(foto.pk),
                      "fotografias": [self.imagen("extra1.png"), self.imagen("extra2.jpg", "JPEG")]})
        respuesta = self.staff.post(reverse("editar_habitacion", args=[self.habitacion.pk]), datos)
        self.assertEqual(respuesta.status_code, 302)
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.imagen.name, foto.imagen.name)
        self.assertEqual(list(self.habitacion.fotografias.values_list("orden", flat=True)), [5, 6, 7])

    def test_edicion_no_admite_principal_ni_orden_de_foto_ajena(self):
        ajena = self.foto_galeria(habitacion=self.habitacion_individual)
        for cambios in ({"foto_principal": str(ajena.pk)}, {f"orden_foto_{ajena.pk}": "0"}):
            with self.subTest(cambios=cambios):
                respuesta = self.staff.post(reverse("editar_habitacion", args=[self.habitacion.pk]), self.datos_habitacion(precio_noche="1.00", **cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["error"])
                self.habitacion.refresh_from_db()
                self.assertEqual(self.habitacion.precio_noche, Decimal("100000.00"))
                self.assertFalse(self.habitacion.imagen)

    def test_eliminar_foto_no_borra_archivo_compartido_con_principal(self):
        foto = self.foto_galeria()
        self.habitacion.imagen = foto.imagen.name
        self.habitacion.save()
        nombre = foto.imagen.name
        archivo = Path(foto.imagen.path)
        self.assertEqual(self.staff.post(reverse("eliminar_fotografia_habitacion", args=[foto.pk])).status_code, 302)
        self.habitacion.refresh_from_db()
        self.assertFalse(FotografiaHabitacion.objects.filter(pk=foto.pk).exists())
        self.assertEqual(self.habitacion.imagen.name, nombre)
        self.assertTrue(archivo.is_file())

    def test_admin_alta_tipo_respeta_total_independiente_y_cero_ninos(self):
        for nombre, capacidad, adultos, ninos in (("Independiente alta", "3", "3", "2"), ("Cero niños alta", "2", "2", "0")):
            with self.subTest(nombre=nombre):
                respuesta = self.staff.post(reverse("registrar_tipo"), {
                    "nombre": nombre, "capacidad": capacidad, "max_adultos": adultos, "max_ninos": ninos,
                })
                self.assertEqual(respuesta.status_code, 302)
                tipo = TipoHabitacion.objects.get(nombre=nombre)
                self.assertEqual((tipo.capacidad, tipo.max_adultos, tipo.max_ninos), (int(capacidad), int(adultos), int(ninos)))

    def test_admin_tipo_rechaza_minimos_y_maximos_sin_guardar(self):
        for capacidad, adultos, ninos in (("0", "1", "0"), ("2", "0", "0"), ("2", "3", "0"), ("2", "1", "2"), ("2", "1", "-1")):
            with self.subTest(capacidad=capacidad, adultos=adultos, ninos=ninos):
                antes = TipoHabitacion.objects.count()
                respuesta = self.staff.post(reverse("registrar_tipo"), {
                    "nombre": "Alta inválida", "capacidad": capacidad, "max_adultos": adultos, "max_ninos": ninos,
                })
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["form"].errors)
                self.assertEqual(TipoHabitacion.objects.count(), antes)

    def test_admin_tipo_dato_malformado_renderiza_error_no_500(self):
        for campo in ("capacidad", "max_adultos", "max_ninos"):
            with self.subTest(campo=campo):
                datos = {"nombre": "Malformado alta", "capacidad": "3", "max_adultos": "2", "max_ninos": "1"}
                datos[campo] = "texto"
                antes = TipoHabitacion.objects.count()
                respuesta = self.staff.post(reverse("registrar_tipo"), datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn(campo, respuesta.context["form"].errors)
                self.assertEqual(TipoHabitacion.objects.count(), antes)

    def test_admin_edicion_conserva_cero_ninos(self):
        respuesta = self.staff.post(reverse("editar_tipo", args=[self.sin_ninos.pk]), {
            "nombre": "Adultos actualizado", "capacidad": "3", "max_adultos": "3", "max_ninos": "0",
        })
        self.assertEqual(respuesta.status_code, 302)
        self.sin_ninos.refresh_from_db()
        self.assertEqual((self.sin_ninos.capacidad, self.sin_ninos.max_adultos, self.sin_ninos.max_ninos), (3, 3, 0))

    def test_reducir_tipo_no_invalida_reserva_vigente(self):
        self.nueva_reserva()
        respuesta = self.staff.post(reverse("editar_tipo", args=[self.doble.pk]), {
            "nombre": "Reducción rechazada", "capacidad": "2", "max_adultos": "1", "max_ninos": "1",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        self.doble.refresh_from_db()
        self.assertEqual((self.doble.nombre, self.doble.capacidad, self.doble.max_adultos), ("Doble", 3, 2))

    def test_cambiar_habitacion_a_tipo_menor_no_invalida_reserva_vigente(self):
        self.nueva_reserva()
        respuesta = self.staff.post(reverse("editar_habitacion", args=[self.habitacion.pk]), self.datos_habitacion(tipo=str(self.individual.pk), precio_noche="1.00"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["error"])
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.tipo_id, self.doble.pk)
        self.assertEqual(self.habitacion.precio_noche, Decimal("100000.00"))

    def test_admin_tarifa_rechaza_nan_negativos_precision_y_exceso(self):
        for precio in ("NaN", "Infinity", "-1.00", "1.001", "10000000000.00"):
            with self.subTest(precio=precio):
                respuesta = self.staff.post(reverse("registrar_habitacion"), self.datos_habitacion(numero="INVALIDA", precio_noche=precio))
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn("precio_noche", respuesta.context["form"].errors)
                self.assertFalse(Habitacion.objects.filter(numero="INVALIDA").exists())

    def test_cliente_no_puede_administrar_fotos_o_capacidad(self):
        foto = self.foto_galeria()
        for ruta, args, datos in (
            ("eliminar_fotografia_habitacion", [foto.pk], {}),
            ("editar_tipo", [self.doble.pk], {"capacidad": "1", "max_adultos": "1", "max_ninos": "0"}),
            ("editar_habitacion", [self.habitacion.pk], self.datos_habitacion(precio_noche="1.00")),
        ):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.guest.post(reverse(ruta, args=args), datos).status_code, 302)
        self.assertTrue(FotografiaHabitacion.objects.filter(pk=foto.pk).exists())
        self.doble.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(self.doble.capacidad, 3)
        self.assertEqual(self.habitacion.precio_noche, Decimal("100000.00"))


class RenderizadoPaginasTests(AuditoriaBase):
    def test_abono_publico_conserva_centavos_sin_localizar(self):
        self.habitacion.precio_noche = Decimal("100000.25")
        self.habitacion.save()
        respuesta = self.guest.get(reverse("posada_ver_habitacion", args=[self.habitacion.pk]), {
            "fecha_inicio": self.entrada.isoformat(), "fecha_fin": self.salida.isoformat(),
            "adultos": "2", "ninos": "1",
        })
        self.assertContains(respuesta, 'min="100000.25" max="300000.75"')
        self.assertContains(respuesta, 'step="0.01" value="100000.25"')

    def test_pago_staff_conserva_saldo_exacto_sin_localizar(self):
        reserva = self.nueva_reserva(tarifa_noche=Decimal("100000.25"))
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.25"))
        respuesta = self.staff.get(reverse("ver_reserva", args=[reserva.pk]))
        self.assertContains(respuesta, 'max="200000.50" name="monto"')
        self.assertContains(respuesta, 'value="200000.50"')
        self.assertContains(respuesta, 'step="0.01" min="0.01"')

    def test_paginas_publicas_renderizan_templates_publico(self):
        for ruta, args, plantilla in (
            ("posada_wayra", [], "publico/portal.html"),
            ("posada_habitaciones", [], "publico/habitaciones.html"),
            ("posada_ver_habitacion", [self.habitacion.pk], "publico/habitacion_detalle.html"),
            ("ver_alojamiento", [self.alojamiento.pk], "publico/alojamiento_detalle.html"),
            ("login", [], "publico/login.html"), ("cliente_login", [], "publico/login.html"),
            ("registro_cliente", [], "publico/registro.html"),
        ):
            with self.subTest(ruta=ruta):
                respuesta = self.client.get(reverse(ruta, args=args))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTemplateUsed(respuesta, plantilla)
                self.assertIs(respuesta.context["es_publico"], True)

    def test_paginas_cliente_renderizan_bajo_publico_sin_templates_legacy(self):
        reserva = self.nueva_reserva()
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        ServicioReserva.objects.create(reserva=reserva, servicio=self.servicio)
        self.foto_galeria()
        for ruta, args, plantilla in (
            ("cliente_habitaciones", [], "publico/habitaciones.html"),
            ("cliente_ver_habitacion", [self.habitacion.pk], "publico/habitacion_detalle.html"),
            ("cliente_mis_reservas", [], "publico/cliente/mis_reservas.html"),
            ("cliente_ver_reserva", [reserva.pk], "publico/cliente/ver_reserva.html"),
            ("perfil", [], "publico/perfil.html"),
        ):
            with self.subTest(ruta=ruta):
                respuesta = self.guest.get(reverse(ruta, args=args))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTemplateUsed(respuesta, plantilla)
                self.assertIs(respuesta.context["es_publico"], True)
                self.assertFalse(any(template.name and template.name.startswith("cliente/") for template in respuesta.templates))

    def test_paginas_staff_listados_detalles_formularios_y_reportes_renderizan(self):
        reserva = self.nueva_reserva()
        Pago.objects.create(reserva=reserva, monto=Decimal("100000.00"))
        ServicioReserva.objects.create(reserva=reserva, servicio=self.servicio)
        self.foto_galeria()
        rutas = (
            ("home", []), ("perfil", []), ("listar_roles", []), ("registrar_rol", []),
            ("editar_rol", [self.rol_recepcion.pk]), ("matriz_permisos", []),
            ("listar_usuarios", []), ("registrar_usuario", []), ("editar_usuario", [self.otro_usuario.pk]),
            ("listar_alojamientos", []), ("ver_alojamiento", [self.alojamiento.pk]),
            ("listar_tipos", []), ("registrar_tipo", []), ("editar_tipo", [self.doble.pk]),
            ("listar_habitaciones", []), ("registrar_habitacion", []), ("editar_habitacion", [self.habitacion.pk]),
            ("configuracion_hotel", []), ("rutina_dia", []),
            ("listar_huespedes", []), ("registrar_huesped", []), ("editar_huesped", [self.huesped.pk]),
            ("listar_servicios", []), ("registrar_servicio", []), ("editar_servicio", [self.servicio.pk]),
            ("listar_reservas", []), ("registrar_reserva", []), ("editar_reserva", [reserva.pk]),
            ("ver_reserva", [reserva.pk]), ("disponibilidad", []), ("pagos", []),
            ("dashboard", []), ("reportes_index", []), ("reporte_reservas", []), ("reporte_ocupacion", []),
            ("reporte_ingresos", []), ("reporte_huespedes", []), ("reporte_habitaciones", []), ("reporte_servicios", []),
            ("listar_sitios", []), ("registrar_sitio", []), ("editar_sitio", [self.sitio.pk]),
        )
        for ruta, args in rutas:
            with self.subTest(ruta=ruta):
                respuesta = self.staff.get(reverse(ruta, args=args))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.templates)

    def test_catalogo_publico_marca_sin_capacidad_y_disponibles_sin_ocultar_total(self):
        respuesta = self.client.get(reverse("posada_habitaciones"), {
            "fecha_inicio": self.entrada.isoformat(), "fecha_fin": self.salida.isoformat(),
            "adultos": "2", "ninos": "1",
        })
        self.assertEqual(respuesta.status_code, 200)
        habitaciones = list(respuesta.context["habitaciones"])
        self.assertEqual(respuesta.context["total_disponibles"], 2)
        self.assertEqual(respuesta.context["total_no_disponibles"], 2)
        self.assertEqual({habitacion.pk for habitacion in habitaciones[:2]}, {self.habitacion.pk, self.habitacion_independiente.pk})
        for habitacion in habitaciones:
            self.assertEqual(habitacion.sin_capacidad, habitacion.pk in {self.habitacion_individual.pk, self.habitacion_sin_ninos.pk})

    def test_detalle_publico_incluye_galeria_y_disponibilidad_real(self):
        foto = self.foto_galeria()
        self.nueva_reserva()
        respuesta = self.client.get(reverse("posada_ver_habitacion", args=[self.habitacion.pk]), {
            "fecha_inicio": self.entrada.isoformat(), "fecha_fin": self.salida.isoformat(),
            "adultos": "2", "ninos": "1",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertIs(respuesta.context["disponible"], False)
        self.assertEqual(list(respuesta.context["habitacion"].fotografias.values_list("pk", flat=True)), [foto.pk])
        self.assertContains(respuesta, foto.imagen.url)
        self.assertEqual(respuesta.context["total_estimado"], Decimal("300000.00"))
