# ==============================================================================
# PROYECTO: SysHSENA / Posada Wayra
# ARCHIVO: syshsena/models.py
# DESCRIPCIÓN: Modelos de datos principales y señales de automatización.
# ==============================================================================

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal


# ==============================================================================
# REGION 1: ROLES Y AUTENTICACIÓN DE USUARIOS
# ==============================================================================

class Rol(models.Model):
    """
    Define los niveles de acceso y responsabilidades en el sistema.
    """
    ADMINISTRADOR = 'ADMINISTRADOR'
    RECEPCIONISTA = 'RECEPCIONISTA'
    CLIENTE = 'CLIENTE'
    GERENTE = 'GERENTE'

    NOMBRE_CHOICES = [
        (ADMINISTRADOR, 'Administrador'),
        (RECEPCIONISTA, 'Recepcionista'),
        (CLIENTE, 'Cliente'),
        (GERENTE, 'Gerente'),
    ]

    nombre = models.CharField(
        max_length=50, 
        choices=NOMBRE_CHOICES, 
        unique=True,
        verbose_name="Nombre del Rol"
    )

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"
        ordering = ['nombre']

    def __str__(self):
        return self.get_nombre_display()


class Usuario(AbstractUser):
    """
    Modelo de usuario personalizado para gestión de seguridad y credenciales.
    """
    rol = models.ForeignKey(
        Rol, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        verbose_name="Rol asignado"
    )
    avatar = models.ImageField(
        upload_to='avatares/',
        blank=True,
        null=True,
        verbose_name="Fotografía de perfil"
    )

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        rol_nombre = self.rol.nombre if self.rol else 'Sin Rol'
        return f"{self.username} ({rol_nombre})"

    @property
    def huesped_perfil(self):
        """Acceso seguro al perfil de Huésped asociado si existe."""
        return getattr(self, 'huesped', None)

    @property
    def iniciales(self):
        nombre = f"{self.first_name} {self.last_name}".strip() or self.username
        partes = [parte for parte in nombre.split() if parte]
        return ''.join(parte[0] for parte in partes[:2]).upper()


class ConfiguracionHotel(models.Model):
    """Datos institucionales editables por Administración y Gerencia.

    Es un singleton: siempre se consulta y actualiza la fila con pk=1 para que
    encabezados, pies de página, recibos y el portal público compartan la
    misma fuente de verdad.
    """
    nombre = models.CharField(max_length=120, default='Posada Wayra', verbose_name="Nombre del establecimiento")
    nit = models.CharField(max_length=30, blank=True, null=True, verbose_name="NIT / Registro")
    direccion = models.CharField(
        max_length=200,
        default='Cl. 1 # 9-95, Riohacha, La Guajira, Colombia',
        verbose_name="Dirección oficial",
    )
    ciudad = models.CharField(max_length=80, default='Riohacha', verbose_name="Ciudad")
    departamento = models.CharField(max_length=80, default='La Guajira', verbose_name="Departamento")
    pais = models.CharField(max_length=80, default='Colombia', verbose_name="País")
    telefono = models.CharField(max_length=30, default='+57 322 220 352', verbose_name="Teléfono")
    whatsapp = models.CharField(max_length=30, default='+57 322 220 352', verbose_name="WhatsApp")
    email = models.EmailField(default='posadawayra@gmail.com', verbose_name="Correo institucional")
    logo = models.ImageField(upload_to='alojamientos/', blank=True, null=True, verbose_name="Logo")
    banner = models.ImageField(upload_to='alojamientos/', blank=True, null=True, verbose_name="Banner principal")
    politicas = models.TextField(
        default=(
            'Check-in desde las 3:00 p.m. y check-out hasta las 11:00 a.m. '
            'Para garantizar la reserva se requiere abonar mínimo 1 noche. '
            'El huésped debe presentarse el primer día pactado; de no realizar '
            'el check-in durante ese día, la reserva se cancela automáticamente '
            'sin derecho a reembolso. No se permite fumar dentro de las '
            'habitaciones. El documento de identidad es obligatorio al registrar '
            'la llegada.'
        ),
        verbose_name="Políticas de alojamiento",
    )
    horario_checkin = models.CharField(max_length=50, default='3:00 p.m.', verbose_name="Horario de check-in")
    horario_checkout = models.CharField(max_length=50, default='11:00 a.m.', verbose_name="Horario de check-out")
    edad_max_nino = models.PositiveSmallIntegerField(default=11, validators=[MaxValueValidator(17)], verbose_name="Edad máxima de niño")
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración del hotel"
        verbose_name_plural = "Configuración del hotel"

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def cargar(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)

    @property
    def direccion_completa(self):
        base = (self.direccion or '').strip()
        partes = [base] if base else []
        for parte in (self.ciudad, self.departamento, self.pais):
            if parte and parte.strip().lower() not in base.lower():
                partes.append(parte.strip())
        return ', '.join(partes)

    @property
    def whatsapp_enlace(self):
        return ''.join(caracter for caracter in (self.whatsapp or '') if caracter.isdigit())


