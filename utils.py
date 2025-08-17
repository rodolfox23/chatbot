# utils.py
from flask import current_app

def get_settings_collection():
    """Devuelve la colección de settings usando la conexión ya creada en app.py."""
    return current_app.db.settings

def get_settings():
    """Obtiene el documento de configuración global."""
    try:
        doc = current_app.db.settings.find_one({'_id': 'global_settings'})
        return doc or {}
    except Exception as e:
        print(f"Error getting settings: {e}")
        return {}

def load_messages():
    """Carga mensajes desde la colección 'messages' y los devuelve como dict {key: value}."""
    try:
        messages = {}
        for msg in current_app.db.messages.find({}):
            k = msg.get('key')
            v = msg.get('value')
            if k is not None and v is not None:
                messages[k] = v
        return messages
    except Exception as e:
        print(f"Error al cargar mensajes desde la base de datos: {e}")
        # Devuelve None para que app.py use el DEFAULT_MESSAGES como fallback
        return None

def get_active_services():
    """
    Devuelve la lista de servicios activos (según tu esquema actual: is_active = True).
    Convierte _id a string por conveniencia (si lo necesitas).
    """
    try:
        services = list(current_app.db.services.find({'is_active': True}).sort('_id', 1))
        for s in services:
            # si prefieres conservar ObjectId, elimina la línea siguiente
            s['_id'] = str(s['_id'])
        return services
    except Exception as e:
        print(f"Error getting active services: {e}")
        return []

def get_service_duration(service_name: str) -> int:
    """
    Devuelve la duración del servicio (minutos) desde settings.service_durations.
    Fallback por defecto: 60 minutos.
    """
    try:
        settings = get_settings()
        service_durations = settings.get('service_durations', {})
        duration = service_durations.get(service_name)
        if isinstance(duration, (int, float)):
            return int(duration)

        # (Opcional) Si quieres intentar leer desde la colección de servicios:
        # svc = current_app.db.services.find_one({'name': service_name})
        # if svc and isinstance(svc.get('duration'), (int, float)):
        #     return int(svc['duration'])

        return 60
    except Exception as e:
        print(f"Error getting service duration: {e}")
        return 60
