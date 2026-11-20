from django.db import DatabaseError
from .models import ConfiguracionHotel


def hotel_config(request):
    try:
        hotel = ConfiguracionHotel.cargar()
    except DatabaseError:
        hotel = None
    return {"hotel": hotel}