# ==============================================================================
# REGION 2: PERFILES DE IDENTIDAD (HUÉSPEDES)
# ==============================================================================

class Huesped(models.Model):
    """
    Fuente única de la verdad para datos personales de clientes y huéspedes walk-in.
    Cumple con los requerimientos normativos (MinCIT / SITT) y métricas comerciales.
    """
    TIPO_DOC_CHOICES = [
        ('CC', 'Cédula de Ciudadanía'),
        ('CE', 'Cédula de Extranjería'),
        ('PAS', 'Pasaporte'),
        ('TI', 'Tarjeta de Identidad'),
    ]

    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='huesped',
        verbose_name="Cuenta de Usuario Asociada"
    )

    tipo_documento = models.CharField(
        max_length=10, 
        choices=TIPO_DOC_CHOICES, 
        default='CC',
        verbose_name="Tipo de Documento"
    )
    numero_documento = models.CharField(
        max_length=20, 
        unique=True,
        default='00000000',
        verbose_name="Número de Documento"
    )
    nombre = models.CharField(max_length=100, default='', verbose_name="Nombre(s)")
    apellido = models.CharField(max_length=100, default='', verbose_name="Apellido(s)")
    telefono = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono")
    email = models.EmailField(blank=True, null=True, verbose_name="Correo Electrónico")
    direccion = models.CharField(max_length=200, blank=True, null=True, verbose_name="Dirección")

    # Nuevos campos normativos y de procedencia (MinCIT / SITT / TRH)
    nacionalidad = models.CharField(max_length=100, default='Colombiana', verbose_name="Nacionalidad")
    ciudad_residencia = models.CharField(max_length=100, default='Bogotá', verbose_name="Ciudad de Residencia")
    pais_residencia = models.CharField(max_length=100, default='Colombia', verbose_name="País de Residencia")
    es_extranjero = models.BooleanField(default=False, verbose_name="¿Es Huésped Internacional?")

    class Meta:
        verbose_name = "Huésped"
        verbose_name_plural = "Huéspedes"
        ordering = ['apellido', 'nombre']

    def __str__(self):
        return f"{self.nombre} {self.apellido} - {self.tipo_documento}: {self.numero_documento}"

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}".strip()

    @property
    def total_facturado(self):
        """Suma total acumulada de dinero gastado en reservas no canceladas."""
        total_res = sum(r.gran_total for r in self.reservas.exclude(estado='CANCELADA'))
        return Decimal(total_res)

    @property
    def es_frecuente(self):
        """Etiqueta VIP si cuenta con 2 o más reservas no canceladas."""
        return self.reservas.exclude(estado='CANCELADA').count() >= 2


# ==============================================================================
# REGION 3: INFRAESTRUCTURA Y HABITACIONES
# ==============================================================================

class Alojamiento(models.Model):
    """
    Representa el establecimiento físico (ej. Posada Wayra).
    """
    nombre = models.CharField(max_length=100, default='Posada Wayra', verbose_name="Nombre del Alojamiento")
    municipio = models.CharField(max_length=100, default='Riohacha', verbose_name="Municipio")
    direccion = models.CharField(max_length=200, default='Riohacha, La Guajira', verbose_name="Dirección")
    telefono = models.CharField(max_length=20, default='', verbose_name="Teléfono")
    email = models.EmailField(blank=True, null=True, verbose_name="Correo Institucional")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    informacion_turistica = models.TextField(blank=True, null=True, verbose_name="Información Turística")
    imagen = models.ImageField(upload_to='alojamientos/', blank=True, null=True, verbose_name="Fotografía Principal")
    sitios_turisticos = models.ManyToManyField(
        'SitioTuristico',


        blank=True,
        related_name='alojamientos',
        verbose_name="Sitios Turísticos Cercanos",
    )

    class Meta:
        verbose_name = "Alojamiento"
        verbose_name_plural = "Alojamientos"

    def __str__(self):
        return f"{self.nombre} - {self.municipio}"

    @property
    def servicios_disponibles(self):
        return self.servicios.all()


