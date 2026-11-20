from django import forms
from django.core.exceptions import ValidationError


def validar_imagen(archivo):
    if archivo.size > 8 * 1024 * 1024:
        raise ValidationError("Cada imagen puede pesar como máximo 8 MB.")
    limpio = forms.ImageField().clean(archivo)
    if limpio.image.format not in {"JPEG", "PNG", "WEBP"}:
        raise ValidationError("Selecciona una imagen JPG, PNG o WEBP.")
    limpio.seek(0)
    return limpio


class OcupacionForm(forms.Form):
    adultos = forms.IntegerField(min_value=1)
    ninos = forms.IntegerField(min_value=0)


class ImporteForm(forms.Form):
    monto = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0)
