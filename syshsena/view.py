# ==============================================================================
# PROYECTO: SysHSENA / Posada Wayra
# ARCHIVO: syshsena/view.py
# DESCRIPCIÓN: Vistas principales del sistema refactorizadas.
# ==============================================================================

import calendar

from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.cache import never_cache
from datetime import datetime, timedelta, date
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Avg, Count, DecimalField, F, Max, Q, Sum
from django.db.models.functions import ExtractDay, TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.exceptions import PermissionDenied, ValidationError
from .forms import ImporteForm, OcupacionForm, validar_imagen

from .models import (
    Alojamiento,
    ConfiguracionHotel,
    FotografiaSitio,
    Habitacion,
    Huesped,
    Pago,
    Reserva,
    Rol,
    Servicio,
    ServicioReserva,
    SitioTuristico,
    TipoHabitacion,
    Usuario,
)

ESTADOS_ACTIVOS = [Reserva.PENDIENTE, Reserva.CONFIRMADA, Reserva.EN_ESTADIA]

MOMENTOS_SERVICIO = ["Desayuno", "Almuerzo", "Cena", "Almuerzo o Cena", "General"]


# ==============================================================================
# REGION 1: AUTENTICACIÓN Y ROLES DE ACCESO
# ==============================================================================

def login_view(request):
    error = None
    if request.user.is_authenticated:
        return redirect(_inicio_segun_rol(request.user))
    destino = _next_valido(request)
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        usuario = authenticate(request, username=username, password=password)
        if usuario is not None and (
            usuario.is_superuser
            or (usuario.rol_id and usuario.rol.nombre in ROLES_STAFF)
        ):
            login(request, usuario)
            return redirect(destino or "home")
        error = (
            "Este acceso está reservado para Recepción, Administración y Gerencia."
            if usuario is not None
            else "Usuario o contraseña incorrectos."
        )
    return render(request, "publico/login.html", {
        "error": error,
        "next": destino or "",
        "client_mode": False,
        "es_publico": True,
    })


def cliente_login_view(request):
    destino = _next_valido(request)
    if request.user.is_authenticated:
        return redirect((destino or "cliente_mis_reservas") if _es_cliente(request.user) else "home")

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        usuario = authenticate(request, username=username, password=password)
        if usuario is not None and _es_cliente(usuario):
            login(request, usuario)
            return redirect(destino or "cliente_mis_reservas")
        error = (
            "Las cuentas del personal deben ingresar desde el acceso de Recepción."
            if usuario is not None
            else "Usuario o contraseña incorrectos."
        )

    return render(request, "publico/login.html", {
        "error": error,
        "next": destino or "",
        "client_mode": True,
        "es_publico": True,
    })


@require_POST
def logout_view(request):
    era_cliente = _es_cliente(request.user)
    logout(request)
    return redirect("posada_wayra" if era_cliente else "login")


def _es_administrador(user):
    if user.is_superuser:
        return True
    return bool(user.rol_id and user.rol.nombre == Rol.ADMINISTRADOR)


def _es_admin_o_gerente(user):
    if user.is_superuser:
        return True
    return bool(user.rol_id and user.rol.nombre in (Rol.ADMINISTRADOR, Rol.GERENTE))


def _nombre_rol(user):
    if user.is_authenticated and user.rol_id:
        return user.rol.nombre
    return None


