"""Filtros propios de SysHSENA para las plantillas.

Se registran automaticamente porque 'syshsena' esta en INSTALLED_APPS.
Uso en una plantilla:  {% load hotel_extras %}  y luego  {{ valor|pesos }}.
"""
from decimal import Decimal, InvalidOperation

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def pesos(valor):
    """Formatea un numero como pesos colombianos: $1.515.000 (sin decimales).

    Se usa un unico formato en TODO el dashboard para dar consistencia:
    simbolo $, separador de miles con punto y sin centavos.
    """
    if valor is None or valor == "":
        return "$0"
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return valor
    # Formato con coma de miles y luego se cambia a punto (estilo Colombia).
    entero = f"{numero:,.0f}".replace(",", ".")
    return f"${entero}"


@register.filter
def badge_estado(estado):
    """Devuelve la clase de color de Bootstrap segun el estado de la reserva."""
    mapa = {
        "CONFIRMADA": "success",
        "PENDIENTE": "warning text-dark",
        "EN_ESTADIA": "info text-dark",
        "CANCELADA": "danger",
        "FINALIZADA": "secondary",
    }
    return mapa.get(estado, "light text-dark")


@register.filter
def hace(valor):
    """Tiempo transcurrido legible: 'Pendiente desde hace 2 horas'."""
    if not valor:
        return ""
    ahora = timezone.now()
    segundos = max(0, int((ahora - valor).total_seconds()))
    minutos = segundos // 60
    if minutos < 1:
        return "hace instantes"
    if minutos < 60:
        return f"hace {minutos} minuto{'s' if minutos != 1 else ''}"
    horas = minutos // 60
    if horas < 24:
        return f"hace {horas} hora{'s' if horas != 1 else ''}"
    dias = horas // 24
    return f"hace {dias} día{'s' if dias != 1 else ''}"


@register.filter
def clase_habitacion(estado):
    """Clase del pill para los estados operativos de una habitación."""
    mapa = {
        "DISPONIBLE": "pill-success",
        "OCUPADA": "pill-danger",
        "LIMPIEZA": "pill-info",
        "MANTENIMIENTO": "pill-warning",
    }
    return mapa.get(estado, "pill-secondary")