class SitioTuristico(models.Model):
    """Atractivos de La Guajira cercanos al establecimiento."""
    nombre = models.CharField(max_length=120, verbose_name="Nombre del Sitio")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    municipio = models.CharField(max_length=100, default='Riohacha', verbose_name="Municipio")
    distancia_km = models.DecimalField(max_digits=8, decimal_places=1, default=0, verbose_name="Distancia (km)")
    imagen = models.ImageField(upload_to='sitios/', blank=True, null=True, verbose_name="Fotografía")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")

    class Meta:
        verbose_name = "Sitio Turístico"
        verbose_name_plural = "Sitios Turísticos"
        ordering = ['orden', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.municipio})"

class FotografiaSitio(models.Model):
    sitio = models.ForeignKey(SitioTuristico, on_delete=models.CASCADE, related_name="fotografias")
    imagen = models.ImageField(upload_to="sitios/galeria/")
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "Fotografía del sitio"
        verbose_name_plural = "Fotografías de sitios"

    def __str__(self):
        return f"Foto {self.id} - {self.sitio.nombre}"

class FotografiaAlojamiento(models.Model):
    """Galería de fotografías de un alojamiento."""
    alojamiento = models.ForeignKey(
        Alojamiento, on_delete=models.CASCADE, related_name='fotografias'
    )
    titulo = models.CharField(max_length=120, blank=True, null=True, verbose_name="Título")
    imagen = models.ImageField(upload_to='alojamientos/', verbose_name="Fotografía")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")

    class Meta:
        verbose_name = "Fotografía del Alojamiento"
        verbose_name_plural = "Fotografías del Alojamiento"
        ordering = ['orden', 'id']

    def __str__(self):
        return self.titulo or f"Fotografía #{self.id}"


class TipoHabitacion(models.Model):
    """
    Categorías de habitaciones (Individual, Doble, Suite, etc.).
    """
    nombre = models.CharField(max_length=50, verbose_name="Tipo de Habitación")
    capacidad = models.PositiveIntegerField(default=2, verbose_name="Capacidad total (personas)")
    max_adultos = models.PositiveIntegerField(default=1, verbose_name="Máximo de adultos")
    max_ninos = models.PositiveIntegerField(default=1, verbose_name="Máximo de niños")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    
    class Meta:
        verbose_name = "Tipo de Habitación"
        verbose_name_plural = "Tipos de Habitación"

    def clean(self):
        super().clean()
        if not isinstance(self.capacidad, int) or self.capacidad < 1:
            raise ValidationError({"capacidad": "La ocupación total debe ser al menos 1."})
        if not isinstance(self.max_adultos, int) or not 1 <= self.max_adultos <= self.capacidad:
            raise ValidationError({"max_adultos": "Debe admitir al menos un adulto sin superar la ocupación total."})
        if not isinstance(self.max_ninos, int) or not 0 <= self.max_ninos < self.capacidad:
            raise ValidationError({"max_ninos": "Los niños cuentan dentro del cupo total y debe quedar sitio para un adulto."})

    def admite(self, adultos, ninos):
        return (1 <= adultos <= self.max_adultos and 0 <= ninos <= self.max_ninos
                and adultos + ninos <= self.capacidad)

    def __str__(self):
        return f"{self.nombre} (Máx. {self.capacidad} personas: {self.max_adultos} adultos, {self.max_ninos} niños)"


class Habitacion(models.Model):
    """
    Habitaciones físicas del alojamiento.
    """
    DISPONIBLE = 'DISPONIBLE'
    OCUPADA = 'OCUPADA'
    LIMPIEZA = 'LIMPIEZA'
    MANTENIMIENTO = 'MANTENIMIENTO'

    ESTADO_CHOICES = [
        (DISPONIBLE, 'Disponible'),
        (OCUPADA, 'Ocupada'),
        (LIMPIEZA, 'En Limpieza'),
        (MANTENIMIENTO, 'En Mantenimiento'),
    ]

    alojamiento = models.ForeignKey(Alojamiento, on_delete=models.CASCADE, related_name='habitaciones')
    tipo = models.ForeignKey(TipoHabitacion, on_delete=models.PROTECT, related_name='habitaciones')
    numero = models.CharField(max_length=10, verbose_name="Número / Identificador")
    piso = models.IntegerField(default=1, verbose_name="Piso / Ubicación")
    precio_noche = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Precio por Noche (COP)")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=DISPONIBLE, verbose_name="Estado Actual")
    imagen = models.ImageField(upload_to='habitaciones/', default='habitaciones/default.jpg', blank=True, null=True)

    class Meta:
        verbose_name = "Habitación"
        verbose_name_plural = "Habitaciones"
        ordering = ['numero']

    def __str__(self):
        return f"Habitación {self.numero} ({self.tipo.nombre}) - {self.get_estado_display()}"

    @property
    def capacidad(self):
        """Devuelve la capacidad total desde TipoHabitacion."""
        return self.tipo.capacidad if self.tipo else 1

    @property
    def max_adultos(self):
        """Devuelve el máximo de adultos permitidos."""
        return self.tipo.max_adultos if self.tipo else 1

    @property
    def max_ninos(self):
        """Devuelve el máximo de niños permitidos."""
        return self.tipo.max_ninos if self.tipo else 1

    @property
    def precio(self):
        """Alias de precio_noche para compatibilidad con las plantillas HTML."""
        return self.precio_noche