def _tiene_rol(user, roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _nombre_rol(user) in roles


def _inicio_segun_rol(user):
    if _nombre_rol(user) == Rol.CLIENTE:
        return "posada_wayra"  # Apunta directamente al portal público/cliente
    return "home"


def role_required(*roles):
    """Restringe una vista a los roles indicados (RN10)."""
    def decorador(view):
        @wraps(view)
        def _vista(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.info(request, "Inicia sesión para continuar.")
                return redirect(f"{settings.LOGIN_URL}?next={request.path}")
            if _tiene_rol(request.user, roles):
                return view(request, *args, **kwargs)
            messages.error(request, "No tienes permisos para acceder a este módulo.")
            return redirect(_inicio_segun_rol(request.user))
        return _vista
    return decorador


# Permisos por rol definidos en la especificación (RN10).
ROLES_ADMIN = (Rol.ADMINISTRADOR,)
ROLES_OPERACION = (Rol.ADMINISTRADOR, Rol.RECEPCIONISTA)
ROLES_STAFF = (Rol.ADMINISTRADOR, Rol.RECEPCIONISTA, Rol.GERENTE)

solo_admin = role_required(*ROLES_ADMIN)
solo_admin_gerente = role_required(Rol.ADMINISTRADOR, Rol.GERENTE)
operacion = role_required(*ROLES_OPERACION)
lectura_staff = role_required(*ROLES_STAFF)


def home(request):
    if not request.user.is_authenticated or _es_cliente(request.user):
        return redirect("posada_wayra")
    alojamientos = Alojamiento.objects.prefetch_related(
        "fotografias", "sitios_turisticos"
    ).all()
    return render(request, "home.html", {"alojamientos": alojamientos})


def _formato_pesos(valor):
    return "$" + f"{Decimal(valor or 0):,.0f}".replace(",", ".")


# ==============================================================================
# REGION 2: ROLES
# ==============================================================================

@login_required
@solo_admin
def listar_roles(request):
    buscar = request.GET.get("buscar", "")
    roles_qs = Rol.objects.all()
    if buscar:
        roles_qs = roles_qs.filter(nombre__icontains=buscar)
    roles_qs = roles_qs.order_by("id")
    paginator = Paginator(roles_qs, 10)
    roles = paginator.get_page(request.GET.get("page"))
    return render(request, "roles/listar_roles.html", {"roles": roles, "buscar": buscar})


@login_required
@solo_admin
def registrar_rol(request):
    error = None
    if request.method == "POST":
        rol = Rol(nombre=request.POST.get("nombre", "").strip())
        try:
            rol.full_clean()
            with transaction.atomic():
                rol.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "Ya existe un rol con ese nombre."
        else:
            return redirect("listar_roles")
    return render(request, "roles/registrar_rol.html", {"error": error, "opciones": Rol.NOMBRE_CHOICES})


@login_required
@solo_admin
def editar_rol(request, idr):
    rol = get_object_or_404(Rol, id=idr)
    error = None
    if request.method == "POST":
        nombre = request.POST.get("nombre", "").strip()
        try:
            with transaction.atomic():
                rol = get_object_or_404(Rol.objects.select_for_update(), id=idr)
                if nombre != rol.nombre and Usuario.objects.filter(rol=rol).exists():
                    raise ValidationError("No se puede cambiar el nombre de un rol asignado: cambiaría los permisos de sus usuarios.")
                rol.nombre = nombre
                rol.full_clean()
                rol.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "Ya existe un rol con ese nombre."
        else:
            return redirect("listar_roles")
    return render(request, "roles/editar_rol.html", {"rol": rol, "error": error, "opciones": Rol.NOMBRE_CHOICES})


@login_required
@solo_admin
@require_POST
def eliminar_rol(request, idr):
    rol = get_object_or_404(Rol, id=idr)
    try:
        with transaction.atomic():
            rol.delete()
    except ProtectedError:
        messages.error(request, "No se puede eliminar un rol asignado a usuarios.")
    else:
        messages.success(request, "Rol eliminado correctamente.")
    return redirect("listar_roles")


# ==============================================================================
# REGION 3: USUARIOS
# ==============================================================================

@login_required
@solo_admin
def listar_usuarios(request):
    buscar = request.GET.get("buscar", "")
    usuarios_qs = Usuario.objects.filter(is_active=True)
    if buscar:
        usuarios_qs = usuarios_qs.filter(
            Q(username__icontains=buscar)
            | Q(first_name__icontains=buscar)
            | Q(last_name__icontains=buscar)
            | Q(email__icontains=buscar)
        )
    usuarios_qs = usuarios_qs.order_by("id")
    paginator = Paginator(usuarios_qs, 10)
    usuarios = paginator.get_page(request.GET.get("page"))
    return render(request, "usuarios/listar_usuarios.html", {"usuarios": usuarios, "buscar": buscar})


def _rol_usuario_formulario(valor):
    if not valor:
        return None
    try:
        rol = Rol.objects.select_for_update().get(pk=int(valor))
    except (ValueError, TypeError, OverflowError, Rol.DoesNotExist):
        raise ValidationError({"rol": "Selecciona un rol válido."})
    if rol.nombre not in dict(Rol.NOMBRE_CHOICES):
        raise ValidationError({"rol": "El rol seleccionado no tiene permisos reconocidos."})
    return rol


def _administradores_activos_bloqueados():
    return list(Usuario.objects.select_for_update().filter(is_active=True).filter(
        Q(is_superuser=True) | Q(rol__nombre=Rol.ADMINISTRADOR)
    ).order_by("pk"))


@login_required
@solo_admin
def registrar_usuario(request):
    error = None
    if request.method == "POST":
        usuario = Usuario(
            username=Usuario.normalize_username(request.POST.get("username", "").strip()),
            first_name=request.POST.get("first_name", "").strip(),
            last_name=request.POST.get("last_name", "").strip(),
            email=request.POST.get("email", "").strip(),
        )
        password = request.POST.get("password", "")
        try:
            if not password:
                raise ValidationError("El usuario y la contraseña son obligatorios.")
            if usuario.email:
                validate_email(usuario.email)
            validate_password(password, user=usuario)
            usuario.set_password(password)
            with transaction.atomic():
                usuario.rol = _rol_usuario_formulario(request.POST.get("rol", "").strip())
                usuario.full_clean()
                usuario.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo registrar: el usuario o sus datos asociados ya existen."
        else:
            messages.success(request, "Usuario registrado correctamente.")
            return redirect("listar_usuarios")
    return render(request, "usuarios/registrar_usuario.html", {"error": error, "roles": Rol.objects.all()})


@login_required
@solo_admin
def editar_usuario(request, idu):
    usuario = get_object_or_404(Usuario, id=idu)
    error = None
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            with transaction.atomic():
                administradores = _administradores_activos_bloqueados()
                usuario = get_object_or_404(Usuario.objects.select_for_update(), id=idu)
                era_admin = usuario.is_active and _es_administrador(usuario)
                usuario.first_name = request.POST.get("first_name", "").strip()
                usuario.last_name = request.POST.get("last_name", "").strip()
                usuario.email = request.POST.get("email", "").strip()
                usuario.rol = _rol_usuario_formulario(request.POST.get("rol", "").strip())
                if era_admin and not _es_administrador(usuario) and len(administradores) <= 1:
                    raise ValidationError("No se puede quitar el acceso al último administrador activo.")
                if usuario.email:
                    validate_email(usuario.email)
                if password:
                    validate_password(password, user=usuario)
                    usuario.set_password(password)
                usuario.full_clean()
                usuario.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo actualizar: revisa los datos de usuario y el rol asignado."
        else:
            if password and usuario.pk == request.user.pk:
                update_session_auth_hash(request, usuario)
            messages.success(request, "Usuario actualizado correctamente.")
            return redirect("listar_usuarios")
    return render(request, "usuarios/editar_usuario.html", {"usuario": usuario, "error": error, "roles": Rol.objects.all()})


@login_required
@solo_admin
@require_POST
def eliminar_usuario(request, idu):
    if request.user.pk == idu:
        messages.error(request, "No puedes desactivar tu propia cuenta.")
        return redirect("listar_usuarios")
    with transaction.atomic():
        administradores = _administradores_activos_bloqueados()
        usuario = get_object_or_404(Usuario.objects.select_for_update(), id=idu)
        if usuario.is_active and _es_administrador(usuario) and len(administradores) <= 1:
            messages.error(request, "No se puede desactivar al último superusuario o administrador activo.")
        else:
            usuario.is_active = False
            usuario.save(update_fields=["is_active"])
            messages.success(request, "Usuario desactivado correctamente.")
    return redirect("listar_usuarios")


@login_required
def perfil(request):
    """Valida los datos y archivos antes de guardar el perfil y sus credenciales."""
    usuario = request.user
    huesped = usuario.huesped_perfil if _es_cliente(usuario) else None
    error = None

    if request.method == "POST":
        accion = request.POST.get("accion", "datos")
        try:
            if accion == "avatar":
                archivo = request.FILES.get("avatar")
                if not archivo:
                    raise ValidationError("Selecciona una imagen para actualizar tu foto de perfil.")
                usuario.avatar = validar_imagen(archivo)
                usuario.full_clean()
                with transaction.atomic():
                    usuario.save(update_fields=["avatar"])
                messages.success(request, "Fotografía de perfil actualizada correctamente.")
            elif accion == "quitar_avatar":
                usuario.avatar = None
                with transaction.atomic():
                    usuario.save(update_fields=["avatar"])
                messages.success(request, "Fotografía de perfil eliminada.")
            elif accion == "password":
                actual = request.POST.get("password_actual", "")
                nueva = request.POST.get("password_nueva", "")
                confirmar = request.POST.get("password_confirmar", "")
                if not usuario.check_password(actual):
                    raise ValidationError("La contraseña actual no es correcta.")
                if nueva != confirmar:
                    raise ValidationError("Las contraseñas nuevas no coinciden.")
                validate_password(nueva, user=usuario)
                usuario.set_password(nueva)
                usuario.full_clean()
                with transaction.atomic():
                    usuario.save(update_fields=["password"])
                update_session_auth_hash(request, usuario)
                messages.success(request, "Contraseña actualizada correctamente.")
            elif accion == "datos":
                usuario.first_name = request.POST.get("first_name", "").strip()
                usuario.last_name = request.POST.get("last_name", "").strip()
                usuario.email = request.POST.get("email", "").strip()
                if usuario.email:
                    validate_email(usuario.email)
                usuario.full_clean()
                if huesped:
                    huesped.nombre = usuario.first_name
                    huesped.apellido = usuario.last_name
                    huesped.email = usuario.email or None
                    huesped.telefono = request.POST.get("telefono", "").strip() or None
                    huesped.direccion = request.POST.get("direccion", "").strip() or None
                    huesped.nacionalidad = request.POST.get("nacionalidad", huesped.nacionalidad).strip() or huesped.nacionalidad
                    huesped.ciudad_residencia = request.POST.get("ciudad_residencia", huesped.ciudad_residencia).strip() or huesped.ciudad_residencia
                    huesped.pais_residencia = request.POST.get("pais_residencia", huesped.pais_residencia).strip() or huesped.pais_residencia
                    huesped.full_clean()
                with transaction.atomic():
                    usuario.save(update_fields=["first_name", "last_name", "email"])
                    if huesped:
                        huesped.save()
                messages.success(request, "Datos de perfil actualizados correctamente.")
            else:
                raise ValidationError("Selecciona una acción de perfil válida.")
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo actualizar el perfil: revisa los datos duplicados o asociados."
        else:
            return redirect("perfil")

    return render(request, "publico/perfil.html", {
        "perfil_usuario": usuario,
        "huesped": huesped,
        "error": error,
        "es_publico": _es_cliente(usuario),
    })


PERMISOS_POR_MODULO = [
    ("Usuarios y roles", "Crear, editar, desactivar cuentas y asignar roles.", {Rol.ADMINISTRADOR}),
    ("Configurar alojamiento", "Datos del establecimiento, fotografías y sitios turísticos.", {Rol.ADMINISTRADOR}),
    ("Administrar habitaciones y tipos", "Crear, editar y eliminar habitaciones, tipos y tarifas.", {Rol.ADMINISTRADOR}),
    ("Consultar inventario", "Ver habitaciones, tipos, tarifas y estados.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA, Rol.GERENTE}),
    ("Administrar servicios", "Crear, editar y eliminar servicios y tarifas.", {Rol.ADMINISTRADOR}),
    ("Servicios en reservas", "Asociar o quitar consumos adicionales en una reserva.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA}),
    ("Huéspedes", "Registrar y actualizar datos de huéspedes.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA}),
    ("Registrar y modificar reservas", "Crear, editar, confirmar y cancelar reservas.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA}),
    ("Consultar reservas y disponibilidad", "Ver reservas, estados y calendario de ocupación.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA, Rol.GERENTE}),
    ("Check-in / Check-out", "Registrar llegadas y salidas y actualizar habitaciones.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA}),
    ("Registrar pagos y abonos", "Aplicar pagos y abonos a las reservas.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA}),
    ("Consultar pagos y saldos", "Ver recaudos, saldos pendientes e historial.", {Rol.ADMINISTRADOR, Rol.RECEPCIONISTA, Rol.GERENTE}),
    ("Dashboard e indicadores", "Consultar KPIs y estadísticas generales.", {Rol.ADMINISTRADOR, Rol.GERENTE}),
    ("Reportes", "Reservas, ocupación, ingresos, habitaciones, huéspedes y servicios.", {Rol.ADMINISTRADOR, Rol.GERENTE}),
    ("Portal del cliente", "Reservar, consultar sus reservas y solicitar cancelación.", {Rol.CLIENTE}),
    ("Perfil propio", "Actualizar datos personales y contraseña.", {Rol.ADMINISTRADOR, Rol.GERENTE, Rol.RECEPCIONISTA, Rol.CLIENTE}),
]


@login_required
@solo_admin
def matriz_permisos(request):
    filas = []
    for modulo, detalle, roles in PERMISOS_POR_MODULO:
        filas.append({
            "modulo": modulo,
            "detalle": detalle,
            "administrador": Rol.ADMINISTRADOR in roles,
            "recepcionista": Rol.RECEPCIONISTA in roles,
            "gerente": Rol.GERENTE in roles,
            "cliente": Rol.CLIENTE in roles,
        })
    return render(request, "roles/permisos.html", {
        "filas": filas,
        "roles": Rol.NOMBRE_CHOICES,
    })


# ==============================================================================
# REGION 3B: CONFIGURACIÓN INSTITUCIONAL (ADMINISTRADOR / GERENTE)
# ==============================================================================

@login_required
@solo_admin_gerente
def configuracion_hotel(request):
    configuracion = ConfiguracionHotel.cargar()
    error = None

    if request.method == "POST":
        configuracion.nombre = request.POST.get("nombre", "").strip()
        configuracion.nit = request.POST.get("nit", "").strip() or None
        configuracion.direccion = request.POST.get("direccion", "").strip()
        configuracion.ciudad = request.POST.get("ciudad", "Riohacha").strip() or "Riohacha"
        configuracion.departamento = request.POST.get("departamento", "La Guajira").strip() or "La Guajira"
        configuracion.pais = request.POST.get("pais", "Colombia").strip() or "Colombia"
        configuracion.telefono = request.POST.get("telefono", "").strip()
        configuracion.whatsapp = request.POST.get("whatsapp", "").strip()
        configuracion.email = request.POST.get("email", "").strip()
        configuracion.politicas = request.POST.get("politicas", "").strip()
        configuracion.horario_checkin = request.POST.get("horario_checkin", "3:00 p.m.").strip() or "3:00 p.m."
        configuracion.horario_checkout = request.POST.get("horario_checkout", "11:00 a.m.").strip() or "11:00 a.m."
        try:
            if not all((configuracion.nombre, configuracion.direccion, configuracion.telefono,
                        configuracion.whatsapp, configuracion.email, configuracion.politicas)):
                raise ValidationError("Completa el nombre, la dirección, los teléfonos, el correo y las políticas.")
            validate_email(configuracion.email)
            try:
                edad_max_nino = int(request.POST.get("edad_max_nino", "").strip())
            except (ValueError, TypeError, OverflowError):
                raise ValidationError("La edad máxima de niño debe ser un número entero entre 0 y 17.")
            if not 0 <= edad_max_nino <= 17:
                raise ValidationError("La edad máxima de niño debe estar entre 0 y 17.")
            configuracion.edad_max_nino = edad_max_nino
            for campo in ("logo", "banner"):
                archivo = request.FILES.get(campo)
                if archivo:
                    setattr(configuracion, campo, validar_imagen(archivo))
                elif request.POST.get(f"quitar_{campo}") == "1":
                    setattr(configuracion, campo, None)
            configuracion.full_clean()
            with transaction.atomic():
                configuracion.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo guardar la configuración; vuelve a intentarlo."
        else:
            messages.success(request, "Configuración del establecimiento actualizada. Los cambios ya se reflejan en toda la plataforma.")
            return redirect("configuracion_hotel")

    return render(request, "configuracion/index.html", {
        "configuracion": configuracion,
        "error": error,
        "edad_min_adulto": configuracion.edad_max_nino + 1,
    })


# ==============================================================================
# REGION 4: ALOJAMIENTOS
# ==============================================================================

@login_required
@lectura_staff
def listar_alojamientos(request):
    sitios = SitioTuristico.objects.prefetch_related("fotografias").all().order_by("orden", "nombre")
    return render(request, "alojamientos/listar_alojamientos.html", {"sitios": sitios})


def ver_alojamiento(request, ida):
    """Ficha pública del establecimiento con fotos, servicios y sitios cercanos."""
    alojamiento = get_object_or_404(
        Alojamiento.objects.prefetch_related(
            "fotografias", "sitios_turisticos", "servicios", "habitaciones__tipo"
        ),
        id=ida,
    )
    return render(request, "publico/alojamiento_detalle.html", {
        **_contexto_publico(),
        "alojamiento": alojamiento,
        "habitaciones": alojamiento.habitaciones.select_related("tipo").exclude(
            estado=Habitacion.MANTENIMIENTO
        ).order_by("numero"),
    })


# ==============================================================================
# REGION 5: TIPOS DE HABITACIÓN
# ==============================================================================

@login_required
@lectura_staff
def listar_tipos(request):
    buscar = request.GET.get("buscar", "")
    tipos_qs = TipoHabitacion.objects.all()
    if buscar:
        tipos_qs = tipos_qs.filter(Q(nombre__icontains=buscar))
    tipos_qs = tipos_qs.order_by("id")
    paginator = Paginator(tipos_qs, 10)
    tipos = paginator.get_page(request.GET.get("page"))
    return render(request, "tipos/listar_tipos.html", {"tipos": tipos, "buscar": buscar})


@login_required
@solo_admin
def registrar_tipo(request):
    from django.forms import modelform_factory
    from django.db import IntegrityError, transaction

    FormularioTipo = modelform_factory(
        TipoHabitacion,
        fields=("nombre", "capacidad", "max_adultos", "max_ninos", "descripcion"),
    )
    form = FormularioTipo(request.POST if request.method == "POST" else None)
    error = None
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                tipo = form.save(commit=False)
                tipo.full_clean()
                tipo.save()
            messages.success(request, "Tipo de habitación registrado.")
            return redirect("listar_tipos")
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo registrar el tipo. Revisa los datos e inténtalo nuevamente."
    return render(request, "tipos/registrar_tipo.html", {"form": form, "error": error})


@login_required
@solo_admin
def editar_tipo(request, idt):
    from django.forms import modelform_factory
    from django.db import IntegrityError, transaction

    tipo = get_object_or_404(TipoHabitacion, id=idt)
    FormularioTipo = modelform_factory(
        TipoHabitacion,
        fields=("nombre", "capacidad", "max_adultos", "max_ninos", "descripcion"),
    )
    form = FormularioTipo(request.POST if request.method == "POST" else None, instance=tipo)
    error = None
    if request.method == "POST":
        try:
            with transaction.atomic():
                tipo_bloqueado = get_object_or_404(TipoHabitacion.objects.select_for_update(), id=idt)
                # Se bloquea primero el tipo y después sus habitaciones, en orden estable.
                habitaciones_ids = list(Habitacion.objects.select_for_update().filter(
                    tipo=tipo_bloqueado
                ).order_by("pk").values_list("pk", flat=True))
                form = FormularioTipo(request.POST, instance=tipo_bloqueado)
                if form.is_valid():
                    candidato = form.save(commit=False)
                    candidato.full_clean()
                    reservas = Reserva.objects.select_for_update().filter(
                        habitacion_id__in=habitaciones_ids,
                        estado__in=ESTADOS_ACTIVOS,
                    ).filter(Q(fecha_fin__gte=date.today()) | Q(estado=Reserva.EN_ESTADIA))
                    for reserva in reservas:
                        adultos = getattr(reserva, "num_adultos", None)
                        ninos = getattr(reserva, "num_ninos", None)
                        total = max(reserva.num_personas or 0, (adultos or 0) + (ninos or 0))
                        if (total > candidato.capacidad
                                or (adultos is not None and adultos > candidato.max_adultos)
                                or (ninos is not None and ninos > candidato.max_ninos)):
                            raise ValidationError(
                                f"La capacidad propuesta no admite la reserva vigente #{reserva.pk}. "
                                "No se guardó ningún cambio."
                            )
                    candidato.save()
                    messages.success(request, "Tipo actualizado para todas sus habitaciones.")
                    return redirect("listar_tipos")
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo actualizar el tipo. Revisa los datos e inténtalo nuevamente."
    return render(request, "tipos/editar_tipo.html", {"tipo": tipo, "form": form, "error": error})


@login_required
@solo_admin
@require_POST
def eliminar_tipo(request, idt):
    from django.db import IntegrityError, transaction
    from django.db.models.deletion import ProtectedError

    try:
        with transaction.atomic():
            tipo = get_object_or_404(TipoHabitacion.objects.select_for_update(), id=idt)
            tipo.delete()
        messages.success(request, "Tipo eliminado.")
    except ProtectedError:
        messages.error(request, "No puedes eliminar un tipo con habitaciones asociadas. Cambia primero su tipo.")
    except IntegrityError:
        messages.error(request, "El tipo está en uso y no puede eliminarse.")
    return redirect("listar_tipos")


# ==============================================================================
# REGION 6: HABITACIONES
# ==============================================================================

@login_required
@lectura_staff
def listar_habitaciones(request):
    buscar = request.GET.get("buscar", "")
    habitaciones_qs = Habitacion.objects.select_related("tipo", "alojamiento")
    if buscar:
        habitaciones_qs = habitaciones_qs.filter(
            Q(numero__icontains=buscar)
            | Q(tipo__nombre__icontains=buscar)
            | Q(alojamiento__nombre__icontains=buscar)
        )
    habitaciones_qs = habitaciones_qs.order_by("id")
    paginator = Paginator(habitaciones_qs, 10)
    habitaciones = paginator.get_page(request.GET.get("page"))
    return render(request, "habitaciones/listar_habitaciones.html", {"habitaciones": habitaciones, "buscar": buscar})


@login_required
@solo_admin
def registrar_habitacion(request):
    from django import forms
    from django.db import IntegrityError, transaction
    from .forms import validar_imagen
    from .models import FotografiaHabitacion

    estados = [(valor, etiqueta) for valor, etiqueta in Habitacion.ESTADO_CHOICES
               if valor in (Habitacion.DISPONIBLE, Habitacion.LIMPIEZA, Habitacion.MANTENIMIENTO)]
    FormularioHabitacion = forms.modelform_factory(
        Habitacion, fields=("numero", "tipo", "alojamiento", "precio_noche", "piso", "estado")
    )
    datos = request.POST.copy() if request.method == "POST" else None
    if datos is not None:
        datos.setdefault("precio_noche", datos.get("precio", ""))
        datos.setdefault("estado", Habitacion.DISPONIBLE)
        datos.setdefault("piso", "1")
    form = FormularioHabitacion(datos)
    form.fields["estado"].choices = estados
    form.fields["precio_noche"] = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), label="Tarifa por noche"
    )
    error = None
    if request.method == "POST":
        try:
            # Se comprueban todos los archivos, incluso si otros campos son inválidos.
            principal = validar_imagen(request.FILES["imagen"]) if request.FILES.get("imagen") else None
            imagenes = [validar_imagen(archivo) for archivo in request.FILES.getlist("fotografias")]
            if form.is_valid():
                with transaction.atomic():
                    tipo = TipoHabitacion.objects.select_for_update().filter(
                        pk=form.cleaned_data["tipo"].pk
                    ).first()
                    alojamiento = Alojamiento.objects.select_for_update().filter(
                        pk=form.cleaned_data["alojamiento"].pk
                    ).first()
                    if tipo is None or alojamiento is None:
                        raise ValidationError("El tipo o alojamiento ya no existe. Actualiza el formulario.")
                    habitacion = form.save(commit=False)
                    habitacion.tipo = tipo
                    habitacion.alojamiento = alojamiento
                    if principal is not None:
                        habitacion.imagen = principal
                    habitacion.full_clean()
                    fotografias = [FotografiaHabitacion(imagen=imagen, orden=orden)
                                   for orden, imagen in enumerate(imagenes)]
                    for foto in fotografias:
                        foto.full_clean(exclude=["habitacion"])
                    habitacion.save()
                    for foto in fotografias:
                        foto.habitacion = habitacion
                        foto.save()
                messages.success(request, "Habitación y fotografías registradas.")
                return redirect("listar_habitaciones")
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo registrar la habitación. Revisa sus datos y relaciones."
    return render(request, "habitaciones/registrar_habitacion.html", {
        "form": form,
        "error": error,
        "tipos": TipoHabitacion.objects.all(),
        "alojamientos": Alojamiento.objects.all(),
        "estados": estados,
    })


@login_required
@solo_admin
def editar_habitacion(request, idh):
    from django import forms
    from django.db import IntegrityError, transaction
    from .forms import validar_imagen
    from .models import FotografiaHabitacion

    habitacion = get_object_or_404(Habitacion.objects.select_related("tipo", "alojamiento"), id=idh)
    tipo_original_id = habitacion.tipo_id
    estados = [(valor, etiqueta) for valor, etiqueta in Habitacion.ESTADO_CHOICES
               if valor in (Habitacion.DISPONIBLE, Habitacion.LIMPIEZA, Habitacion.MANTENIMIENTO)]
    FormularioHabitacion = forms.modelform_factory(
        Habitacion, fields=("numero", "tipo", "alojamiento", "precio_noche", "piso", "estado")
    )
    datos = request.POST.copy() if request.method == "POST" else None
    if datos is not None:
        datos.setdefault("precio_noche", datos.get("precio", ""))
        datos.setdefault("estado", habitacion.estado)
        datos.setdefault("piso", str(habitacion.piso))

    def construir_formulario(instancia, en_estadia):
        formulario = FormularioHabitacion(datos, instance=instancia)
        formulario.fields["precio_noche"] = forms.DecimalField(
            max_digits=12, decimal_places=2, min_value=Decimal("0"), label="Tarifa por noche"
        )
        formulario.fields["estado"].choices = Habitacion.ESTADO_CHOICES if en_estadia else estados
        formulario.fields["estado"].disabled = en_estadia
        return formulario

    estado_bloqueado = habitacion.reservas.filter(estado=Reserva.EN_ESTADIA).exists()
    form = construir_formulario(habitacion, estado_bloqueado)
    error = None
    if request.method == "POST":
        try:
            principal = validar_imagen(request.FILES["imagen"]) if request.FILES.get("imagen") else None
            imagenes = [validar_imagen(archivo) for archivo in request.FILES.getlist("fotografias")]
            quitar_imagen = forms.BooleanField(required=False).clean(request.POST.get("quitar_imagen"))
            foto_principal_id = forms.IntegerField(required=False, min_value=1).clean(
                request.POST.get("foto_principal")
            )
            if sum((principal is not None, quitar_imagen, foto_principal_id is not None)) > 1:
                raise ValidationError("Elige solo una acción: cargar principal, usar una foto de galería o quitar la principal.")
            if form.is_valid():
                with transaction.atomic():
                    # El orden tipo -> habitación coincide con editar_tipo.
                    tipos_bloqueados = {tipo.pk: tipo for tipo in TipoHabitacion.objects.select_for_update().filter(
                        pk__in=(tipo_original_id, form.cleaned_data["tipo"].pk)
                    ).order_by("pk")}
                    bloqueada = get_object_or_404(Habitacion.objects.select_for_update(), id=idh)
                    if bloqueada.tipo_id not in tipos_bloqueados:
                        raise ValidationError("Otra operación cambió el tipo. Actualiza el formulario y vuelve a intentar.")
                    tipo = tipos_bloqueados.get(form.cleaned_data["tipo"].pk)
                    alojamiento = Alojamiento.objects.select_for_update().filter(
                        pk=form.cleaned_data["alojamiento"].pk
                    ).first()
                    if tipo is None or alojamiento is None:
                        raise ValidationError("El tipo o alojamiento ya no existe. Actualiza el formulario.")
                    reservas = list(Reserva.objects.select_for_update().filter(
                        habitacion=bloqueada, estado__in=ESTADOS_ACTIVOS
                    ).filter(Q(fecha_fin__gte=date.today()) | Q(estado=Reserva.EN_ESTADIA)))
                    en_estadia = any(reserva.estado == Reserva.EN_ESTADIA for reserva in reservas)
                    estado_anterior = bloqueada.estado
                    tipo_anterior_id = bloqueada.tipo_id
                    alojamiento_anterior_id = bloqueada.alojamiento_id
                    if en_estadia and request.POST.get("estado", estado_anterior) != estado_anterior:
                        raise ValidationError("La habitación tiene una estadía activa. Su estado se gestiona desde check-in/check-out.")
                    form = construir_formulario(bloqueada, en_estadia)
                    if not form.is_valid():
                        raise ValidationError("Revisa los campos indicados. No se guardó ningún cambio.")
                    candidata = form.save(commit=False)
                    candidata.tipo = tipo
                    candidata.alojamiento = alojamiento
                    if en_estadia and (candidata.tipo_id != tipo_anterior_id
                                       or candidata.alojamiento_id != alojamiento_anterior_id):
                        raise ValidationError("No puedes cambiar el tipo o alojamiento durante una estadía activa.")
                    for reserva in reservas:
                        adultos = getattr(reserva, "num_adultos", None)
                        ninos = getattr(reserva, "num_ninos", None)
                        total = max(reserva.num_personas or 0, (adultos or 0) + (ninos or 0))
                        if (total > tipo.capacidad
                                or (adultos is not None and adultos > tipo.max_adultos)
                                or (ninos is not None and ninos > tipo.max_ninos)):
                            raise ValidationError(f"El tipo elegido no admite la reserva vigente #{reserva.pk}.")
                    fotografias = list(FotografiaHabitacion.objects.select_for_update().filter(habitacion=bloqueada))
                    fotos_por_id = {foto.pk: foto for foto in fotografias}
                    campos_orden = {f"orden_foto_{foto.pk}" for foto in fotografias}
                    if any(clave.startswith("orden_foto_") and clave not in campos_orden for clave in request.POST):
                        raise ValidationError("Una fotografía ya no existe o no pertenece a esta habitación.")
                    for foto in fotografias:
                        foto.orden = forms.IntegerField(min_value=0).clean(
                            request.POST.get(f"orden_foto_{foto.pk}", foto.orden)
                        )
                        foto.full_clean()
                    if foto_principal_id is not None:
                        if foto_principal_id not in fotos_por_id:
                            raise ValidationError("La fotografía principal elegida no pertenece a esta habitación.")
                        candidata.imagen = fotos_por_id[foto_principal_id].imagen.name
                    elif principal is not None:
                        candidata.imagen = principal
                    elif quitar_imagen:
                        candidata.imagen = ""
                    candidata.full_clean()
                    siguiente_orden = max((foto.orden for foto in fotografias), default=-1) + 1
                    nuevas = [FotografiaHabitacion(habitacion=candidata, imagen=imagen, orden=siguiente_orden + indice)
                              for indice, imagen in enumerate(imagenes)]
                    for foto in nuevas:
                        foto.full_clean()
                    # Ninguna escritura ocurre antes de validar habitación, órdenes y todos los archivos.
                    candidata.save()
                    for foto in fotografias:
                        foto.save(update_fields=["orden"])
                    for foto in nuevas:
                        foto.save()
                messages.success(request, "Habitación y galería actualizadas. Los cambios de tarifa aplican a futuras reservas.")
                return redirect("listar_habitaciones")
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo guardar la habitación. Revisa los datos y vuelve a intentar."
        habitacion = get_object_or_404(Habitacion.objects.select_related("tipo", "alojamiento"), id=idh)
        estado_bloqueado = habitacion.reservas.filter(estado=Reserva.EN_ESTADIA).exists()
    fotografias = list(habitacion.fotografias.all())
    for foto in fotografias:
        foto.orden_formulario = request.POST.get(f"orden_foto_{foto.pk}", foto.orden) if request.method == "POST" else foto.orden
    return render(request, "habitaciones/editar_habitacion.html", {
        "habitacion": habitacion,
        "form": form,
        "error": error,
        "tipos": TipoHabitacion.objects.all(),
        "alojamientos": Alojamiento.objects.all(),
        "estados": estados,
        "estado_bloqueado": estado_bloqueado,
        "fotografias": fotografias,
        "quitar_imagen": request.POST.get("quitar_imagen", ""),
        "foto_principal": request.POST.get("foto_principal", ""),
    })


@login_required
@solo_admin
@require_POST
def eliminar_habitacion(request, idh):
    from django.db import IntegrityError, transaction
    from django.db.models.deletion import ProtectedError

    habitacion = get_object_or_404(Habitacion, id=idh)
    tipo_id = habitacion.tipo_id
    try:
        with transaction.atomic():
            get_object_or_404(TipoHabitacion.objects.select_for_update(), pk=tipo_id)
            habitacion = get_object_or_404(Habitacion.objects.select_for_update(), id=idh)
            if habitacion.tipo_id != tipo_id:
                raise ValidationError("Otra operación cambió esta habitación. Actualiza el listado.")
            habitacion.delete()
        messages.success(request, "Habitación eliminada.")
    except ProtectedError:
        messages.error(request, "No puedes eliminar una habitación con reservas asociadas. Conserva su historial.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    except IntegrityError:
        messages.error(request, "La habitación está en uso y no puede eliminarse.")
    return redirect("listar_habitaciones")


@login_required
@solo_admin
@require_POST
def eliminar_fotografia_habitacion(request, foto_id):
    from django.db import IntegrityError, transaction
    from django.db.models.deletion import ProtectedError
    from .models import FotografiaHabitacion

    foto = get_object_or_404(FotografiaHabitacion, pk=foto_id)
    habitacion_id = foto.habitacion_id
    try:
        with transaction.atomic():
            get_object_or_404(Habitacion.objects.select_for_update(), pk=habitacion_id)
            foto = get_object_or_404(FotografiaHabitacion.objects.select_for_update(), pk=foto_id,
                                     habitacion_id=habitacion_id)
            # Solo se borra el registro: la principal u otros registros pueden compartir el archivo.
            foto.delete()
        messages.success(request, "Fotografía retirada de la galería. La imagen principal no se modifica.")
    except ProtectedError:
        messages.error(request, "Esta fotografía está en uso y no puede retirarse.")
    except IntegrityError:
        messages.error(request, "No se pudo retirar la fotografía. Actualiza la página e inténtalo nuevamente.")
    return redirect("editar_habitacion", idh=habitacion_id)


# ==============================================================================
# REGION 7: HUÉSPEDES
# ==============================================================================

@login_required
@lectura_staff
def listar_huespedes(request):
    buscar = request.GET.get("buscar", "")
    huespedes_qs = Huesped.objects.annotate(num_reservas=Count("reservas"))
    if buscar:
        huespedes_qs = huespedes_qs.filter(
            Q(numero_documento__icontains=buscar)
            | Q(nombre__icontains=buscar)
            | Q(apellido__icontains=buscar)
            | Q(email__icontains=buscar)
        )
    huespedes_qs = huespedes_qs.order_by("apellido", "nombre")
    paginator = Paginator(huespedes_qs, 10)
    huespedes = paginator.get_page(request.GET.get("page"))
    return render(request, "huespedes/listar_huespedes.html", {"huespedes": huespedes, "buscar": buscar})


def _datos_huesped_formulario(request, huesped):
    huesped.tipo_documento = request.POST.get("tipo_documento", huesped.tipo_documento).strip()
    huesped.numero_documento = request.POST.get("numero_documento", "").strip()
    huesped.nombre = request.POST.get("nombre", request.POST.get("nombres", "")).strip()
    huesped.apellido = request.POST.get("apellido", request.POST.get("apellidos", "")).strip()
    huesped.telefono = request.POST.get("telefono", "").strip() or None
    huesped.email = request.POST.get("correo", request.POST.get("email", "")).strip() or None
    huesped.direccion = request.POST.get("direccion", "").strip() or None
    for campo in ("nacionalidad", "ciudad_residencia", "pais_residencia"):
        setattr(huesped, campo, request.POST.get(campo, getattr(huesped, campo)).strip() or getattr(huesped, campo))
    huesped.es_extranjero = request.POST.get("es_extranjero") in ("on", "true", "1", "si", "sí")


@login_required
@operacion
def registrar_huesped(request):
    error = None
    errores = {}
    huesped = Huesped()
    if request.method == "POST":
        _datos_huesped_formulario(request, huesped)
        try:
            huesped.full_clean()
            with transaction.atomic():
                huesped.save()
        except ValidationError as exc:
            errores = getattr(exc, "message_dict", {"__all__": exc.messages})
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "Ya existe un huésped con ese número de documento."
            errores = {"numero_documento": [error]}
        else:
            messages.success(request, "Huésped registrado correctamente.")
            return redirect("listar_huespedes")
    return render(request, "huespedes/registrar_huesped.html", {
        "huesped": huesped, "error": error, "errores": errores, "tipos": Huesped.TIPO_DOC_CHOICES,
    })


@login_required
@operacion
def editar_huesped(request, idh):
    huesped = get_object_or_404(Huesped, id=idh)
    error = None
    errores = {}
    if request.method == "POST":
        _datos_huesped_formulario(request, huesped)
        try:
            huesped.full_clean()
            with transaction.atomic():
                huesped.save()
        except ValidationError as exc:
            errores = getattr(exc, "message_dict", {"__all__": exc.messages})
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "Ya existe un huésped con ese número de documento."
            errores = {"numero_documento": [error]}
        else:
            messages.success(request, "Huésped actualizado correctamente.")
            return redirect("listar_huespedes")
    return render(request, "huespedes/editar_huesped.html", {
        "huesped": huesped, "error": error, "errores": errores, "tipos": Huesped.TIPO_DOC_CHOICES,
    })


@login_required
@solo_admin
@require_POST
def eliminar_huesped(request, idh):
    huesped = get_object_or_404(Huesped, id=idh)
    try:
        with transaction.atomic():
            huesped = get_object_or_404(Huesped.objects.select_for_update(), id=idh)
            if huesped.reservas.exists():
                raise ProtectedError("El huésped tiene reservas.", [huesped])
            huesped.delete()
    except ProtectedError:
        messages.error(request, "No se puede eliminar un huésped con reservas; se conserva su historial.")
    else:
        messages.success(request, "Huésped eliminado correctamente.")
    return redirect("listar_huespedes")


# ==============================================================================
# REGION 8: SERVICIOS ADICIONALES
# ==============================================================================

@login_required
@lectura_staff
def listar_servicios(request):
    buscar = request.GET.get("buscar", "")
    servicios_qs = Servicio.objects.select_related("alojamiento").all()
    if buscar:
        servicios_qs = servicios_qs.filter(
            Q(nombre__icontains=buscar) | Q(descripcion__icontains=buscar)
        )
    servicios_qs = servicios_qs.order_by("id")
    paginator = Paginator(servicios_qs, 10)
    servicios = paginator.get_page(request.GET.get("page"))
    return render(request, "servicios/listar_servicios.html", {"servicios": servicios, "buscar": buscar})


def _precio_servicio(valor):
    try:
        precio = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return precio if precio.is_finite() else None


def _datos_servicio_formulario(request, servicio):
    servicio.nombre = request.POST.get("nombre", "").strip()
    servicio.descripcion = request.POST.get("descripcion", "").strip()
    servicio.momento_dia = request.POST.get("momento_dia", "General").strip() or "General"
    servicio.imagen_url = request.POST.get("imagen_url", "").strip() or None
    precio = _precio_servicio(request.POST.get("precio", ""))
    if precio is None:
        raise ValidationError({"precio": "Introduce un precio decimal válido y finito."})
    if precio < 0:
        raise ValidationError({"precio": "El precio del servicio no puede ser negativo; cero es válido."})
    servicio.precio = precio
    if servicio.momento_dia not in MOMENTOS_SERVICIO:
        raise ValidationError({"momento_dia": "Selecciona un momento del día válido."})
    try:
        servicio.alojamiento_id = int(request.POST.get("alojamiento", "").strip())
    except (ValueError, TypeError, OverflowError):
        raise ValidationError({"alojamiento": "Selecciona un alojamiento válido."})
    archivo = request.FILES.get("imagen_archivo")
    if archivo:
        servicio.imagen = validar_imagen(archivo)
    elif request.POST.get("quitar_imagen") == "1":
        servicio.imagen = None
    servicio.full_clean()


@login_required
@solo_admin
def registrar_servicio(request):
    error = None
    servicio = Servicio()
    if request.method == "POST":
        try:
            _datos_servicio_formulario(request, servicio)
            with transaction.atomic():
                servicio.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo registrar el servicio: verifica el alojamiento seleccionado."
        else:
            messages.success(request, "Servicio registrado correctamente.")
            return redirect("listar_servicios")
    return render(request, "servicios/registrar_servicio.html", {
        "servicio": servicio,
        "error": error,
        "alojamientos": Alojamiento.objects.all(),
        "momentos": MOMENTOS_SERVICIO,
    })


@login_required
@solo_admin
def editar_servicio(request, ids):
    servicio = get_object_or_404(Servicio, id=ids)
    error = None
    if request.method == "POST":
        try:
            _datos_servicio_formulario(request, servicio)
            with transaction.atomic():
                servicio.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo actualizar el servicio: verifica el alojamiento seleccionado."
        else:
            messages.success(request, "Servicio actualizado correctamente.")
            return redirect("listar_servicios")
    return render(request, "servicios/editar_servicio.html", {
        "servicio": servicio,
        "error": error,
        "alojamientos": Alojamiento.objects.all(),
        "momentos": MOMENTOS_SERVICIO,
    })


@login_required
@solo_admin
@require_POST
def eliminar_servicio(request, ids):
    servicio = get_object_or_404(Servicio, id=ids)
    try:
        with transaction.atomic():
            servicio.delete()
    except ProtectedError:
        messages.error(request, "No se puede eliminar un servicio utilizado en reservas; se conserva su historial.")
    else:
        messages.success(request, "Servicio eliminado correctamente.")
    return redirect("listar_servicios")


# ==============================================================================
# REGION 9: RESERVAS Y CONTROL DE OVERBOOKING
# ==============================================================================

def _next_valido(request):
    destino = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if destino.startswith("/") and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return None


def _parse_fecha(valor):
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _habitaciones_ocupadas(entrada, salida, excluir_reserva=None):
    hoy = date.today()
    ocupacion = Q(estado__in=ESTADOS_ACTIVOS, fecha_inicio__lt=salida, fecha_fin__gt=entrada)
    if entrada <= hoy:
        ocupacion |= Q(estado=Reserva.EN_ESTADIA, fecha_checkout__isnull=True,
                       fecha_fin__lte=hoy, fecha_inicio__lt=salida)
    reservas = Reserva.objects.filter(ocupacion)
    if excluir_reserva:
        reservas = reservas.exclude(id=excluir_reserva)
    return set(reservas.values_list("habitacion_id", flat=True))


def _validar_ocupacion(habitacion, adultos, ninos):
    if not habitacion.tipo.admite(adultos, ninos):
        return (f"La habitación {habitacion.numero} admite máximo {habitacion.capacidad} personas, "
                f"con hasta {habitacion.max_adultos} adultos y {habitacion.max_ninos} niños.")
    return None


def _ocupacion_solicitada(request):
    form = OcupacionForm(request.POST)
    if not form.is_valid():
        return None, None, "Indica al menos un adulto y una cantidad válida de niños."
    return form.cleaned_data["adultos"], form.cleaned_data["ninos"], None


def _habitacion_bloqueada(idh):
    tipo_id = get_object_or_404(Habitacion, pk=idh).tipo_id
    get_object_or_404(TipoHabitacion.objects.select_for_update(), pk=tipo_id)
    return get_object_or_404(Habitacion.objects.select_for_update(), pk=idh, tipo_id=tipo_id)


def _reserva_bloqueada(idre):
    habitacion_id = get_object_or_404(Reserva, pk=idre).habitacion_id
    _habitacion_bloqueada(habitacion_id)
    return get_object_or_404(Reserva.objects.select_for_update(), pk=idre, habitacion_id=habitacion_id)


def _validar_reserva(habitacion, entrada, salida, excluir_reserva=None, adultos=1, ninos=0):
    if not (habitacion and entrada and salida):
        return "Debes indicar habitación y fechas válidas."
    if salida <= entrada:
        return "La fecha de salida debe ser posterior a la fecha de llegada."
    if entrada < date.today() and excluir_reserva is None:
        return "La llegada no puede ser anterior a hoy."
    if habitacion.estado == Habitacion.MANTENIMIENTO:
        return "La habitación está en mantenimiento."
    if entrada <= date.today() and habitacion.estado == Habitacion.LIMPIEZA:
        return "La habitación aún está en limpieza."
    error = _validar_ocupacion(habitacion, adultos, ninos)
    if error:
        return error
    ocupadas = _habitaciones_ocupadas(entrada, salida, excluir_reserva=excluir_reserva)
    if habitacion.id in ocupadas:
        return f"La habitación {habitacion.numero} no está disponible en el rango de fechas seleccionado."
    return None


def _entero_positivo(valor, defecto=1):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return defecto
    return numero if numero > 0 else defecto


def _entero_no_negativo(valor, defecto=0):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return defecto
    return numero if numero >= 0 else defecto


# Elimina la repetición del bloque return al final de esta función:
def _parametros_busqueda(request):
    hoy = date.today()
    entrada = _parse_fecha(request.GET.get("fecha_inicio", "")) or hoy
    salida = _parse_fecha(request.GET.get("fecha_fin", "")) or (entrada + timedelta(days=1))

    if entrada < hoy:
        entrada = hoy
    if salida <= entrada:
        salida = entrada + timedelta(days=1)

    adultos = _entero_positivo(request.GET.get("adultos"), 1)
    ninos = _entero_no_negativo(request.GET.get("ninos"), 0)

    huespedes = adultos + ninos

    return {
        "entrada": entrada,
        "salida": salida,
        "adultos": adultos,
        "ninos": ninos,
        "huespedes": huespedes,
        "noches": max((salida - entrada).days, 1),
        "aplicado": bool(request.GET.get("fecha_inicio") or request.GET.get("fecha_fin")),
    }




def _habitaciones_publicas(entrada, salida, adultos, ninos):
    habitaciones = Habitacion.objects.select_related("tipo", "alojamiento").prefetch_related("fotografias").filter(
        tipo__max_adultos__gte=adultos, tipo__max_ninos__gte=ninos,
        tipo__capacidad__gte=adultos + ninos,
    ).exclude(estado=Habitacion.MANTENIMIENTO).exclude(
        id__in=_habitaciones_ocupadas(entrada, salida)
    )
    if entrada <= date.today():
        habitaciones = habitaciones.exclude(estado=Habitacion.LIMPIEZA)
    return habitaciones.order_by("precio_noche", "numero")


def _contexto_publico():
    limites = TipoHabitacion.objects.aggregate(adultos=Max("max_adultos"), ninos=Max("max_ninos"))
    return {"es_publico": True, "limites_busqueda": {
        "adultos": limites["adultos"] or 1, "ninos": limites["ninos"] or 0,
    }}


def _minimo_abono(habitacion, total_estimado):
    """Regla de negocio: garantía mínima equivalente a una noche."""
    total = Decimal(total_estimado or 0)
    precio = Decimal(habitacion.precio_noche or 0)
    if total <= 0:
        return Decimal("0")
    if precio <= 0:
        return total
    return min(precio, total)


def _fecha_se_desocupa(habitacion, desde):
    reservas = list(
        Reserva.objects.filter(
            habitacion=habitacion,
            estado__in=ESTADOS_ACTIVOS,
            fecha_fin__gt=desde,
        ).order_by("fecha_inicio")
    )
    if not reservas:
        return None
    libre = desde
    for r in reservas:
        if r.fecha_inicio <= libre:
            if r.fecha_fin > libre:
                libre = r.fecha_fin
        else:
            break
    return libre if libre > desde else None


@login_required
@lectura_staff
def listar_reservas(request):
    buscar = request.GET.get("buscar", "")
    estado = request.GET.get("estado", "")
    reservas_qs = Reserva.objects.select_related(
        "huesped", "habitacion", "habitacion__alojamiento"
    )
    if buscar:
        reservas_qs = reservas_qs.filter(
            Q(huesped__nombre__icontains=buscar)
            | Q(huesped__apellido__icontains=buscar)
            | Q(huesped__numero_documento__icontains=buscar)
            | Q(habitacion__numero__icontains=buscar)
        )
    if estado == "SOLICITUD_CANCELACION":
        reservas_qs = reservas_qs.filter(cancelacion_solicitada=True).exclude(estado=Reserva.CANCELADA)
    elif estado:
        reservas_qs = reservas_qs.filter(estado=estado)

    # Prioriza arriba las solicitudes de cancelación pendientes de aprobar
    reservas_qs = reservas_qs.order_by("-cancelacion_solicitada", "-fecha_creacion", "-id")
    solicitudes_cancelacion_count = Reserva.objects.filter(
        cancelacion_solicitada=True
    ).exclude(estado__in=(Reserva.CANCELADA, Reserva.FINALIZADA)).count()

    paginator = Paginator(reservas_qs, 10)
    reservas = paginator.get_page(request.GET.get("page"))
    return render(request, "reservas/listar_reservas.html", {
        "reservas": reservas,
        "buscar": buscar,
        "estado": estado,
        "estados": Reserva.ESTADO_CHOICES,
        "solicitudes_cancelacion_count": solicitudes_cancelacion_count,
    })


@login_required
@lectura_staff
def ver_reserva(request, idre):
    reserva = get_object_or_404(
        Reserva.objects.select_related("huesped", "habitacion", "habitacion__alojamiento"),
        id=idre,
    )
    servicios_reserva = reserva.servicios_consumidos.select_related("servicio").all()
    pagos = reserva.pagos.all().order_by("-fecha_pago")
    servicios = Servicio.objects.filter(
        alojamiento_id=reserva.habitacion.alojamiento_id
    ).order_by("nombre")
    
    return render(request, "reservas/ver_reserva.html", {
        "reserva": reserva,
        "servicios_reserva": servicios_reserva,
        "pagos": pagos,
        "servicios": servicios,
        "metodos": Pago.METODO_CHOICES,
    })


def _contexto_reserva(error=None, datos=None):
    return {
        "error": error, "datos_reserva": datos or {},
        "huespedes": Huesped.objects.all().order_by("apellido", "nombre"),
        "habitaciones": Habitacion.objects.select_related("tipo", "alojamiento").order_by("numero"),
        "estados": [(Reserva.PENDIENTE, "Pendiente de validación")],
    }


@login_required
@operacion
def registrar_reserva(request):
    error = None
    if request.method == "POST":
        adultos, ninos, error = _ocupacion_solicitada(request)
        idhabitacion = request.POST.get("habitacion", "")
        idhuesped = request.POST.get("huesped", "")
        entrada = _parse_fecha(request.POST.get("fecha_entrada", request.POST.get("fecha_inicio")))
        salida = _parse_fecha(request.POST.get("fecha_salida", request.POST.get("fecha_fin")))
        huesped = Huesped.objects.filter(pk=idhuesped).first() if idhuesped.isdecimal() else None
        if not huesped or not idhabitacion.isdecimal():
            error = "Selecciona un huésped y una habitación válidos."
        if request.POST.get("estado", Reserva.PENDIENTE) != Reserva.PENDIENTE:
            error = "La reserva debe crearse pendiente; confirma el abono antes del check-in."
        if error is None:
            try:
                with transaction.atomic():
                    habitacion = _habitacion_bloqueada(idhabitacion)
                    error = _validar_reserva(habitacion, entrada, salida, adultos=adultos, ninos=ninos)
                    if error:
                        raise ValidationError(error)
                    reserva = Reserva(huesped=huesped, habitacion=habitacion, num_personas=adultos + ninos,
                                      num_adultos=adultos, num_ninos=ninos, fecha_inicio=entrada, fecha_fin=salida,
                                      tarifa_noche=habitacion.precio_noche)
                    reserva.full_clean()
                    reserva.save()
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                messages.success(request, "Reserva registrada pendiente de validación.")
                return redirect("ver_reserva", idre=reserva.pk)
    return render(request, "reservas/registrar_reserva.html", _contexto_reserva(error, request.POST))


@login_required
@operacion
def editar_reserva(request, idre):
    reserva = get_object_or_404(Reserva, id=idre)
    error = None
    if reserva.estado in (Reserva.CANCELADA, Reserva.FINALIZADA):
        messages.warning(request, "No se puede modificar una reserva cancelada o finalizada.")
        return redirect("ver_reserva", idre=idre)
    datos = {
        "huesped": str(reserva.huesped_id), "habitacion": str(reserva.habitacion_id),
        "fecha_entrada": reserva.fecha_inicio.isoformat(), "fecha_salida": reserva.fecha_fin.isoformat(),
        "adultos": reserva.num_adultos, "ninos": reserva.num_ninos,
    }
    if request.method == "POST":
        datos = request.POST
        adultos, ninos, error = _ocupacion_solicitada(request)
        idhabitacion = request.POST.get("habitacion", "")
        idhuesped = request.POST.get("huesped", "")
        entrada = _parse_fecha(request.POST.get("fecha_entrada", request.POST.get("fecha_inicio")))
        salida = _parse_fecha(request.POST.get("fecha_salida", request.POST.get("fecha_fin")))
        huesped = Huesped.objects.filter(pk=idhuesped).first() if idhuesped.isdecimal() else None
        if not huesped or not idhabitacion.isdecimal():
            error = "Selecciona un huésped y una habitación válidos."
        if error is None:
            try:
                with transaction.atomic():
                    ids_habitaciones = [reserva.habitacion_id, int(idhabitacion)]
                    ids_tipos = list(Habitacion.objects.filter(pk__in=ids_habitaciones).values_list("tipo_id", flat=True))
                    list(TipoHabitacion.objects.select_for_update().filter(pk__in=ids_tipos).order_by("pk"))
                    habitaciones = {h.pk: h for h in Habitacion.objects.select_for_update().filter(
                        pk__in=ids_habitaciones, tipo_id__in=ids_tipos).order_by("pk")}
                    actual = get_object_or_404(Reserva.objects.select_for_update(), pk=idre)
                    habitacion = habitaciones.get(int(idhabitacion))
                    if actual.habitacion_id not in habitaciones:
                        raise ValidationError("Otra operación cambió la habitación. Actualiza esta página.")
                    if actual.estado not in ESTADOS_ACTIVOS:
                        raise ValidationError("La reserva ya no admite cambios.")
                    if request.POST.get("estado", actual.estado) != actual.estado:
                        raise ValidationError("Usa las acciones de confirmar, cancelar, check-in o check-out para cambiar el estado.")
                    if actual.estado == Reserva.EN_ESTADIA and (int(idhabitacion) != actual.habitacion_id or entrada != actual.fecha_inicio):
                        raise ValidationError("Durante la estadía no se pueden cambiar la habitación ni la llegada.")
                    error = _validar_reserva(habitacion, entrada, salida, excluir_reserva=idre, adultos=adultos, ninos=ninos)
                    if error:
                        raise ValidationError(error)
                    if habitacion.pk != actual.habitacion_id:
                        actual.tarifa_noche = habitacion.precio_noche
                    actual.habitacion = habitacion
                    actual.huesped = huesped
                    actual.fecha_inicio, actual.fecha_fin = entrada, salida
                    actual.num_adultos, actual.num_ninos = adultos, ninos
                    actual.num_personas = adultos + ninos
                    actual.full_clean()
                    if actual.total_pagado > actual.gran_total:
                        raise ValidationError("El nuevo total es menor que lo pagado. Gestiona primero el ajuste con recepción.")
                    actual.save()
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                messages.success(request, "Reserva actualizada; se conserva la tarifa acordada si no cambiaste de habitación.")
                return redirect("ver_reserva", idre=idre)
    contexto = _contexto_reserva(error, datos)
    contexto.update(reserva=reserva, estados=[(reserva.estado, reserva.get_estado_display())])
    return render(request, "reservas/editar_reserva.html", contexto)


@login_required
@operacion
@require_POST
def cancelar_reserva(request, idre):
    with transaction.atomic():
        reserva = _reserva_bloqueada(idre)
        if reserva.estado == Reserva.CANCELADA:
            messages.info(request, "La reserva ya estaba cancelada.")
        elif reserva.estado not in (Reserva.PENDIENTE, Reserva.CONFIRMADA):
            messages.warning(request, "Solo se pueden cancelar reservas pendientes o confirmadas.")
        else:
            reserva.estado = Reserva.CANCELADA
            reserva.cancelacion_solicitada = False
            reserva.save(update_fields=["estado", "cancelacion_solicitada"])
            messages.success(request, "Reserva cancelada correctamente.")
    return redirect(_next_valido(request) or "listar_reservas")


@login_required
@operacion
@require_POST
def confirmar_reserva(request, idre):
    with transaction.atomic():
        reserva = _reserva_bloqueada(idre)
        if reserva.estado == Reserva.CONFIRMADA:
            messages.info(request, f"La reserva #{reserva.id} ya se encuentra confirmada.")
        elif reserva.estado != Reserva.PENDIENTE:
            messages.warning(request, "Solo se pueden confirmar reservas pendientes.")
        else:
            habitacion = reserva.habitacion
            error = None
            if reserva.fecha_inicio < date.today():
                error = "No se puede confirmar una reserva cuya llegada ya pasó."
            else:
                try:
                    reserva.full_clean()
                except ValidationError as exc:
                    error = " ".join(exc.messages)
            if error is None:
                if reserva.num_adultos is not None:
                    error = _validar_reserva(
                        habitacion, reserva.fecha_inicio, reserva.fecha_fin,
                        excluir_reserva=reserva.id,
                        adultos=reserva.num_adultos, ninos=reserva.num_ninos,
                    )
                elif habitacion.estado == Habitacion.MANTENIMIENTO:
                    error = "La habitación está en mantenimiento."
                elif reserva.fecha_inicio == date.today() and habitacion.estado == Habitacion.LIMPIEZA:
                    error = "La habitación aún está en limpieza."
                elif habitacion.id in _habitaciones_ocupadas(
                    reserva.fecha_inicio, reserva.fecha_fin, excluir_reserva=reserva.id
                ):
                    error = "La habitación no está disponible en las fechas de la reserva."
            if error is None and (reserva.tarifa_noche is None or reserva.tarifa_noche < 0):
                error = "La reserva debe tener una tarifa por noche acordada válida."
            if error is None:
                minimo = min(reserva.tarifa_noche, reserva.gran_total)
                if reserva.total_pagado < minimo:
                    error = f"El abono mínimo para confirmar es {_formato_pesos(minimo)} COP."
            if error:
                messages.warning(request, error)
            else:
                reserva.estado = Reserva.CONFIRMADA
                reserva.cancelacion_solicitada = False
                reserva.save(update_fields=["estado", "cancelacion_solicitada"])
                messages.success(request, f"Reserva #{reserva.id} confirmada correctamente.")
    return redirect(_next_valido(request) or "listar_reservas")


@login_required
@lectura_staff
def rutina_dia(request):
    """Rutina operativa diaria para recepción, administración y gerencia."""
    hoy = date.today()
    base = Reserva.objects.select_related("huesped", "habitacion", "habitacion__tipo")

    llegadas = base.filter(
        estado__in=(Reserva.PENDIENTE, Reserva.CONFIRMADA),
        fecha_inicio=hoy,
    ).order_by("habitacion__numero", "huesped__apellido")

    # Incluye salidas de hoy y salidas vencidas de días anteriores que siguen EN_ESTADIA
    salidas = base.filter(
        estado=Reserva.EN_ESTADIA,
        fecha_fin__lte=hoy,
    ).order_by("fecha_fin", "habitacion__numero", "huesped__apellido")

    salidas_vencidas_count = base.filter(
        estado=Reserva.EN_ESTADIA,
        fecha_fin__lt=hoy,
    ).count()

    pagos_por_verificar = (
        base.filter(estado=Reserva.PENDIENTE)
        .prefetch_related("pagos", "servicios_consumidos")
        .order_by("fecha_creacion")
    )

    habitaciones_limpieza = Habitacion.objects.select_related("tipo").filter(
        estado=Habitacion.LIMPIEZA
    ).order_by("numero")
    habitaciones_mantenimiento = Habitacion.objects.select_related("tipo").filter(
        estado=Habitacion.MANTENIMIENTO
    ).order_by("numero")

    return render(request, "reservas/rutina_dia.html", {
        "hoy": hoy,
        "llegadas": llegadas,
        "salidas": salidas,
        "salidas_vencidas_count": salidas_vencidas_count,
        "pagos_por_verificar": pagos_por_verificar,
        "habitaciones_limpieza": habitaciones_limpieza,
        "habitaciones_mantenimiento": habitaciones_mantenimiento,
        "puede_operar": _tiene_rol(request.user, ROLES_OPERACION),
    })


@login_required
@lectura_staff
def disponibilidad(request):
    tab = request.GET.get("tab", "checkin").strip()
    if tab not in ("checkin", "checkout"):
        tab = "checkin"
    fecha_str = request.GET.get("fecha", "").strip()
    hoy = date.today()
    fecha_filtro = _parse_fecha(fecha_str) or hoy

    reservas_qs = Reserva.objects.select_related("huesped", "habitacion", "habitacion__tipo")
    if tab == "checkout":
        if fecha_filtro == hoy:
            reservas_qs = reservas_qs.filter(estado=Reserva.EN_ESTADIA, fecha_fin__lte=hoy)
        else:
            reservas_qs = reservas_qs.filter(estado=Reserva.EN_ESTADIA, fecha_fin=fecha_filtro)
    else:
        reservas_qs = reservas_qs.filter(
            estado__in=(Reserva.PENDIENTE, Reserva.CONFIRMADA),
            fecha_inicio=fecha_filtro,
        )
    reservas_qs = reservas_qs.order_by("fecha_fin" if tab == "checkout" else "fecha_inicio", "habitacion__numero")

    total_habitaciones = Habitacion.objects.count()
    habitaciones_ocupadas = Habitacion.objects.filter(estado=Habitacion.OCUPADA).count()
    habitaciones_disponibles = Habitacion.objects.filter(estado=Habitacion.DISPONIBLE).exclude(
        id__in=Reserva.objects.filter(estado=Reserva.EN_ESTADIA).values("habitacion_id")
    ).count()
    porcentaje_ocupacion = round(habitaciones_ocupadas * 100 / total_habitaciones, 1) if total_habitaciones > 0 else 0

    llegadas_pendientes = Reserva.objects.filter(
        estado__in=(Reserva.PENDIENTE, Reserva.CONFIRMADA),
        fecha_inicio=hoy,
    )
    salidas_pendientes = Reserva.objects.filter(estado=Reserva.EN_ESTADIA, fecha_fin__lte=hoy)

    return render(request, "reservas/checkin_checkout_panel.html", {
        "tab": tab,
        "fecha_filtro": fecha_filtro,
        "hoy_str": hoy.strftime("%Y-%m-%d"),
        "reservas_lista": reservas_qs,
        "checkin_hoy_count": llegadas_pendientes.count(),
        "checkout_hoy_count": salidas_pendientes.count(),
        "total_reservas_hoy": llegadas_pendientes.count() + salidas_pendientes.count(),
        "total_habitaciones": total_habitaciones,
        "total_habitaciones_ocupadas": habitaciones_ocupadas,
        "habitaciones_disponibles": habitaciones_disponibles,
        "porcentaje_ocupacion": porcentaje_ocupacion,
        "proximos_checkin": llegadas_pendientes.order_by("habitacion__numero")[:6],
        "proximos_checkout": salidas_pendientes.order_by("fecha_fin", "habitacion__numero")[:6],
    })


@login_required
@operacion
@require_POST
def cambiar_estado_habitacion(request, idh):
    with transaction.atomic():
        habitacion = get_object_or_404(Habitacion.objects.select_for_update(), id=idh)
        nuevo_estado = request.POST.get("estado", "").strip()
        permitidos = {Habitacion.DISPONIBLE, Habitacion.LIMPIEZA, Habitacion.MANTENIMIENTO}
        if nuevo_estado not in permitidos:
            messages.error(request, "El estado solicitado no es válido.")
        elif Reserva.objects.filter(habitacion=habitacion, estado=Reserva.EN_ESTADIA).exists():
            messages.warning(request, "La habitación tiene una estadía activa. Registra primero el check-out.")
        else:
            habitacion.estado = nuevo_estado
            habitacion.save(update_fields=["estado"])
            messages.success(
                request,
                f"Habitación {habitacion.numero} actualizada a «{habitacion.get_estado_display()}».",
            )
    return redirect(_next_valido(request) or "rutina_dia")


# ==============================================================================
# REGION 10: OPERACIÓN HOTELERA
# ==============================================================================

@login_required
@operacion
@require_POST
def checkin_reserva(request, idre):
    with transaction.atomic():
        reserva = _reserva_bloqueada(idre)
        habitacion = reserva.habitacion
        error = None
        if reserva.estado != Reserva.CONFIRMADA:
            error = "Solo se puede registrar el check-in de reservas confirmadas."
        elif reserva.fecha_checkin is not None or reserva.fecha_checkout is not None:
            error = "Esta reserva ya tiene una llegada o salida registrada."
        elif reserva.fecha_inicio != date.today():
            error = "El check-in solo puede registrarse el día de llegada acordado."
        elif habitacion.estado != Habitacion.DISPONIBLE:
            error = "La habitación debe estar disponible, sin ocupación, limpieza ni mantenimiento."
        elif Reserva.objects.filter(habitacion=habitacion, estado=Reserva.EN_ESTADIA).exclude(pk=reserva.pk).exists():
            error = "La habitación tiene otra estadía activa."
        else:
            try:
                reserva.full_clean()
            except ValidationError as exc:
                error = " ".join(exc.messages)
        if error is None:
            if reserva.num_adultos is not None:
                error = _validar_reserva(
                    habitacion, reserva.fecha_inicio, reserva.fecha_fin,
                    excluir_reserva=reserva.id,
                    adultos=reserva.num_adultos, ninos=reserva.num_ninos,
                )
            elif habitacion.id in _habitaciones_ocupadas(
                reserva.fecha_inicio, reserva.fecha_fin, excluir_reserva=reserva.id
            ):
                error = "La habitación no está disponible en las fechas de la reserva."
        if error is None and (reserva.tarifa_noche is None or reserva.tarifa_noche < 0):
            error = "La reserva debe tener una tarifa por noche acordada válida."
        if error is None:
            minimo = min(reserva.tarifa_noche, reserva.gran_total)
            if reserva.total_pagado < minimo:
                error = f"El abono mínimo para registrar el check-in es {_formato_pesos(minimo)} COP."
        if error:
            messages.warning(request, error)
        else:
            reserva.fecha_checkin = timezone.now()
            reserva.estado = Reserva.EN_ESTADIA
            reserva.save(update_fields=["fecha_checkin", "estado"])
            messages.success(request, f"Check-in de la habitación {habitacion.numero} registrado correctamente.")
    destino = _next_valido(request)
    return redirect(destino) if destino else redirect("ver_reserva", idre=reserva.id)


@login_required
@operacion
@require_POST
def checkout_reserva(request, idre):
    with transaction.atomic():
        reserva = _reserva_bloqueada(idre)
        estado_hab = request.POST.get("estado_habitacion", Habitacion.LIMPIEZA).strip()
        if reserva.estado != Reserva.EN_ESTADIA:
            messages.warning(request, "Solo se puede hacer check-out de reservas con huésped en estadía.")
        elif reserva.fecha_checkin is None:
            messages.warning(request, "No se puede realizar el check-out: la reserva no tiene check-in.")
        elif reserva.fecha_checkout is not None:
            messages.info(request, "Esta reserva ya tiene check-out registrado.")
        elif estado_hab not in (Habitacion.LIMPIEZA, Habitacion.MANTENIMIENTO):
            messages.error(request, "La habitación debe quedar en limpieza o mantenimiento.")
        elif reserva.tarifa_noche is None:
            messages.error(request, "La reserva no tiene una tarifa por noche acordada.")
        elif reserva.saldo_pendiente != 0:
            messages.error(
                request,
                f"El cliente registra un saldo pendiente de {_formato_pesos(reserva.saldo_pendiente)}. "
                "Debe estar totalmente saldado.",
            )
        else:
            valor_final = reserva.gran_total
            reserva.fecha_checkout = timezone.now()
            reserva.estado = Reserva.FINALIZADA
            reserva.save(update_fields=["fecha_checkout", "estado"])
            habitacion = reserva.habitacion
            habitacion.estado = estado_hab
            habitacion.save(update_fields=["estado"])
            messages.success(
                request,
                f"Check-out de la habitación {habitacion.numero} registrado. "
                f"Valor final: {_formato_pesos(valor_final)}. "
                f"La habitación pasó a estado «{habitacion.get_estado_display()}».",
            )
    destino = _next_valido(request)
    return redirect(destino) if destino else redirect("ver_reserva", idre=reserva.id)


@login_required
@operacion
@require_POST
def agregar_servicio_reserva(request, idre):
    with transaction.atomic():
        reserva = _reserva_bloqueada(idre)
        idservicio = request.POST.get("servicio", "").strip()
        cantidad_raw = request.POST.get("cantidad", "1").strip()
        id_valido = (
            idservicio.isascii() and idservicio.isdigit() and len(idservicio) <= 19
            and 0 < int(idservicio) <= 9223372036854775807
        )
        cantidad = int(cantidad_raw) if (
            cantidad_raw.isascii() and cantidad_raw.isdigit() and len(cantidad_raw) <= 10
        ) else 0
        if reserva.estado not in ESTADOS_ACTIVOS:
            messages.warning(request, "No se pueden agregar servicios a reservas canceladas o finalizadas.")
        elif not id_valido or not 1 <= cantidad <= 2147483647:
            messages.warning(request, "Selecciona un servicio y una cantidad entera positiva válida.")
        else:
            servicio = Servicio.objects.filter(
                pk=int(idservicio), alojamiento_id=reserva.habitacion.alojamiento_id
            ).first()
            if servicio is None:
                messages.warning(request, "Selecciona un servicio del alojamiento de la reserva.")
            else:
                consumo = ServicioReserva(
                    reserva=reserva, servicio=servicio,
                    cantidad=cantidad, precio_unitario=servicio.precio,
                )
                try:
                    consumo.full_clean()
                    if consumo.precio_unitario < 0:
                        raise ValidationError("El precio del servicio no puede ser negativo.")
                except ValidationError as exc:
                    messages.warning(request, " ".join(exc.messages))
                else:
                    consumo.save()
                    messages.success(request, "Servicio agregado a la reserva.")
    return redirect("ver_reserva", idre=reserva.id)


@login_required
@operacion
@require_POST
def eliminar_servicio_reserva(request, idsr):
    with transaction.atomic():
        idre = get_object_or_404(ServicioReserva, pk=idsr).reserva_id
        reserva = _reserva_bloqueada(idre)
        servicio_reserva = get_object_or_404(
            ServicioReserva.objects.select_for_update(), pk=idsr, reserva_id=reserva.pk
        )
        if reserva.estado not in ESTADOS_ACTIVOS:
            messages.warning(request, "No se pueden eliminar consumos de reservas canceladas o finalizadas.")
        else:
            servicio_reserva.delete()
            messages.success(request, "Servicio eliminado de la reserva.")
    return redirect("ver_reserva", idre=idre)


def _crear_pago(reserva, monto, metodo, comprobante="", observacion=""):
    form = ImporteForm({"monto": monto})
    if not form.is_valid():
        return "Monto inválido: " + " ".join(form.errors["monto"])
    monto = form.cleaned_data["monto"]
    if monto <= 0:
        return "El monto del pago debe ser mayor que cero."
    if metodo not in dict(Pago.METODO_CHOICES):
        return "El método de pago solicitado no es válido."
    with transaction.atomic():
        reserva = _reserva_bloqueada(reserva.pk)
        if reserva.estado not in ESTADOS_ACTIVOS:
            return "No se pueden registrar pagos en reservas canceladas o finalizadas."
        if reserva.tarifa_noche is None:
            return "La reserva no tiene una tarifa por noche acordada."
        saldo = reserva.saldo_pendiente
        if monto > saldo:
            return (
                f"El monto (${monto:,.0f}) supera el saldo pendiente "
                f"(${saldo:,.0f})."
            )
        pago = Pago(
            reserva=reserva, monto=monto, metodo_pago=metodo,
            comprobante=comprobante, observacion=observacion,
        )
        try:
            pago.full_clean()
        except ValidationError as exc:
            return " ".join(exc.messages)
        pago.save()
    return None


@login_required
@operacion
@require_POST
def registrar_pago(request, idre):
    reserva = get_object_or_404(Reserva, id=idre)
    error = _crear_pago(
        reserva, request.POST.get("monto", "").strip(),
        request.POST.get("metodo_pago", "").strip(),
        request.POST.get("comprobante", "").strip(),
        request.POST.get("observacion", "").strip(),
    )
    if error:
        messages.warning(request, error)
    else:
        messages.success(request, "Pago registrado correctamente.")
    return redirect("ver_reserva", idre=reserva.id)


@login_required
@operacion
@require_POST
def eliminar_pago(request, idp):
    with transaction.atomic():
        idre = get_object_or_404(Pago, pk=idp).reserva_id
        reserva = _reserva_bloqueada(idre)
        pago = get_object_or_404(Pago.objects.select_for_update(), pk=idp, reserva_id=reserva.pk)
        if reserva.estado not in ESTADOS_ACTIVOS:
            messages.warning(request, "No se pueden eliminar pagos de reservas canceladas o finalizadas.")
        elif reserva.estado == Reserva.EN_ESTADIA and reserva.tarifa_noche is None:
            messages.warning(request, "La reserva no tiene una tarifa por noche acordada.")
        elif reserva.estado == Reserva.EN_ESTADIA and (
            reserva.total_pagado - pago.monto < min(reserva.tarifa_noche, reserva.gran_total)
        ):
            messages.warning(request, "No se puede eliminar el pago: la estadía quedaría sin el abono mínimo de garantía.")
        else:
            pago.delete()
            messages.success(request, "Pago eliminado.")
    destino = _next_valido(request)
    return redirect(destino) if destino else redirect("ver_reserva", idre=idre)


@login_required
@lectura_staff
@require_http_methods(["GET", "POST"])
def pagos(request):
    """Módulo de pagos: historial, saldos, métodos y registro de abonos."""
    if request.method == "POST":
        if not _tiene_rol(request.user, ROLES_OPERACION):
            messages.error(request, "Solo administración y recepción pueden registrar pagos.")
            return redirect("pagos")
        idre = request.POST.get("reserva", "").strip()
        id_valido = (
            idre.isascii() and idre.isdigit() and len(idre) <= 19
            and 0 < int(idre) <= 9223372036854775807
        )
        reserva = Reserva.objects.filter(pk=int(idre)).first() if id_valido else None
        if reserva is None:
            messages.warning(request, "Selecciona una reserva con saldo pendiente.")
        else:
            error = _crear_pago(
                reserva, request.POST.get("monto", "").strip(),
                request.POST.get("metodo_pago", "").strip(),
                request.POST.get("comprobante", "").strip(),
                request.POST.get("observacion", "").strip(),
            )
            if error:
                messages.warning(request, error)
            else:
                messages.success(
                    request,
                    f"Pago registrado para la reserva #{reserva.id}. "
                    f"Saldo actual: ${reserva.saldo_pendiente:,.0f}.",
                )
        return redirect("pagos")

    buscar = request.GET.get("buscar", "").strip()
    metodo = request.GET.get("metodo", "").strip()
    periodo = request.GET.get("periodo", "historico").strip()
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()

    hoy = date.today()
    d_inicio = d_fin = None
    if periodo == "hoy":
        d_inicio = d_fin = hoy
    elif periodo == "mes":
        d_inicio, d_fin = hoy.replace(day=1), hoy
    elif periodo == "rango":
        d_inicio, d_fin = _parse_fecha(fecha_desde), _parse_fecha(fecha_hasta)

    pagos_qs = Pago.objects.select_related(
        "reserva", "reserva__huesped", "reserva__habitacion"
    )
    if d_inicio:
        pagos_qs = pagos_qs.filter(fecha_pago__date__gte=d_inicio)
    if d_fin:
        pagos_qs = pagos_qs.filter(fecha_pago__date__lte=d_fin)
    if metodo:
        pagos_qs = pagos_qs.filter(metodo_pago=metodo)
    if buscar:
        pagos_qs = pagos_qs.filter(
            Q(reserva__huesped__nombre__icontains=buscar)
            | Q(reserva__huesped__apellido__icontains=buscar)
            | Q(reserva__huesped__numero_documento__icontains=buscar)
            | Q(reserva__habitacion__numero__icontains=buscar)
            | Q(comprobante__icontains=buscar)
        )

    total_periodo = pagos_qs.aggregate(total=Sum("monto"))["total"] or Decimal("0")
    total_historico = Pago.objects.aggregate(total=Sum("monto"))["total"] or Decimal("0")
    por_metodo = [
        (etiqueta, pagos_qs.filter(metodo_pago=valor).aggregate(total=Sum("monto"))["total"] or Decimal("0"))
        for valor, etiqueta in Pago.METODO_CHOICES
    ]

    saldo_pendiente = Decimal("0")
    reservas_con_saldo = []
    for r in (
        Reserva.objects.filter(estado__in=ESTADOS_ACTIVOS)
        .select_related("huesped", "habitacion")
        .prefetch_related("servicios_consumidos", "pagos")
    ):
        saldo = r.saldo_pendiente
        if saldo > 0:
            saldo_pendiente += saldo
            reservas_con_saldo.append(r)

    pagos_qs = pagos_qs.order_by("-fecha_pago")
    paginator = Paginator(pagos_qs, 15)
    pagina = paginator.get_page(request.GET.get("page"))

    return render(request, "pagos/index.html", {
        "pagos": pagina,
        "buscar": buscar,
        "metodo": metodo,
        "periodo": periodo,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "metodos": Pago.METODO_CHOICES,
        "por_metodo": por_metodo,
        "total_periodo": total_periodo,
        "total_historico": total_historico,
        "saldo_pendiente": saldo_pendiente,
        "reservas_con_saldo": reservas_con_saldo,
        "puede_registrar": _tiene_rol(request.user, ROLES_OPERACION),
    })


# ==============================================================================
# REGION 11: DASHBOARD E INDICADORES
# ==============================================================================

MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

COLOR_ESTADO = {
    Reserva.CONFIRMADA: "success",
    Reserva.PENDIENTE: "warning",
    Reserva.CANCELADA: "danger",
    Reserva.FINALIZADA: "secondary",
    Reserva.EN_ESTADIA: "info",
}

METODO_COLOR = {
    Pago.EFECTIVO: "success",
    Pago.TARJETA: "info",
    Pago.TRANSFERENCIA: "primary",
}


def _rango_periodo(periodo, desde, hasta, hoy, inicio_mes, inicio_semana):
    if periodo == "hoy":
        return hoy, hoy, "Hoy"
    if periodo == "semana":
        return inicio_semana, hoy, "Esta semana"
    if periodo == "rango":
        d, h = _parse_fecha(desde), _parse_fecha(hasta)
        if d and h and d <= h:
            return d, h, f"{d:%d/%m/%Y} – {h:%d/%m/%Y}"
    return inicio_mes, hoy, "Este mes"


@login_required
@solo_admin_gerente
def dashboard(request):
    contexto = _contexto_dashboard(
        periodo=request.GET.get("periodo", "mes"),
        desde=request.GET.get("desde", ""),
        hasta=request.GET.get("hasta", ""),
    )
    return render(request, "reportes/dashboard.html", contexto)


def _contexto_dashboard(periodo="mes", desde="", hasta=""):
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    inicio_semana = hoy - timedelta(days=hoy.weekday())

    total_habitaciones = Habitacion.objects.count()
    habitaciones_ocupadas = Habitacion.objects.filter(estado=Habitacion.OCUPADA).count()
    habitaciones_mantenimiento = Habitacion.objects.filter(estado=Habitacion.MANTENIMIENTO).count()
    habitaciones_disponibles = max(0, total_habitaciones - habitaciones_ocupadas - habitaciones_mantenimiento)

    porcentaje_ocupacion = round(habitaciones_ocupadas * 100 / total_habitaciones, 1) if total_habitaciones > 0 else 0

    reservas_activas = Reserva.objects.filter(estado__in=ESTADOS_ACTIVOS).count()
    reservas_pendientes = Reserva.objects.filter(estado=Reserva.PENDIENTE).count()
    reservas_vencidas = Reserva.objects.filter(
        estado__in=[Reserva.PENDIENTE, Reserva.CONFIRMADA],
        fecha_fin__lt=hoy,
    ).count()
    reservas_dia = Reserva.objects.filter(fecha_creacion__date=hoy).count()
    huespedes_registrados = Huesped.objects.count()

    llegadas_hoy = (
        Reserva.objects
        .select_related("huesped", "habitacion")
        .filter(fecha_inicio=hoy)
        .exclude(estado=Reserva.CANCELADA)
        .order_by("habitacion__numero")
    )
    salidas_hoy = (
        Reserva.objects
        .select_related("huesped", "habitacion")
        .filter(fecha_fin=hoy)
        .exclude(estado=Reserva.CANCELADA)
        .order_by("habitacion__numero")
    )

    ingresos_total = Pago.objects.aggregate(total=Sum("monto"))["total"] or Decimal("0")
    ingresos_mes = Pago.objects.filter(fecha_pago__date__gte=inicio_mes).aggregate(total=Sum("monto"))["total"] or Decimal("0")
    
    p_desde, p_hasta, periodo_label = _rango_periodo(periodo, desde, hasta, hoy, inicio_mes, inicio_semana)
    pagos_periodo = Pago.objects.filter(fecha_pago__date__gte=p_desde, fecha_pago__date__lte=p_hasta)
    ingresos_periodo = pagos_periodo.aggregate(total=Sum("monto"))["total"] or Decimal("0")

    tot_metodo = {f["metodo_pago"]: (f["t"] or Decimal("0")) for f in pagos_periodo.values("metodo_pago").annotate(t=Sum("monto"))}
    ingresos_por_metodo = []
    for codigo, label in Pago.METODO_CHOICES:
        total_m = tot_metodo.get(codigo, Decimal("0"))
        pct = round(float(total_m) * 100 / float(ingresos_periodo), 1) if ingresos_periodo else 0
        ingresos_por_metodo.append({
            "codigo": codigo, "label": label, "total": total_m,
            "color": METODO_COLOR.get(codigo, "secondary"), "porcentaje": pct,
        })

    saldo_por_cobrar = Decimal("0")
    for r in Reserva.objects.filter(estado__in=ESTADOS_ACTIVOS).prefetch_related("servicios_consumidos", "pagos").select_related("habitacion"):
        if r.saldo_pendiente > 0:
            saldo_por_cobrar += r.saldo_pendiente

    reservas_hoy = llegadas_hoy.count() + salidas_hoy.count()

    inicio_grafico = (hoy.replace(day=1) - timedelta(days=150)).replace(day=1)
    reservas_por_mes = list(
        Reserva.objects.filter(fecha_creacion__date__gte=inicio_grafico)
        .annotate(mes=TruncMonth("fecha_creacion"))
        .values("mes")
        .annotate(total=Count("id"))
        .order_by("mes")
    )
    conteo_por_mes = {
        (fila["mes"].year, fila["mes"].month): fila["total"]
        for fila in reservas_por_mes
    }
    max_reservas_mes = max(conteo_por_mes.values(), default=1) or 1
    grafico_reservas = []
    cursor_mes = inicio_grafico
    while (cursor_mes.year, cursor_mes.month) <= (hoy.year, hoy.month):
        total_mes = conteo_por_mes.get((cursor_mes.year, cursor_mes.month), 0)
        grafico_reservas.append({
            "label": f"{MESES_ES[cursor_mes.month - 1]} {cursor_mes.year}",
            "total": total_mes,
            "porcentaje": max(5, int(total_mes * 100 / max_reservas_mes)) if total_mes else 0,
        })
        cursor_mes = (cursor_mes.replace(day=28) + timedelta(days=4)).replace(day=1)

    return {
        "total_habitaciones": total_habitaciones,
        "habitaciones_ocupadas": habitaciones_ocupadas,
        "habitaciones_mantenimiento": habitaciones_mantenimiento,
        "habitaciones_disponibles": habitaciones_disponibles,
        "porcentaje_ocupacion": porcentaje_ocupacion,
        "reservas_hoy": reservas_hoy,
        "grafico_reservas": grafico_reservas,
        "reservas_activas": reservas_activas,
        "reservas_pendientes": reservas_pendientes,
        "reservas_vencidas": reservas_vencidas,
        "reservas_dia": reservas_dia,
        "huespedes_registrados": huespedes_registrados,
        "llegadas_hoy": llegadas_hoy,
        "salidas_hoy": salidas_hoy,
        "ingresos_total": ingresos_total,
        "ingresos_mes": ingresos_mes,
        "periodo": periodo,
        "periodo_label": periodo_label,
        "ingresos_periodo": ingresos_periodo,
        "ingresos_por_metodo": ingresos_por_metodo,
        "saldo_por_cobrar": saldo_por_cobrar,
        "todas_las_habitaciones": Habitacion.objects.select_related('tipo', 'alojamiento').order_by('numero'),
    }


# ==============================================================================
# REGION 12: REPORTES
# ==============================================================================

@login_required
@solo_admin_gerente
def reportes_index(request):
    return render(request, "reportes/index.html")


@login_required
@solo_admin_gerente
def reporte_reservas(request):
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()
    estado = request.GET.get("estado", "").strip()
    idhabitacion = request.GET.get("habitacion", "").strip()
    buscar = request.GET.get("buscar", "").strip()

    reservas_qs = Reserva.objects.select_related("huesped", "habitacion", "habitacion__alojamiento")
    d = _parse_fecha(fecha_desde)
    h = _parse_fecha(fecha_hasta)
    if d:
        reservas_qs = reservas_qs.filter(fecha_inicio__gte=d)
    if h:
        reservas_qs = reservas_qs.filter(fecha_inicio__lte=h)
    if estado:
        reservas_qs = reservas_qs.filter(estado=estado)
    if idhabitacion.isdigit():
        reservas_qs = reservas_qs.filter(habitacion_id=idhabitacion)
    if buscar:
        reservas_qs = reservas_qs.filter(
            Q(huesped__nombre__icontains=buscar)
            | Q(huesped__apellido__icontains=buscar)
            | Q(huesped__numero_documento__icontains=buscar)
        )

    reservas_qs = reservas_qs.order_by("-fecha_inicio", "-id")
    paginator = Paginator(reservas_qs, 15)
    reservas = paginator.get_page(request.GET.get("page"))

    return render(request, "reportes/reservas.html", {
        "reservas": reservas,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "estado": estado,
        "habitacion": idhabitacion,
        "buscar": buscar,
        "estados": Reserva.ESTADO_CHOICES,
        "habitaciones": Habitacion.objects.select_related("alojamiento").order_by("numero"),
    })


@login_required
@solo_admin_gerente
def reporte_ocupacion(request):
    total = Habitacion.objects.count()
    ocupadas = Habitacion.objects.filter(estado=Habitacion.OCUPADA).count()
    disponibles = Habitacion.objects.filter(estado=Habitacion.DISPONIBLE).count()
    porcentaje = round(ocupadas * 100 / total, 1) if total else 0

    por_alojamiento = (
        Alojamiento.objects.annotate(
            total=Count("habitaciones"),
            ocupadas=Count("habitaciones", filter=Q(habitaciones__estado=Habitacion.OCUPADA)),
            disponibles=Count("habitaciones", filter=Q(habitaciones__estado=Habitacion.DISPONIBLE)),
        )
        .order_by("nombre")
    )

    return render(request, "reportes/ocupacion.html", {
        "total": total,
        "ocupadas": ocupadas,
        "disponibles": disponibles,
        "porcentaje": porcentaje,
        "por_alojamiento": por_alojamiento,
    })


@login_required
@solo_admin_gerente
def reporte_ingresos(request):
    periodo = request.GET.get("periodo", "mes").strip()
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()

    hoy = date.today()
    d_inicio = None
    d_fin = None

    # Lógica de Filtros Rápidos
    if periodo == "hoy":
        d_inicio = hoy
        d_fin = hoy
    elif periodo == "ayer":
        d_inicio = hoy - timedelta(days=1)
        d_fin = hoy - timedelta(days=1)
    elif periodo == "mes":
        d_inicio = hoy.replace(day=1)
        d_fin = hoy
    elif periodo == "rango" and fecha_desde and fecha_hasta:
        d_inicio = _parse_fecha(fecha_desde)
        d_fin = _parse_fecha(fecha_hasta)
    elif periodo == "historico":
        d_inicio = None
        d_fin = None

    pagos_qs = Pago.objects.select_related("reserva", "reserva__huesped", "reserva__habitacion")
    if d_inicio:
        pagos_qs = pagos_qs.filter(fecha_pago__date__gte=d_inicio)
    if d_fin:
        pagos_qs = pagos_qs.filter(fecha_pago__date__lte=d_fin)

    total_recaudado = pagos_qs.aggregate(total=Sum("monto"))["total"] or Decimal("0")
    total_historico = Pago.objects.aggregate(total=Sum("monto"))["total"] or Decimal("0")

    total_efectivo = pagos_qs.filter(metodo_pago=Pago.EFECTIVO).aggregate(total=Sum("monto"))["total"] or Decimal("0")
    total_transferencia = pagos_qs.filter(metodo_pago=Pago.TRANSFERENCIA).aggregate(total=Sum("monto"))["total"] or Decimal("0")
    total_tarjeta = pagos_qs.filter(metodo_pago=Pago.TARJETA).aggregate(total=Sum("monto"))["total"] or Decimal("0")

    # Construcción de barras por día para el mes seleccionado
    mes_ref = d_inicio if d_inicio else hoy
    _, num_dias = calendar.monthrange(mes_ref.year, mes_ref.month)
    
    pagos_mes = Pago.objects.filter(
        fecha_pago__year=mes_ref.year, 
        fecha_pago__month=mes_ref.month
    )
    ingresos_por_dia_raw = {
        item['dia']: item['total'] 
        for item in pagos_mes.order_by().annotate(dia=ExtractDay('fecha_pago')).values('dia').annotate(total=Sum('monto'))
    }

    max_ingreso_dia = max(ingresos_por_dia_raw.values(), default=Decimal("1")) or Decimal("1")
    
    grafico_dias = []
    for dia in range(1, num_dias + 1):
        monto_dia = ingresos_por_dia_raw.get(dia, Decimal("0"))
        porcentaje = float(monto_dia * 100 / max_ingreso_dia) if max_ingreso_dia else 0
        grafico_dias.append({
            "dia": dia,
            "monto": monto_dia,
            "porcentaje": min(100, max(5, int(porcentaje))) if monto_dia > 0 else 0
        })

    por_metodo_raw = {fila["metodo_pago"]: fila["total"] for fila in pagos_qs.values("metodo_pago").annotate(total=Sum("monto"))}
    por_metodo = [(etiqueta, por_metodo_raw.get(valor, Decimal("0"))) for valor, etiqueta in Pago.METODO_CHOICES]

    saldo_pendiente = Decimal("0")
    for r in Reserva.objects.exclude(estado=Reserva.CANCELADA).prefetch_related("servicios_consumidos", "pagos").select_related("habitacion"):
        saldo_pendiente += r.saldo_pendiente

    pagos_qs = pagos_qs.order_by("-fecha_pago")
    paginator = Paginator(pagos_qs, 15)
    pagos = paginator.get_page(request.GET.get("page"))

    return render(request, "reportes/ingresos.html", {
        "pagos": pagos,
        "periodo": periodo,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "total_recaudado": total_recaudado,
        "total_historico": total_historico,
        "total_efectivo": total_efectivo,
        "total_transferencia": total_transferencia,
        "total_tarjeta": total_tarjeta,
        "por_metodo": por_metodo,
        "saldo_pendiente": saldo_pendiente,
        "grafico_dias": grafico_dias,
        "num_dias": num_dias,
        "mes_nombre": date_format(mes_ref, "F").capitalize(),
    })


@login_required
@solo_admin_gerente
def reporte_huespedes(request):
    buscar = request.GET.get("buscar", "").strip()
    origen = request.GET.get("origen", "").strip()
    tipo_cliente = request.GET.get("tipo_cliente", "").strip()
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()

    huespedes_qs = Huesped.objects.annotate(
        num_reservas=Count("reservas", filter=~Q(reservas__estado=Reserva.CANCELADA))
    ).prefetch_related("reservas__habitacion", "reservas__habitacion__tipo")

    # Filtros de búsqueda
    if buscar:
        huespedes_qs = huespedes_qs.filter(
            Q(nombre__icontains=buscar)
            | Q(apellido__icontains=buscar)
            | Q(numero_documento__icontains=buscar)
            | Q(ciudad_residencia__icontains=buscar)
        )

    if origen == "nacional":
        huespedes_qs = huespedes_qs.filter(es_extranjero=False)
    elif origen == "internacional":
        huespedes_qs = huespedes_qs.filter(es_extranjero=True)

    if tipo_cliente == "nuevo":
        huespedes_qs = huespedes_qs.filter(num_reservas=1)
    elif tipo_cliente == "frecuente":
        huespedes_qs = huespedes_qs.filter(num_reservas__gte=2)

    d = _parse_fecha(fecha_desde)
    h = _parse_fecha(fecha_hasta)
    if d:
        huespedes_qs = huespedes_qs.filter(reservas__fecha_inicio__gte=d)
    if h:
        huespedes_qs = huespedes_qs.filter(reservas__fecha_fin__lte=h)

    huespedes_qs = huespedes_qs.distinct().order_by("-num_reservas", "apellido")

    # KPIs Principales
    total_huespedes = huespedes_qs.count()
    recurrentes_count = huespedes_qs.filter(num_reservas__gte=2).count()
    porcentaje_fidelidad = round((recurrentes_count * 100 / total_huespedes), 1) if total_huespedes > 0 else 0

    # Distribución Nacional vs Internacional
    nacionales_count = huespedes_qs.filter(es_extranjero=False).count()
    internacionales_count = huespedes_qs.filter(es_extranjero=True).count()
    pct_nacional = round((nacionales_count * 100 / total_huespedes), 0) if total_huespedes > 0 else 100
    pct_internacional = round((internacionales_count * 100 / total_huespedes), 0) if total_huespedes > 0 else 0

    reservas_activas = Reserva.objects.filter(huesped__in=huespedes_qs).exclude(estado=Reserva.CANCELADA)
    total_noches = sum(r.noches for r in reservas_activas)
    promedio_estadia = round(total_noches / reservas_activas.count(), 1) if reservas_activas.exists() else 0

    top_ciudades = (
        huespedes_qs.values("ciudad_residencia")
        .annotate(total=Count("id"))
        .order_by("-total")[:3]
    )

    paginator = Paginator(huespedes_qs, 15)
    huespedes = paginator.get_page(request.GET.get("page"))

    return render(request, "reportes/huespedes.html", {
        "huespedes": huespedes,
        "buscar": buscar,
        "origen": origen,
        "tipo_cliente": tipo_cliente,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "total_huespedes": total_huespedes,
        "porcentaje_fidelidad": porcentaje_fidelidad,
        "promedio_estadia": promedio_estadia,
        "top_ciudades": top_ciudades,
        "internacionales_count": internacionales_count,
        "nacionales_count": nacionales_count,
        "pct_nacional": int(pct_nacional),
        "pct_internacional": int(pct_internacional),
    })


@login_required
@solo_admin_gerente
def reporte_habitaciones(request):
    buscar = request.GET.get("buscar", "").strip()
    estado = request.GET.get("estado", "").strip()
    idtipo = request.GET.get("tipo", "").strip()
    idalojamiento = request.GET.get("alojamiento", "").strip()

    habitaciones_qs = (
        Habitacion.objects.select_related("tipo", "alojamiento")
        .annotate(
            num_reservas=Count(
                "reservas",
                filter=~Q(reservas__estado=Reserva.CANCELADA),
                distinct=True,
            ),
            ingresos=Sum(
                "reservas__pagos__monto",
                filter=~Q(reservas__estado=Reserva.CANCELADA),
            ),
        )
    )
    if buscar:
        habitaciones_qs = habitaciones_qs.filter(
            Q(numero__icontains=buscar) | Q(tipo__nombre__icontains=buscar)
        )
    if estado:
        habitaciones_qs = habitaciones_qs.filter(estado=estado)
    if idtipo.isdigit():
        habitaciones_qs = habitaciones_qs.filter(tipo_id=idtipo)
    if idalojamiento.isdigit():
        habitaciones_qs = habitaciones_qs.filter(alojamiento_id=idalojamiento)

    habitaciones_qs = habitaciones_qs.order_by("alojamiento__nombre", "numero")
    total = habitaciones_qs.count()
    disponibles = habitaciones_qs.filter(estado=Habitacion.DISPONIBLE).count()
    ocupadas = habitaciones_qs.filter(estado=Habitacion.OCUPADA).count()
    mantenimiento = habitaciones_qs.filter(estado=Habitacion.MANTENIMIENTO).count()
    porcentaje = round(ocupadas * 100 / total, 1) if total else 0
    precio_promedio = habitaciones_qs.aggregate(promedio=Avg("precio_noche"))["promedio"] or Decimal("0")
    ingresos_total = sum((h.ingresos or Decimal("0")) for h in habitaciones_qs)

    paginator = Paginator(habitaciones_qs, 15)
    pagina = paginator.get_page(request.GET.get("page"))

    return render(request, "reportes/habitaciones.html", {
        "habitaciones": pagina,
        "buscar": buscar,
        "estado": estado,
        "tipo": idtipo,
        "alojamiento": idalojamiento,
        "estados": Habitacion.ESTADO_CHOICES,
        "tipos": TipoHabitacion.objects.all(),
        "alojamientos": Alojamiento.objects.all(),
        "total": total,
        "disponibles": disponibles,
        "ocupadas": ocupadas,
        "mantenimiento": mantenimiento,
        "porcentaje": porcentaje,
        "precio_promedio": precio_promedio,
        "ingresos_total": ingresos_total,
    })


@login_required
@solo_admin_gerente
def reporte_servicios(request):
    buscar = request.GET.get("buscar", "").strip()
    idservicio = request.GET.get("servicio", "").strip()
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()

    consumos_qs = (
        ServicioReserva.objects.select_related(
            "servicio", "reserva", "reserva__huesped", "reserva__habitacion"
        )
        .exclude(reserva__estado=Reserva.CANCELADA)
    )
    if idservicio.isdigit():
        consumos_qs = consumos_qs.filter(servicio_id=idservicio)
    if buscar:
        consumos_qs = consumos_qs.filter(
            Q(reserva__huesped__nombre__icontains=buscar)
            | Q(reserva__huesped__apellido__icontains=buscar)
            | Q(reserva__habitacion__numero__icontains=buscar)
            | Q(servicio__nombre__icontains=buscar)
        )
    d = _parse_fecha(fecha_desde)
    h = _parse_fecha(fecha_hasta)
    if d:
        consumos_qs = consumos_qs.filter(reserva__fecha_inicio__gte=d)
    if h:
        consumos_qs = consumos_qs.filter(reserva__fecha_inicio__lte=h)

    por_servicio = list(
        consumos_qs.values("servicio__id", "servicio__nombre")
        .annotate(
            unidades=Sum("cantidad"),
            total=Sum(
                F("cantidad") * F("precio_unitario"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            ventas=Count("id"),
        )
        .order_by("-total")
    )
    total_vendido = sum((fila["unidades"] or 0) for fila in por_servicio)
    ingresos_servicios = sum((fila["total"] or Decimal("0")) for fila in por_servicio)
    servicios_distintos = len(por_servicio)
    promedio_venta = (
        (ingresos_servicios / total_vendido).quantize(Decimal("0.01"))
        if total_vendido else Decimal("0")
    )

    consumos_qs = consumos_qs.order_by("-reserva__fecha_inicio", "-id")
    paginator = Paginator(consumos_qs, 15)
    pagina = paginator.get_page(request.GET.get("page"))

    return render(request, "reportes/servicios.html", {
        "consumos": pagina,
        "por_servicio": por_servicio,
        "servicios": Servicio.objects.order_by("nombre"),
        "buscar": buscar,
        "servicio": idservicio,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "total_vendido": total_vendido,
        "ingresos_servicios": ingresos_servicios,
        "servicios_distintos": servicios_distintos,
        "promedio_venta": promedio_venta,
    })

# ==============================================================================
# REGION 12B: PORTAL PÚBLICO / POSADA WAYRA
# ==============================================================================

def _contexto_sitios():
    return SitioTuristico.objects.all().order_by("orden", "nombre")


def posada_wayra(request):
    """Portal público principal en /posada_wayra/."""
    filtros = _parametros_busqueda(request)
    disponibles = _habitaciones_publicas(
        filtros["entrada"], filtros["salida"], filtros["adultos"], filtros["ninos"]
    )
    return render(request, "publico/portal.html", {
        **_contexto_publico(),
        "filtros": filtros,
        "habitaciones": disponibles[:6],
        "total_disponibles": disponibles.count(),
        "sitios": _contexto_sitios(),
        "configuracion": ConfiguracionHotel.cargar(),
    })


def posada_habitaciones(request):
    """Listado completo del catálogo ordenado: primero disponibles, luego no disponibles."""
    filtros = _parametros_busqueda(request)
    
    # Obtenemos todas las habitaciones activas (sin excluir por reservas previas)
    todas_habitaciones = Habitacion.objects.select_related("tipo", "alojamiento").exclude(
        estado=Habitacion.MANTENIMIENTO
    ).order_by("numero")

    # Identificamos cuáles sí están libres para las fechas elegidas (con capacidad mínima 1)
    ids_libres = set(
        _habitaciones_publicas(filtros["entrada"], filtros["salida"], 1, 0)
        .values_list("id", flat=True)
    )

    disponibles_lista = []
    no_disponibles_lista = []

    for h in todas_habitaciones:
        h.ocupada_en_fechas = h.id not in ids_libres
        h.sin_capacidad = not h.tipo.admite(filtros["adultos"], filtros["ninos"])
        if not h.ocupada_en_fechas and not h.sin_capacidad:
            disponibles_lista.append(h)
        else:
            no_disponibles_lista.append(h)

    # Unimos las listas poniendo primero las disponibles y después las no disponibles
    lista_ordenada = disponibles_lista + no_disponibles_lista

    paginator = Paginator(lista_ordenada, 9)
    habitaciones = paginator.get_page(request.GET.get("page"))

    return render(request, "publico/habitaciones.html", {
        **_contexto_publico(),
        "filtros": filtros,
        "habitaciones": habitaciones,
        "total_disponibles": len(disponibles_lista),
        "total_no_disponibles": len(no_disponibles_lista),
        "sitios": _contexto_sitios(),
    })


def posada_ver_habitacion(request, idh):
    habitacion = get_object_or_404(
        Habitacion.objects.select_related("tipo", "alojamiento").prefetch_related("fotografias"), id=idh
    )
    filtros = _parametros_busqueda(request)
    return _render_detalle_habitacion(request, habitacion, filtros)


def _render_detalle_habitacion(request, habitacion, filtros, error=None):
    disponible = _habitaciones_publicas(filtros["entrada"], filtros["salida"],
                                       filtros["adultos"], filtros["ninos"]).filter(pk=habitacion.pk).exists()
    total_estimado = Decimal(filtros["noches"]) * habitacion.precio_noche
    return render(request, "publico/habitacion_detalle.html", {
        **_contexto_publico(), "error": error, "datos_reserva": request.POST,
        "habitacion": habitacion, "filtros": filtros, "disponible": disponible,
        "total_estimado": total_estimado, "minimo_abono": _minimo_abono(habitacion, total_estimado),
        "es_cliente": _es_cliente(request.user), "sitios": _contexto_sitios(),
    })


# ==============================================================================
# REGION 13: PORTAL DEL CLIENTE
# ==============================================================================

def _es_cliente(user):
    return bool(user.is_authenticated and user.rol_id and user.rol.nombre == Rol.CLIENTE)


solo_cliente = user_passes_test(_es_cliente, login_url="home")


def registro_cliente(request):
    if request.user.is_authenticated:
        return redirect("home")
    error = None
    destino = _next_valido(request)
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            if not password or password != request.POST.get("password2", ""):
                raise ValidationError("Introduce contraseñas válidas y coincidentes.")
            with transaction.atomic():
                rol_cliente, _ = Rol.objects.get_or_create(nombre=Rol.CLIENTE)
                usuario = Usuario(username=request.POST.get("username", "").strip(),
                                  first_name=request.POST.get("nombre", request.POST.get("nombres", "")).strip(),
                                  last_name=request.POST.get("apellido", request.POST.get("apellidos", "")).strip(),
                                  email=request.POST.get("correo", request.POST.get("email", "")).strip(), rol=rol_cliente)
                if not usuario.first_name or not usuario.last_name or not usuario.email:
                    raise ValidationError("Completa nombre, apellido y correo electrónico.")
                validate_password(password, usuario)
                usuario.set_password(password)
                usuario.full_clean()
                usuario.save()
                huesped = usuario.huesped
                _datos_huesped_formulario(request, huesped)
                huesped.full_clean()
                huesped.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "El usuario o el documento ya está registrado."
        else:
            login(request, usuario)
            messages.success(request, "Tu cuenta fue creada correctamente.")
            return redirect(destino or "posada_wayra")
    return render(request, "publico/registro.html", {
        **_contexto_publico(), "error": error, "datos": request.POST,
        "next": destino or "", "tipos": Huesped.TIPO_DOC_CHOICES,
    })


@login_required(login_url="cliente_login")
@solo_cliente
def cliente_habitaciones(request):
    return posada_habitaciones(request)


@login_required(login_url="cliente_login")
@solo_cliente
def cliente_ver_habitacion(request, idh):
    return posada_ver_habitacion(request, idh)


@login_required(login_url="cliente_login")
@solo_cliente
@require_POST
def cliente_reservar(request):
    huesped = request.user.huesped_perfil
    if huesped is None:
        messages.warning(request, "Tu cuenta no tiene perfil de huésped. Contacta a recepción.")
        return redirect("cliente_mis_reservas")
    idhabitacion = request.POST.get("habitacion", "")
    if not idhabitacion.isdecimal():
        messages.error(request, "Selecciona una habitación válida.")
        return redirect("posada_habitaciones")
    habitacion = get_object_or_404(Habitacion.objects.select_related("tipo", "alojamiento").prefetch_related("fotografias"), pk=idhabitacion)
    entrada = _parse_fecha(request.POST.get("fecha_entrada", request.POST.get("fecha_inicio")))
    salida = _parse_fecha(request.POST.get("fecha_salida", request.POST.get("fecha_fin")))
    adultos, ninos, error = _ocupacion_solicitada(request)
    importe = ImporteForm({"monto": request.POST.get("monto_abono")})
    metodo = request.POST.get("metodo_pago", "")
    if not importe.is_valid():
        error = "Introduce un abono válido con máximo dos decimales."
    if metodo not in dict(Pago.METODO_CHOICES):
        error = "Selecciona un método de pago válido."
    if error is None:
        try:
            with transaction.atomic():
                habitacion = _habitacion_bloqueada(idhabitacion)
                error = _validar_reserva(habitacion, entrada, salida, adultos=adultos, ninos=ninos)
                if error:
                    raise ValidationError(error)
                total = Decimal((salida - entrada).days) * habitacion.precio_noche
                monto = importe.cleaned_data["monto"]
                minimo = _minimo_abono(habitacion, total)
                if monto < minimo or monto > total:
                    raise ValidationError(f"El abono debe estar entre {_formato_pesos(minimo)} y {_formato_pesos(total)} COP.")
                reserva = Reserva(huesped=huesped, habitacion=habitacion, num_personas=adultos + ninos,
                                  num_adultos=adultos, num_ninos=ninos, fecha_inicio=entrada, fecha_fin=salida,
                                  tarifa_noche=habitacion.precio_noche)
                reserva.full_clean()
                reserva.save()
                if monto > 0:
                    pago = Pago(reserva=reserva, monto=monto, metodo_pago=metodo,
                                observacion="Abono declarado por el cliente, pendiente de validación por recepción")
                    pago.full_clean()
                    pago.save()
        except ValidationError as exc:
            error = " ".join(exc.messages)
        else:
            messages.success(request, f"Solicitud #{reserva.pk} registrada. Recepción verificará el abono declarado; este formulario no procesa un cobro bancario.")
            return redirect("cliente_mis_reservas")
    messages.error(request, error)
    llegada = entrada or date.today()
    partida = salida if salida and salida > llegada else llegada + timedelta(days=1)
    filtros = {"entrada": llegada, "salida": partida, "adultos": adultos or 1,
               "ninos": ninos if ninos is not None else 0, "noches": (partida - llegada).days, "aplicado": True}
    return _render_detalle_habitacion(request, habitacion, filtros, error)


@login_required(login_url="cliente_login")
@solo_cliente
def cliente_mis_reservas(request):
    huesped = request.user.huesped_perfil
    hoy = date.today()
    vigentes = historial = Reserva.objects.none()
    if huesped:
        base = Reserva.objects.select_related("habitacion", "habitacion__alojamiento").filter(huesped=huesped)
        vigentes = base.filter(estado__in=ESTADOS_ACTIVOS).order_by("fecha_inicio")
        historial = base.exclude(estado__in=ESTADOS_ACTIVOS).order_by("-fecha_inicio")
        
    return render(request, "publico/cliente/mis_reservas.html", {
        **_contexto_publico(),
        "huesped": huesped,
        "vigentes": vigentes,
        "historial": historial,
        "hoy": hoy,
    })


@login_required(login_url="cliente_login")
@solo_cliente
def cliente_ver_reserva(request, idre):
    reserva = get_object_or_404(Reserva.objects.select_related("habitacion__tipo", "huesped").prefetch_related(
        "pagos", "servicios_consumidos__servicio"), pk=idre, huesped=request.user.huesped_perfil)
    return render(request, "publico/cliente/ver_reserva.html", {
        **_contexto_publico(), "reserva": reserva, "pagos": reserva.pagos.all(),
        "servicios_reserva": reserva.servicios_consumidos.all(),
    })


@login_required(login_url="cliente_login")
@solo_cliente
@require_POST
@transaction.atomic
def cliente_solicitar_cancelacion(request, idre):
    huesped = request.user.huesped_perfil
    reserva = get_object_or_404(Reserva.objects.select_for_update(), id=idre, huesped=huesped)
    if reserva.estado in (Reserva.CANCELADA, Reserva.FINALIZADA):
        messages.info(request, "Esta reserva ya no admite cancelación.")
    elif reserva.estado == Reserva.EN_ESTADIA:
        messages.warning(request, "Ya realizaste check-in. Acércate a recepción para gestionar una salida anticipada.")
    elif reserva.cancelacion_solicitada:
        messages.info(request, "Ya tienes una solicitud de cancelación en revisión por recepción.")
    else:
        reserva.cancelacion_solicitada = True
        reserva.save(update_fields=["cancelacion_solicitada"])
        messages.success(
            request,
            "Tu solicitud de cancelación fue enviada a recepción. "
            "En breve validarán la cancelación y el estado de tu abono."
        )
    return redirect("cliente_mis_reservas")



def _datos_sitio_formulario(request, sitio):
    sitio.nombre = request.POST.get("nombre", "").strip()
    sitio.municipio = request.POST.get("municipio", "").strip()
    sitio.descripcion = request.POST.get("descripcion", "").strip()
    distancia = _precio_servicio(request.POST.get("distancia_km", "").strip() or "0")
    if distancia is None or distancia < 0:
        raise ValidationError({"distancia_km": "La distancia debe ser un decimal finito no negativo."})
    sitio.distancia_km = distancia
    try:
        sitio.orden = int(request.POST.get("orden", "").strip() or "0")
    except (ValueError, TypeError, OverflowError):
        raise ValidationError({"orden": "El orden debe ser un número entero no negativo."})
    if sitio.orden < 0:
        raise ValidationError({"orden": "El orden no puede ser negativo."})
    principal = request.FILES.get("imagen")
    if principal:
        sitio.imagen = validar_imagen(principal)
    elif request.POST.get("quitar_imagen") == "1":
        sitio.imagen = None
    sitio.full_clean()
    fotografias = []
    for archivo in request.FILES.getlist("fotografias"):
        fotografia = FotografiaSitio(sitio=sitio, imagen=validar_imagen(archivo))
        fotografia.full_clean(exclude=["sitio"])
        fotografias.append(fotografia)
    return fotografias


def _guardar_galeria_sitio(sitio, fotografias):
    ultima = sitio.fotografias.order_by("-orden").values_list("orden", flat=True).first()
    orden_inicial = (ultima if ultima is not None else 0) + 1
    for orden, fotografia in enumerate(fotografias, start=orden_inicial):
        fotografia.sitio = sitio
        fotografia.orden = orden
        fotografia.save()


@login_required
@lectura_staff
def listar_sitios(request):
    sitios = SitioTuristico.objects.prefetch_related("fotografias").all().order_by("orden", "nombre")
    return render(request, "alojamientos/listar_alojamientos.html", {"sitios": sitios})


@login_required
@solo_admin
def registrar_sitio(request):
    error = None
    sitio = SitioTuristico()
    if request.method == "POST":
        try:
            fotografias = _datos_sitio_formulario(request, sitio)
            with transaction.atomic():
                sitio.save()
                _guardar_galeria_sitio(sitio, fotografias)
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo registrar el destino y su galería; revisa los datos."
        else:
            messages.success(request, "Destino turístico registrado correctamente.")
            return redirect("listar_sitios")
    return render(request, "alojamientos/registrar_alojamiento.html", {"sitio": sitio, "error": error})


@login_required
@solo_admin
def editar_sitio(request, sitio_id):
    sitio = get_object_or_404(SitioTuristico, id=sitio_id)
    error = None
    if request.method == "POST":
        try:
            with transaction.atomic():
                sitio = get_object_or_404(SitioTuristico.objects.select_for_update(), id=sitio_id)
                fotografias = _datos_sitio_formulario(request, sitio)
                sitio.save()
                _guardar_galeria_sitio(sitio, fotografias)
        except ValidationError as exc:
            error = " ".join(exc.messages)
        except IntegrityError:
            error = "No se pudo actualizar el destino y su galería; revisa los datos."
        else:
            messages.success(request, "Destino turístico actualizado correctamente.")
            return redirect("editar_sitio", sitio_id=sitio.id)
    return render(request, "alojamientos/editar_alojamiento.html", {
        "sitio": sitio,
        "fotografias": sitio.fotografias.all(),
        "error": error,
    })


@login_required
@solo_admin
@require_POST
def eliminar_sitio(request, sitio_id):
    sitio = get_object_or_404(SitioTuristico, id=sitio_id)
    try:
        with transaction.atomic():
            sitio.delete()
    except ProtectedError:
        messages.error(request, "No se puede eliminar el destino porque tiene registros asociados protegidos.")
    else:
        messages.success(request, "Destino turístico eliminado.")
    return redirect("listar_sitios")


@login_required
@solo_admin
@require_POST
def eliminar_fotografia_sitio(request, foto_id):
    foto = get_object_or_404(FotografiaSitio, id=foto_id)
    sitio_id = foto.sitio_id
    try:
        with transaction.atomic():
            foto.delete()
    except ProtectedError:
        messages.error(request, "No se puede eliminar una fotografía con registros asociados protegidos.")
    else:
        messages.success(request, "Fotografía eliminada del slider.")
    return redirect("editar_sitio", sitio_id=sitio_id)