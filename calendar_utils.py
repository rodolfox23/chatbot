import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
from typing import Optional
import logging
import re
from utils import get_settings, get_service_duration
from dotenv import load_dotenv
import json

# Cargar variables de entorno
load_dotenv()

# Configuración de Google Calendar desde variables de entorno
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', 'service_account_credentials.json')
CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')

if not CALENDAR_ID:
    # Usamos logging si está disponible, o print como fallback.
    try:
        logging.critical("La variable de entorno GOOGLE_CALENDAR_ID no está configurada.")
    except NameError:
        print("CRITICAL: La variable de entorno GOOGLE_CALENDAR_ID no está configurada.")
    raise ValueError("La variable de entorno GOOGLE_CALENDAR_ID no está configurada.")

def get_calendar_service():
    """Crea y devuelve un objeto de servicio de Google Calendar."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build('calendar', 'v3', credentials=credentials)
    except FileNotFoundError:
        logging.error(f"Error: El archivo de credenciales '{SERVICE_ACCOUNT_FILE}' no fue encontrado.")
        return None
    except Exception as e:
        logging.error(f"Error al crear el servicio de calendario: {e}", exc_info=True)
        return None

def create_calendar_event(service_type, client_name, phone_number, date_time_santiago):
    """Crea un evento en Google Calendar con la fecha exacta en Santiago."""
    try:
        logging.info(f"[GOOGLE CALENDAR] Iniciando creación de evento para {client_name} - {service_type}")
        logging.info(f"[GOOGLE CALENDAR] Fecha y hora: {date_time_santiago}")
        logging.info(f"[GOOGLE CALENDAR] CALENDAR_ID configurado: {CALENDAR_ID}")
        
        # Obtener la duración del servicio desde la configuración
        service_duration = get_service_duration(service_type)
        logging.info(f"[GOOGLE CALENDAR] Duración del servicio: {service_duration} horas")
        
        # Calcular la hora de fin
        end_time = date_time_santiago + timedelta(minutes=service_duration)
        logging.info(f"[GOOGLE CALENDAR] Hora de fin: {end_time}")
        
        # Crear el evento
        event = {
            'summary': f'{service_type} - {client_name}',
            'description': f'Cliente: {client_name}\nTeléfono: {phone_number}\nServicio: {service_type}',
            'start': {
                'dateTime': date_time_santiago.isoformat(),
                'timeZone': 'America/Santiago',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'America/Santiago',
            },
        }
        
        print(f"[DEBUG] Hora de inicio enviada: {date_time_santiago} (tzinfo: {date_time_santiago.tzinfo})")
        print(f"[DEBUG] Hora de fin enviada: {end_time} (tzinfo: {end_time.tzinfo})")
        print(f"[DEBUG] Diccionario del evento enviado a Google Calendar:")
        print(json.dumps(event, indent=2, default=str))
        
        calendar_service = get_calendar_service()
        if not calendar_service:
            logging.error("[GOOGLE CALENDAR] ERROR: No se pudo obtener el servicio de calendario")
            return None
            
        logging.info(f"[GOOGLE CALENDAR] Servicio de calendario obtenido correctamente")
        logging.info(f"[GOOGLE CALENDAR] Intentando insertar evento en calendario ID: {CALENDAR_ID}")
        
        # Intentar crear el evento
        created_event = calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        
        logging.info(f"[GOOGLE CALENDAR] ✅ EVENTO CREADO EXITOSAMENTE!")
        logging.info(f"[GOOGLE CALENDAR] ID del evento: {created_event.get('id')}")
        logging.info(f"[GOOGLE CALENDAR] Link del evento: {created_event.get('htmlLink')}")
        logging.info(f"[GOOGLE CALENDAR] Título: {created_event.get('summary')}")
        logging.info(f"[GOOGLE CALENDAR] Inicio: {created_event.get('start')}")
        logging.info(f"[GOOGLE CALENDAR] Fin: {created_event.get('end')}")
        
        return created_event
        
    except Exception as e:
        logging.error(f"[GOOGLE CALENDAR] ❌ ERROR al crear evento en Google Calendar: {e}")
        logging.error(f"[GOOGLE CALENDAR] Detalles del error: {str(e)}")
        if hasattr(e, 'content'):
            logging.error(f"[GOOGLE CALENDAR] Respuesta del servidor: {e.content}")
        return None

def check_availability(date_time_santiago: datetime, service_type: str) -> (bool, str):
    """
    Revisa si el horario solicitado está disponible, usando fechas en Santiago.
    """
    service = get_calendar_service()
    if not service:
        return False, "No se pudo conectar con el calendario."

    settings = get_settings()
    business_hours = settings.get('business_hours', {'start': '09:00', 'end': '18:00'})
    business_days = settings.get('business_days', [0, 1, 2, 3, 4, 5]) 
    santiago_tz = pytz.timezone('America/Santiago')
    
    # Asegurar que la fecha tenga tzinfo de Santiago
    if date_time_santiago.tzinfo is None:
        date_time_santiago = santiago_tz.localize(date_time_santiago)
    
    # Usar directamente la fecha en Santiago para validaciones
    santiago_time = date_time_santiago

    if santiago_time.weekday() not in business_days:
        return False, f"⚠️ Lo siento, no atendemos los domingos."

    start_h, start_m = map(int, business_hours['start'].split(':'))
    end_h, end_m = map(int, business_hours['end'].split(':'))

    if not (santiago_time.time() >= datetime.strptime(business_hours['start'], '%H:%M').time() and 
            santiago_time.time() < datetime.strptime(business_hours['end'], '%H:%M').time()):
        return False, f"⚠️ Lo siento, nuestro horario de atención es de {business_hours['start']} a {business_hours['end']}."

    # Obtener duración desde la configuración de settings
    duration_minutes = get_service_duration(service_type)
    
    # Convertir a UTC solo para la consulta al calendario
    start_check_utc = date_time_santiago.astimezone(pytz.utc)
    end_check_utc = start_check_utc + timedelta(minutes=duration_minutes)
    
    try:
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_check_utc.isoformat(),
            timeMax=end_check_utc.isoformat(),
            singleEvents=True,
            timeZone='UTC' # Importante: la consulta se hace en UTC
        ).execute()
        
        if events_result.get('items', []):
            return False, "⚠️ Lo siento, ese horario ya está ocupado. Por favor, elige otro."

        return True, "disponible"

    except Exception as e:
        logging.error(f"Error al chequear disponibilidad: {e}", exc_info=True)
        return False, "Ocurrió un error al verificar la disponibilidad."

def parse_date_only(input_str: str) -> Optional[datetime]:
    """
    Parsea un string de fecha (sin hora) y devuelve un objeto datetime
    consciente de la zona horaria (America/Santiago) para el inicio del día.
    """
    santiago_tz = pytz.timezone('America/Santiago')
    now = datetime.now(santiago_tz)
    text_normalized = input_str.lower().strip()

    # Patrón para 'hoy'
    if 'hoy' in text_normalized:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Patrón para 'mañana'
    elif 'mañana' in text_normalized:
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Patrón para DD/MM
    match = re.fullmatch(r'(\d{1,2})/(\d{1,2})', text_normalized)
    if match:
        try:
            day, month = map(int, match.groups())
            # Asumir año actual. Si la fecha es pasada, asumir el siguiente año.
            year = now.year
            candidate_date = santiago_tz.localize(datetime(year, month, day, 0, 0), is_dst=None)
            if candidate_date < now:
                candidate_date = santiago_tz.localize(datetime(year + 1, month, day, 0, 0), is_dst=None)
            return candidate_date
        except (ValueError, IndexError):
            pass

    return None

def parse_datetime(input_str: str) -> Optional[datetime]:
    """
    Parsea un string de fecha/hora y SIEMPRE devuelve un objeto datetime
    consciente de la zona horaria (America/Santiago).
    """
    logging.info(f"[DEBUG parse_datetime] Texto recibido: '{input_str}'")
    santiago_tz = pytz.timezone('America/Santiago')
    now = datetime.now(santiago_tz)
    text_normalized = input_str.lower().strip()

    # Patrón mejorado para DD/MM HH:MM (con o sin 'a las')
    match = re.search(r'(\d{1,2}/\d{1,2})\s+(?:a las\s+)?(\d{1,2}:\d{2})', text_normalized)
    if match:
        try:
            date_part, time_part = match.groups()
            day, month = map(int, date_part.split('/'))
            hour, minute = map(int, time_part.split(':'))
            year = now.year
            candidate_date = santiago_tz.localize(datetime(year, month, day, hour, minute), is_dst=None)
            if candidate_date < now:
                candidate_date = santiago_tz.localize(datetime(year + 1, month, day, hour, minute), is_dst=None)
            return candidate_date
        except (ValueError, IndexError):
            pass

    # Patrón para 'hoy' o 'mañana' + HH:MM (con o sin 'a las')
    day_keyword = None
    if 'hoy' in text_normalized:
        day_keyword = now
    elif 'mañana' in text_normalized:
        day_keyword = now + timedelta(days=1)
    
    if day_keyword:
        match = re.search(r'(?:a las\s*)?(\d{1,2}:\d{2})', text_normalized)
        if match:
            try:
                hour, minute = map(int, match.group(1).split(':'))
                return day_keyword.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except (ValueError, IndexError):
                return None
        else:
            # Si solo dice 'hoy' o 'mañana' sin hora, asumir hora actual
            return day_keyword.replace(second=0, microsecond=0)

    # Patrón para 'a las HH:MM' (asume hoy)
    match = re.fullmatch(r'a las\s*(\d{1,2}:\d{2})', text_normalized)
    if match:
        try:
            hour, minute = map(int, match.group(1).split(':'))
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, IndexError):
            return None

    # Patrón para HH:MM (asume hoy)
    match = re.fullmatch(r'(\d{1,2}:\d{2})', text_normalized)
    if match:
        try:
            hour, minute = map(int, match.group(1).split(':'))
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, IndexError):
            return None

    return None

if __name__ == "__main__":
    # Script seguro para borrar eventos largos (más de 1 día)
    from datetime import datetime
    import pytz

    print("Buscando y eliminando eventos que duren más de 1 día...")
    service = get_calendar_service()
    if not service:
        print("No se pudo conectar a Google Calendar.")
        exit(1)

    now = datetime.now(pytz.timezone('America/Santiago'))
    time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=time_min,
        maxResults=100,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    count_deleted = 0
    for event in events:
        start = event['start'].get('dateTime')
        end = event['end'].get('dateTime')
        if start and end:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            duration = end_dt - start_dt
            if duration.total_seconds() > 86400:  # Más de 1 día
                print(f"Borrando evento: {event['summary']} ({start} - {end})")
                service.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
                count_deleted += 1
    print(f"Total de eventos eliminados: {count_deleted}") 