class FotografiaHabitacion(models.Model):
    habitacion = models.ForeignKey(Habitacion, on_delete=models.CASCADE, related_name="fotografias")
    imagen = models.ImageField(upload_to="habitaciones/galeria/")
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]


# ==============================================================================
# REGION 4: SERVICIOS ADICIONALES
# ==============================================================================

class Servicio(models.Model):
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.DecimalField(decimal_places=2, max_digits=10)
    alojamiento = models.ForeignKey(Alojamiento, on_delete=models.CASCADE, related_name='servicios')
    momento_dia = models.CharField(max_length=50, default='General')
    imagen_url = models.URLField(blank=True, null=True)
    imagen = models.ImageField(upload_to='alojamientos/', blank=True, null=True)


# ==============================================================================
# REGION 5: RESERVAS Y OPERACIÓN HOTELERA
# ==============================================================================

class Reserva(models.Model):
    """
    Gestión del ciclo de vida operativo de una reserva.
    """
    PENDIENTE = 'PENDIENTE'
    CONFIRMADA = 'CONFIRMADA'
    EN_ESTADIA = 'EN_ESTADIA'
    FINALIZADA = 'FINALIZADA'
    CANCELADA = 'CANCELADA'

    ESTADO_CHOICES = [
        (PENDIENTE, 'Pendiente de Confirmación'),
        (CONFIRMADA, 'Reserva Confirmada'),
        (EN_ESTADIA, 'Huésped en Estadía (Check-in)'),
        (FINALIZADA, 'Estadía Finalizada (Check-out)'),
        (CANCELADA, 'Reserva Cancelada'),
    ]

    huesped = models.ForeignKey(Huesped, on_delete=models.PROTECT, related_name='reservas')
    habitacion = models.ForeignKey(Habitacion, on_delete=models.PROTECT, related_name='reservas')
    num_personas = models.PositiveIntegerField(default=1, verbose_name="Número de Huéspedes")
    num_adultos = models.PositiveIntegerField(null=True, blank=True, verbose_name="Adultos")
    num_ninos = models.PositiveIntegerField(null=True, blank=True, verbose_name="Niños")
    tarifa_noche = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Tarifa por noche acordada")
    fecha_inicio = models.DateField(default=timezone.now, verbose_name="Fecha de Llegada (Check-in estipulado)")
    fecha_fin = models.DateField(default=timezone.now, verbose_name="Fecha de Salida (Check-out estipulado)")
    
    fecha_checkin = models.DateTimeField(null=True, blank=True, verbose_name="Fecha/Hora Check-in Real")
    fecha_checkout = models.DateTimeField(null=True, blank=True, verbose_name="Fecha/Hora Check-out Real")
    
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=PENDIENTE)
    cancelacion_solicitada = models.BooleanField(default=False, verbose_name="Solicitud de Cancelación")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"Reserva #{self.id} - {self.huesped.nombre_completo} ({self.get_estado_display()})"

    def clean(self):
        super().clean()
        if self.fecha_fin and self.fecha_inicio and self.fecha_fin <= self.fecha_inicio:
            raise ValidationError("La fecha de salida debe ser posterior a la fecha de llegada.")
        if self.habitacion_id and self.num_personas > self.habitacion.capacidad:
            raise ValidationError("El número de huéspedes supera la ocupación total de la habitación.")
        if (self.num_adultos is None) != (self.num_ninos is None):
            raise ValidationError("Indica tanto adultos como niños.")
        if self.num_adultos is not None and self.habitacion_id:
            if not self.habitacion.tipo.admite(self.num_adultos, self.num_ninos):
                raise ValidationError("La combinación de adultos y niños supera los límites de la habitación.")
            if self.num_personas != self.num_adultos + self.num_ninos:
                raise ValidationError("La ocupación total debe coincidir con adultos más niños.")

    def save(self, *args, **kwargs):
        if self.tarifa_noche is None:
            self.tarifa_noche = self.habitacion.precio_noche
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"tarifa_noche"}
        super().save(*args, **kwargs)

    @property
    def noches(self):
        if self.fecha_fin and self.fecha_inicio:
            dias = (self.fecha_fin - self.fecha_inicio).days
            return max(dias, 1)
        return 1

    @property
    def valor_habitacion_total(self):
        return Decimal(self.noches) * self.tarifa_noche

    @property
    def valor_servicios_total(self):
        total = sum(item.subtotal for item in self.servicios_consumidos.all())
        return Decimal(total)

    @property
    def gran_total(self):
        return self.valor_habitacion_total + self.valor_servicios_total

    @property
    def total_pagado(self):
        total = sum(pago.monto for pago in self.pagos.all())
        return Decimal(total)

    @property
    def saldo_pendiente(self):
        return max(self.gran_total - self.total_pagado, Decimal('0.00'))


