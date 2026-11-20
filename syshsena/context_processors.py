from .models import ConfiguracionHotel


def hotel_config(request):
    """Expone los datos institucionales a todas las plantillas como `hotel`."""
    return {"hotel": ConfiguracionHotel.cargar()}
