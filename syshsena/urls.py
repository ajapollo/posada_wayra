# ==============================================================================
# PROYECTO: SysHSENA / Posada Wayra
# ARCHIVO: syshsena/urls.py
# DESCRIPCIÓN: Enrutamiento completo de URLs alineado a las vistas corregidas.
# ==============================================================================

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from syshsena import view
from syshsena.view import (
    login_view, cliente_login_view, logout_view, home, perfil, matriz_permisos, configuracion_hotel,
    listar_roles, registrar_rol, editar_rol, eliminar_rol,
    listar_usuarios, registrar_usuario, editar_usuario, eliminar_usuario,
    listar_alojamientos, ver_alojamiento,
    listar_tipos, registrar_tipo, editar_tipo, eliminar_tipo,
    listar_habitaciones, registrar_habitacion, editar_habitacion, eliminar_habitacion,
    eliminar_fotografia_habitacion,
    cambiar_estado_habitacion,
    listar_huespedes, registrar_huesped, editar_huesped, eliminar_huesped,
    listar_servicios, registrar_servicio, editar_servicio, eliminar_servicio,
    listar_reservas, ver_reserva, registrar_reserva, editar_reserva,
    cancelar_reserva, disponibilidad, confirmar_reserva,
    checkin_reserva, checkout_reserva, rutina_dia,
    agregar_servicio_reserva, eliminar_servicio_reserva,
    registrar_pago, eliminar_pago, pagos,
    dashboard, reportes_index,
    reporte_reservas, reporte_ocupacion, reporte_ingresos, reporte_huespedes,
    reporte_habitaciones, reporte_servicios,
    posada_wayra, posada_habitaciones, posada_ver_habitacion,
    registro_cliente, cliente_habitaciones, cliente_ver_habitacion, cliente_reservar,
    cliente_mis_reservas, cliente_ver_reserva, cliente_solicitar_cancelacion,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # Autenticación
    path("login/", login_view, name="login"),
    path("cliente/login/", cliente_login_view, name="cliente_login"),
    path("logout/", logout_view, name="logout"),
    path("registro/", registro_cliente, name="registro_cliente"),
    path("perfil/", perfil, name="perfil"),
    path("", home, name="home"),

    # Portal público
    path("posada_wayra/", posada_wayra, name="posada_wayra"),
    path("posada_wayra/habitaciones/", posada_habitaciones, name="posada_habitaciones"),
    path("posada_wayra/habitaciones/<int:idh>/", posada_ver_habitacion, name="posada_ver_habitacion"),

    # Portal del Cliente (Vistas del huésped autenticado)
    path("cliente/habitaciones/", cliente_habitaciones, name="cliente_habitaciones"),
    path("cliente/habitaciones/<int:idh>/", cliente_ver_habitacion, name="cliente_ver_habitacion"),
    path("cliente/reservar/", cliente_reservar, name="cliente_reservar"),
    path("cliente/mis-reservas/", cliente_mis_reservas, name="cliente_mis_reservas"),
    path("cliente/reservas/<int:idre>/", cliente_ver_reserva, name="cliente_ver_reserva"),
    path("cliente/reservas/<int:idre>/cancelar/", cliente_solicitar_cancelacion, name="cliente_solicitar_cancelacion"),

    # Módulo de Roles
    path("roles/", listar_roles, name="listar_roles"),
    path("roles/registrar/", registrar_rol, name="registrar_rol"),
    path("roles/editar/<int:idr>/", editar_rol, name="editar_rol"),
    path("roles/eliminar/<int:idr>/", eliminar_rol, name="eliminar_rol"),
    path("roles/permisos/", matriz_permisos, name="matriz_permisos"),

    # Módulo de Usuarios
    path("usuarios/", listar_usuarios, name="listar_usuarios"),
    path("usuarios/registrar/", registrar_usuario, name="registrar_usuario"),
    path("usuarios/editar/<int:idu>/", editar_usuario, name="editar_usuario"),
    path("usuarios/eliminar/<int:idu>/", eliminar_usuario, name="eliminar_usuario"),

    # Módulo de Alojamientos
    path("alojamientos/", listar_alojamientos, name="listar_alojamientos"),
    path("alojamientos/ver/<int:ida>/", ver_alojamiento, name="ver_alojamiento"),

    # Módulo de Sitios Turísticos ("Vive La Guajira")
    path("sitios/", view.listar_sitios, name="listar_sitios"),
    path("sitios/registrar/", view.registrar_sitio, name="registrar_sitio"),
    path("sitios/<int:sitio_id>/editar/", view.editar_sitio, name="editar_sitio"),
    path("sitios/<int:sitio_id>/eliminar/", view.eliminar_sitio, name="eliminar_sitio"),
    path("sitios/fotografia/<int:foto_id>/eliminar/", view.eliminar_fotografia_sitio, name="eliminar_fotografia_sitio"),

    # Módulo de Tipos de Habitación
    path("tipos/", listar_tipos, name="listar_tipos"),
    path("tipos/registrar/", registrar_tipo, name="registrar_tipo"),
    path("tipos/editar/<int:idt>/", editar_tipo, name="editar_tipo"),
    path("tipos/eliminar/<int:idt>/", eliminar_tipo, name="eliminar_tipo"),

    # Módulo de Habitaciones
    path("gestion/habitaciones/", listar_habitaciones, name="listar_habitaciones"),
    path("habitaciones/registrar/", registrar_habitacion, name="registrar_habitacion"),
    path("habitaciones/editar/<int:idh>/", editar_habitacion, name="editar_habitacion"),
    path("habitaciones/eliminar/<int:idh>/", eliminar_habitacion, name="eliminar_habitacion"),
    path("habitaciones/fotografias/<int:foto_id>/eliminar/", eliminar_fotografia_habitacion, name="eliminar_fotografia_habitacion"),
    path("habitaciones/<int:idh>/estado/", cambiar_estado_habitacion, name="cambiar_estado_habitacion"),

    # Configuración institucional y rutina diaria
    path("configuracion/", configuracion_hotel, name="configuracion_hotel"),
    path("rutina/", rutina_dia, name="rutina_dia"),

    # Módulo de Huéspedes
    path("huespedes/", listar_huespedes, name="listar_huespedes"),
    path("huespedes/registrar/", registrar_huesped, name="registrar_huesped"),
    path("huespedes/editar/<int:idh>/", editar_huesped, name="editar_huesped"),
    path("huespedes/eliminar/<int:idh>/", eliminar_huesped, name="eliminar_huesped"),

    # Módulo de Servicios Adicionales
    path("servicios/", listar_servicios, name="listar_servicios"),
    path("servicios/registrar/", registrar_servicio, name="registrar_servicio"),
    path("servicios/editar/<int:ids>/", editar_servicio, name="editar_servicio"),
    path("servicios/eliminar/<int:ids>/", eliminar_servicio, name="eliminar_servicio"),

    # Módulo de Gestión Administrativa de Reservas (Recepcionista / Admin)
    path("reservas/", listar_reservas, name="listar_reservas"),
    path("reservas/disponibilidad/", disponibilidad, name="disponibilidad"),
    path("reservas/registrar/", registrar_reserva, name="registrar_reserva"),
    path("reservas/ver/<int:idre>/", ver_reserva, name="ver_reserva"),
    path("reservas/editar/<int:idre>/", editar_reserva, name="editar_reserva"),
    path("reservas/cancelar/<int:idre>/", cancelar_reserva, name="cancelar_reserva"),
    path("reservas/confirmar/<int:idre>/", confirmar_reserva, name="confirmar_reserva"),

    # Operación Hotelera
    path("reservas/<int:idre>/checkin/", checkin_reserva, name="checkin_reserva"),
    path("reservas/<int:idre>/checkout/", checkout_reserva, name="checkout_reserva"),
    path("reservas/<int:idre>/servicios/agregar/", agregar_servicio_reserva, name="agregar_servicio_reserva"),
    path("reservas/servicios/eliminar/<int:idsr>/", eliminar_servicio_reserva, name="eliminar_servicio_reserva"),
    path("reservas/<int:idre>/pagos/registrar/", registrar_pago, name="registrar_pago"),
    path("reservas/pagos/eliminar/<int:idp>/", eliminar_pago, name="eliminar_pago"),

    # Módulo de Pagos
    path("pagos/", pagos, name="pagos"),

    # Dashboard e Indicadores Gerenciales
    path("dashboard/", dashboard, name="dashboard"),
    path("reportes/", reportes_index, name="reportes_index"),
    path("reportes/reservas/", reporte_reservas, name="reporte_reservas"),
    path("reportes/ocupacion/", reporte_ocupacion, name="reporte_ocupacion"),
    path("reportes/ingresos/", reporte_ingresos, name="reporte_ingresos"),
    path("reportes/huespedes/", reporte_huespedes, name="reporte_huespedes"),
    path("reportes/habitaciones/", reporte_habitaciones, name="reporte_habitaciones"),
    path("reportes/servicios/", reporte_servicios, name="reporte_servicios"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)