class ServicioReserva(models.Model):
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='servicios_consumidos')
    servicio = models.ForeignKey(Servicio, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        verbose_name = "Consumo de Servicio"
        verbose_name_plural = "Consumos de Servicios"

    def save(self, *args, **kwargs):
        if not self.precio_unitario:
            self.precio_unitario = self.servicio.precio
        super().save(*args, **kwargs)

    @property
    def subtotal(self):
        return Decimal(self.cantidad) * self.precio_unitario


# ==============================================================================
# REGION 6: FINANZAS Y PAGOS
# ==============================================================================

class Pago(models.Model):
    EFECTIVO = 'EFECTIVO'
    TARJETA = 'TARJETA'
    TRANSFERENCIA = 'TRANSFERENCIA'

    METODO_CHOICES = [
        (EFECTIVO, 'Efectivo'),
        (TARJETA, 'Tarjeta Débito/Crédito'),
        (TRANSFERENCIA, 'Transferencia bancaria / Nequi / Daviplata'),
    ]

    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='pagos')
    monto = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Monto Abonado (COP)")
    metodo_pago = models.CharField(max_length=20, choices=METODO_CHOICES, default=EFECTIVO)
    fecha_pago = models.DateTimeField(default=timezone.now, verbose_name="Fecha del Pago")
    comprobante = models.CharField(max_length=100, blank=True, null=True, verbose_name="Número de Comprobante/Referencia")
    observacion = models.TextField(blank=True, null=True, verbose_name="Observaciones")

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ['-fecha_pago']

    def __str__(self):
        return f"Pago #{self.id} - Reserva #{self.reserva.id}: ${self.monto:,.0f} ({self.get_metodo_pago_display()})"


# ==============================================================================
# REGION 7: SEÑALES Y AUTOMATIZACIÓN
# ==============================================================================

@receiver(post_save, sender=Usuario)
def sincronizar_perfil_huesped(sender, instance, created, **kwargs):
    if instance.rol and instance.rol.nombre == Rol.CLIENTE:
        huesped, _ = Huesped.objects.get_or_create(
            usuario=instance, defaults={"numero_documento": f"PEND-{instance.pk}"}
        )
        
        modificado = False
        if instance.email and huesped.email != instance.email:
            huesped.email = instance.email
            modificado = True

        if instance.first_name and huesped.nombre != instance.first_name:
            huesped.nombre = instance.first_name
            modificado = True

        if instance.last_name and huesped.apellido != instance.last_name:
            huesped.apellido = instance.last_name
            modificado = True

        if modificado:
            huesped.save()


@receiver(post_save, sender=Reserva)
def actualizar_estado_habitacion_segun_reserva(sender, instance, **kwargs):
    habitacion = instance.habitacion

    if instance.estado == Reserva.EN_ESTADIA:
        if habitacion.estado != Habitacion.OCUPADA:
            habitacion.estado = Habitacion.OCUPADA
            habitacion.save(update_fields=['estado'])

    elif instance.estado in [Reserva.FINALIZADA, Reserva.CANCELADA]:
        otras_activas = Reserva.objects.filter(
            habitacion=habitacion, 
            estado=Reserva.EN_ESTADIA
        ).exclude(id=instance.id).exists()

        if not otras_activas and habitacion.estado == Habitacion.OCUPADA:
            habitacion.estado = (
                Habitacion.LIMPIEZA
                if instance.estado == Reserva.FINALIZADA
                else Habitacion.DISPONIBLE
            )
            habitacion.save(update_fields=['estado'])