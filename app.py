import os
from flask import Flask, request, current_app, Response
from twilio.twiml.messaging_response import MessagingResponse
import logging
import pytz
from datetime import datetime, timedelta
from pymongo import MongoClient, ASCENDING
import pymongo
from bson.objectid import ObjectId
from calendar_utils import create_calendar_event, check_availability, parse_date_only, parse_datetime
import json
import mercadopago
import re
from dotenv import load_dotenv
from utils import get_settings, load_messages, get_active_services, get_service_duration
import dateutil.parser
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Cargar variables de entorno al inicio
load_dotenv()

# Setup MercadoPago SDK
mercadopago_sdk = mercadopago.SDK(os.getenv("MERCADOPAGO_ACCESS_TOKEN"))

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Estructura de mensajes por defecto (fallback)
DEFAULT_MESSAGES = {
    'welcome': "¡Hola! 👋 Soy tu asistente virtual para agendar citas de manicure y pedicure. ¿Qué te gustaría hacer hoy?",
    'service_list_header': "Estos son nuestros servicios disponibles.",
    'service_list_item': "{i}. {emoji} {name}",
    'invalid_service': "Ese número no está en la lista. Por favor, elige una opción válida.",
    'date_prompt': "{emoji} ¡Perfecto! Elegiste {service_name}.\n\n⏰ Nuestro horario es de {start_hour} a {end_hour}.\n\n📅 ¿Cuándo quieres tu cita?\nEscribe el día y la hora. Por ejemplo:\n👉 22/06 a las 14:30\n👉 a las 16:00 (para hoy)\n\nEscribe *agendar* para volver al menú.",
    'invalid_date_format': "🕒 Ups, no entendí la fecha.\nPor favor escribe algo así como:\n👉 22/06 a las 14:30\n👉 hoy a las 16:00",
    'past_date_error': "No puedes agendar en el pasado. Por favor, elige una fecha y hora futura.",
    'future_date_error': "Solo puedes agendar con un máximo de 90 días de anticipación.",
    'unavailable_slot_error': "❌ Lo siento, la hora solicitada ({time}) no está disponible.",
    'next_available_slots_message': "Aquí tienes algunos horarios disponibles para *{service_name}*:\n\n{available_slots}\n\nPor favor, elige una de estas opciones o intenta con otra fecha.",
    'pre_booking_confirmation': "✅ ¡Pre-reserva lista!\n\n{emoji} Servicio: {service}\n📅 Fecha: {date}\n🕖 Hora: {time}\n\n🔔 Responde:\n- PAGAR para confirmar tu cita\n- *agendar* para volver al menú\n- *salir* sin guardar la reserva",
    'booking_payment_prompt': "¡Último paso! Para confirmar tu cita, realiza el pago del abono de ${payment_amount} aquí:\n\n{payment_link}\n\n🔔 Una vez pagado, responde *CONFIRMAR* aquí mismo para finalizar tu reserva.\nTambién puedes escribir:\n\n*agendar* para volver al menú\n*salir* para salir sin guardar la reserva.",
    'payment_link_error': "Lo siento, no pudimos generar el enlace de pago. Por favor, intenta de nuevo más tarde.",
    'booking_cancelled_by_user': "Ok, hemos cancelado la reserva. Escribe 'hola' para empezar de nuevo si lo deseas.",
    'invalid_booking_confirmation_option': "Por favor, responde con 'PAGAR' para confirmar, '*agendar*' para volver al menú o '*salir*' para anular la reserva.",
    'no_pending_appointment_error': "No encontré una cita pendiente de pago para confirmar. Si ya pagaste, contacta al administrador. Si no, empieza de nuevo escribiendo 'hola'.",
    'final_confirmation_success': "✅ ¡Tu cita está confirmada!\n\nServicio: {service}\nFecha: {date}\n\n¡Te esperamos!",
    'calendar_error': "Hubo un problema al crear tu cita en el calendario. Por favor, contacta al administrador para confirmar manualmente.",
    'invalid_final_confirmation_option': "Por favor, responde *CONFIRMAR* para finalizar, *agendar* para volver al menú, o *salir* sin guardar la reserva.",
    'booking_exit_message': "Ok, hemos salido sin guardar la reserva. Escribe 'hola' para empezar de nuevo si lo deseas.",
    'no_appointments_to_cancel': "No tienes citas activas para cancelar.",
    'multiple_appointments_to_cancel': "Tienes varias citas. Por favor, responde con el número de la cita que deseas cancelar:\n\n{appointments_list}",
    'confirm_cancellation_single': "🗓️ Has seleccionado cancelar tu cita para:\n{emoji} {service} — {date} a las {time}\n\n¿Confirmas la cancelación?\nResponde: *sí* para confirmar, o *no* para mantener la cita.",
    'cancellation_aborted': "Ok, tu cita no ha sido cancelada.",
}

def create_app():
    """
    Application factory to create and configure the Flask app.
    This pattern allows each worker to have its own application context.
    """
    app = Flask(__name__)

    # La configuración ahora se maneja directamente con os.getenv(),
    # por lo que app.config.from_object(Config) ya no es necesario.

    # Setup MongoDB Connection
    try:
        mongodb_uri = os.getenv("MONGODB_URI")
        if not mongodb_uri:
            logger.error("MONGODB_URI environment variable not set")
            # Use default messages and settings for now
            app.messages = DEFAULT_MESSAGES
            app.active_services = []
            app.settings = {}
            return app
            
        client = MongoClient(mongodb_uri)
        db = client['peluqueria_bot'] # EXPLICITLY select the database
        app.db = db
        app.clients_collection = db.clients
        app.appointments_collection = db.appointments
        app.blacklist_collection = db.blacklist
        # Load active services dynamically for this app instance
        app.active_services = get_active_services()
        if not app.active_services:
            logger.warning("ALERTA: No se encontraron servicios activos en la base de datos.")
        
        logger.info(f"App instance created. MongoDB connected and {len(app.active_services)} services loaded.")

        # Cargar settings y messages
        app.settings = get_settings()
        if not app.settings:
            app.logger.error("CRITICAL: No se pudo cargar la configuración desde la base de datos. La aplicación podría no funcionar como se espera.")
            # Podrías tener un fallback aquí si es necesario
        
        app.messages = load_messages()
        if not app.messages:
            app.logger.warning("ADVERTENCIA: No se pudieron cargar los mensajes desde la BD. Usando mensajes por defecto.")
            app.messages = DEFAULT_MESSAGES
        
        # --- CIRUGÍA DE PLANTILLAS: Se ejecuta siempre para garantizar el formato correcto ---
        try:
            if not hasattr(app, 'db') or not app.db:
                logger.warning("Skipping template updates - no database connection")
                return app
                
            messages_collection = app.db.messages
            
            # Plantilla para pedir la fecha
            date_prompt_template = "{emoji} ¡Perfecto! Elegiste {service_name}.\n\n⏰ Nuestro horario es de {start_hour} a {end_hour}.\n\n📅 ¿Cuándo quieres tu cita?\nEscribe el día y la hora. Por ejemplo:\n👉 22/06 a las 14:30\n👉 a las 16:00 (para hoy)\n\nEscribe agendar para volver al menú."
            messages_collection.update_one(
                {'key': 'date_prompt'},
                {'$set': {'value': date_prompt_template}},
                upsert=True
            )

            # Plantilla para la pre-reserva
            pre_booking_template = "✅ ¡Pre-reserva lista!\n\n{emoji} Servicio: {service}\n📅 Fecha: {date}\n🕖 Hora: {time}\n\n🔔 Responde:\n- PAGAR para confirmar tu cita\n- *agendar* para volver al menú\n- *salir* sin guardar la reserva"
            messages_collection.update_one(
                {'key': 'pre_booking_confirmation'},
                {'$set': {'value': pre_booking_template}},
                upsert=True
            )
            
            # Plantilla para el menú de servicios
            services_menu_template = "Estos son nuestros servicios disponibles.\n\n1. 💅 Manicure\n2. 👐🦶 Pack Manos + Pies\n3. 👣 Pedicure\n4. 👁️ Pestañas\n\nResponde con el número del servicio que deseas agendar."
            messages_collection.update_one(
                {'key': 'services_menu'},
                {'$set': {'value': services_menu_template}},
                upsert=True
            )
            
            # Plantilla para confirmación final (CUANDO SE PUEDE AGENDAR MÁS)
            final_conf_can_book_template = "✅ ¡Tu cita está confirmada!\n\nServicio: {service}\nFecha: {date}\n\n¡Te esperamos!\n\n🔁 Si deseas agendar otro servicio, escribe *agendar* para volver al menú.\n❌ Si deseas cancelar esta cita, escribe *cancelar*.\n🚪 Si deseas salir, escribe *salir*."
            messages_collection.update_one(
                {'key': 'final_confirmation_can_book_more'},
                {'$set': {'value': final_conf_can_book_template}},
                upsert=True
            )

            # Plantilla para confirmación final (CUANDO NO SE PUEDE AGENDAR MÁS)
            final_conf_no_book_template = "✅ ¡Tu cita está confirmada!\n\nServicio: {service}\nFecha: {date}\n\n¡Te esperamos!\n\n❌ Si deseas cancelar esta cita, escribe *cancelar*.\n🚪 ya no puedes agendar más, escribe *salir* para cerrar la aplicación."
            messages_collection.update_one(
                {'key': 'final_confirmation_no_more_booking'},
                {'$set': {'value': final_conf_no_book_template}},
                upsert=True
            )
            
            # Plantilla de bienvenida con instrucciones claras
            welcome_prompt_template = "¡Hola! 👋\n\nPara ver nuestros servicios y reservar una cita, escribe *agendar*.\n\nSi necesitas cancelar una cita existente, escribe *cancelar*."
            messages_collection.update_one(
                {'key': 'welcome_prompt'},
                {'$set': {'value': welcome_prompt_template}},
                upsert=True
            )
            
            # Plantillas para el flujo de cancelación
            messages_collection.update_one({'key': 'no_appointments_to_cancel'}, {'$set': {'value': 'No tienes citas activas para cancelar.'}}, upsert=True)
            messages_collection.update_one({'key': 'multiple_appointments_to_cancel'}, {'$set': {'value': 'Tienes varias citas. Por favor, responde con el número de la cita que deseas cancelar:\n\n{appointments_list}'}}, upsert=True)
            messages_collection.update_one({'key': 'confirm_cancellation_single'}, {'$set': {'value': 'Has seleccionado cancelar tu cita para *{service}* el día *{date}* a las *{time}*. ¿Estás seguro? Responde *si* o *no*.'}}, upsert=True)
            messages_collection.update_one({'key': 'cancellation_aborted'}, {'$set': {'value': 'Ok, tu cita no ha sido cancelada.'}}, upsert=True)
            
            # Forzar actualización del menú de admin
            settings_collection = app.db.settings
            admin_menu_config = {
                'title': "Hola! Estás en el modo administrador. ¿Qué te gustaría hacer?",
                'options': [
                    {'key': '1', 'text': 'Cancelar citas', 'next_state': 'cancel_appointments_date', 'prompt': '🗓️ Ok, vamos a cancelar citas. ¿Para qué fecha quieres ver las citas a cancelar? (Usa "hoy", "mañana" o DD/MM)'},
                    {'key': '2', 'text': 'Ver bloqueados', 'action': 'show_blocked_users'},
                    {'key': '3', 'text': 'Cambiar horarios', 'next_state': 'update_start_hour', 'prompt': '⏰ Ok, vamos a cambiar el horario. Primero, escribe la nueva hora de APERTURA (ej: 09:00).'},
                    {'key': '4', 'text': 'Ver cancelaciones del día', 'action': 'show_cancellations_today'},
                    {'key': '5', 'text': 'Ver citas del día', 'action': 'show_todays_appointments'},
                    {'key': '6', 'text': 'Bloquear/Desbloquear calendario', 'action': 'toggle_calendar_block'},
                    {'key': '7', 'text': 'Desbloquear usuario', 'next_state': 'unblock_user_number', 'prompt': 'Por favor, escribe el número del usuario a desbloquear (ej: 56912345678).'},
                    {'key': '8', 'text': 'Salir', 'action': 'exit_admin_mode', 'prompt': 'Has salido del modo administrador.'},
                ]
            }
            settings_collection.update_one(
                {'_id': 'global_settings'},
                {'$set': {'admin_main_menu': admin_menu_config}},
                upsert=True
            )

            app.logger.info("Plantillas de mensajes y menú de admin forzados a la versión correcta.")
            # Recargar los mensajes y settings para que la app los use inmediatamente
            app.messages = load_messages()

        except Exception as e:
            app.logger.error(f"Error al forzar la actualización de plantillas: {e}")

    except Exception as e:
        logger.critical(f"Could not connect to MongoDB: {e}", exc_info=True)
        app.db = None
        app.appointments_collection = None
        app.clients_collection = None
        app.active_services = []

    # La gestión de la conexión ahora se maneja por cada función que la necesita,
    # por lo que el teardown global no es estrictamente necesario en este nuevo enfoque.

    return app

# Create the app instance using the factory
app = create_app()

# Google Calendar configuration
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'service_account_credentials.json'
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")

def add_to_calendar(client_name, service_name, date_obj):
    try:
        if not date_obj.tzinfo:
            date_obj = pytz.timezone('America/Santiago').localize(date_obj)

        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        
        event = {
            'summary': f'Cita: {service_name} - {client_name}',
            'description': f'Servicio de {service_name} para {client_name}.',
            'start': {'dateTime': date_obj.isoformat()},
            'end': {'dateTime': (date_obj + timedelta(hours=1)).isoformat()},
        }
        
        created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        logger.info(f'Evento creado: {created_event.get("htmlLink")}')
        return created_event.get('id')
    except Exception as e:
        logger.error(f'Error al crear evento en Google Calendar: {str(e)}', exc_info=True)
        return None

def remove_from_calendar(event_id):
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        logger.info(f"Evento {event_id} eliminado del calendario.")
        return True
    except Exception as e:
        logger.error(f"Error al eliminar evento del calendario: {str(e)}", exc_info=True)
        return False

def create_payment_link(amount, description, appointment_id):
    """Crea un link de pago en Mercado Pago."""
    try:
        logger.info(f"Attempting to create payment link for appointment {appointment_id} with amount {amount}")

        preference_data = {
            "items": [
                {
                    "title": description,
                    "quantity": 1,
                    "currency_id": "CLP",
                    "unit_price": float(amount)
                }
            ],
            "back_urls": {
                "success": "https://www.instagram.com/francisco.cl/",
                "failure": "https://www.instagram.com/francisco.cl/",
                "pending": "https://www.instagram.com/francisco.cl/"
            },
            "auto_return": "approved",
            "external_reference": str(appointment_id),
        }
        
        logger.info(f"Mercado Pago preference data: {json.dumps(preference_data, indent=2)}")
        
        preference_response = mercadopago_sdk.preference().create(preference_data)
        
        logger.info(f"Mercado Pago API response: {json.dumps(preference_response, indent=2)}")

        if preference_response and preference_response.get("status") == 201:
            return preference_response["response"]["init_point"]
        else:
            logger.error(f"Error creating payment link from Mercado Pago API. Full response: {preference_response}")
            return None
            
    except Exception as e:
        logger.error(f"Exception while creating payment link: {str(e)}", exc_info=True)
        return None

def get_dynamic_welcome_message(user_name, user_id, phone_number):
    """Generates a dynamic welcome message including active appointments and available services."""
    appointments_collection = current_app.appointments_collection
    active_services = current_app.active_services
    
    message_parts = [f"✨ ¡Hola, {user_name}!"]
    
    # 1. Show existing confirmed appointments
    user_appointments = list(appointments_collection.find({'client_id': user_id, 'status': 'confirmed'}))
    if user_appointments:
        message_parts.append("\nEstas son tus citas activas:")
        for app in user_appointments:
            service_info = next((s for s in active_services if s['name'] == app['service']), {})
            emoji = service_info.get('emoji', '✅')
            date_str = app['date'].strftime('%d/%m')
            time_str = app['date'].strftime('%H:%M')
            message_parts.append(f"*{emoji} {app['service']}*")
            message_parts.append(f"  📅 {date_str} a las {time_str}")
    
    # 2. Get and show available services (not already booked)
    booked_service_names = {app['service'] for app in user_appointments}
    available_services = [s for s in active_services if s['name'] not in booked_service_names]
    
    if available_services:
        if user_appointments:
            message_parts.append("\n\nPara agendar otro servicio, elige una opción:")
            message_parts.append("\n¡Bienvenido/a! Por favor, elige el servicio que deseas agendar:")
            message_parts.append("\nResponde con el número. O si deseas cancelar una cita, escribe *cancelar*.")
            message_parts.append("\nSi deseas cancelar alguna, escribe: *cancelar*")
            message_parts.append("\nPor el momento no hay servicios disponibles para agendar.")
        else:
            message_parts.append("\n¡Bienvenido/a! Por favor, elige el servicio que deseas agendar:")
        
        message_parts.append("") # for a newline
        for i, service in enumerate(available_services, 1):
            emoji = service.get('emoji', '✅')
            message_parts.append(f"*{i}. {emoji} {service['name']}*")
        
        if user_appointments:
            message_parts.append("\nResponde con el número. O si deseas cancelar una cita, escribe *cancelar*.")
        else:
            message_parts.append("\nResponde con el número.")
    else:
        if user_appointments:
            message_parts.append("\n\n⚠️ Ya tienes citas para todos nuestros servicios disponibles.")
            message_parts.append("Si deseas cancelar alguna, escribe: *cancelar*")
        else:
            message_parts.append("\nPor el momento no hay servicios disponibles para agendar.")

    return "\n".join(message_parts)

def send_goodbye_message(resp, user_id):
    """Envía un mensaje de despedida y resetea el contador de intentos."""
    goodbye_message = """👋 ¡Gracias por visitarnos!

Esperamos verte pronto en la peluquería.

¡Que tengas un excelente día! ✂️💇‍♀️"""
    resp.message(goodbye_message)
    current_app.clients_collection.update_one({'_id': user_id}, {'$set': {'invalid_attempts': 0}})

# ============================================================================
# CLIENT FLOW HANDLER FUNCTIONS
# ============================================================================

def format_confirmed_appointments(user_appointments, active_services, santiago_tz):
    if not user_appointments:
        return "(No tienes citas confirmadas)"
    
    def get_appointment_date(app):
        """Extrae la fecha de una cita, manejando tanto strings ISO como datetime"""
        date_value = app['date']
        santiago_tz = pytz.timezone('America/Santiago')
        
        if isinstance(date_value, str):
            # Es un string ISO, parsearlo
            import dateutil.parser
            parsed_date = dateutil.parser.isoparse(date_value)
        else:
            # Es un datetime
            parsed_date = date_value
        
        # Asegurar que tenga zona horaria
        if parsed_date.tzinfo is None:
            parsed_date = santiago_tz.localize(parsed_date)
        
        return parsed_date
    
    lines = []
    # Ordenar por fecha, manejando ambos tipos de datos
    sorted_appointments = sorted(user_appointments, key=get_appointment_date)
    
    for app in sorted_appointments:
        service_info = next((s for s in active_services if s['name'] == app['service']), {})
        emoji = service_info.get('emoji', '✅')
        
        # Obtener la fecha parseada
        app_date = get_appointment_date(app)
        
        # Convertir a hora local de Santiago
        if app_date.tzinfo is None:
            local_time = santiago_tz.localize(app_date)
        else:
            local_time = app_date.astimezone(santiago_tz)
        
        # Calcular hora de fin usando la duración del servicio
        duration_minutes = get_service_duration(app['service'])
        end_time = local_time + timedelta(minutes=duration_minutes)
        
        date_str = f"{local_time.strftime('%d/%m a las %H:%M')}-{end_time.strftime('%H:%M')}"
        lines.append(f"{emoji} {app['service']} — {date_str}")
    
    return "\n".join(lines)

def format_services_menu(available_services):
    if not available_services:
        return (
            "✅ ¡Felicitaciones! Ya tienes agendados todos nuestros servicios.\n\n"
            "❌ Escribe cancelar para anular una cita.\n"
            "🚪 Escribe salir para finalizar."
        )
    lines = ["\nPor favor, elige el servicio que deseas agendar:\n"]
    
    # Agregar servicios disponibles
    for i, service in enumerate(available_services, 1):
        emoji = service.get('emoji', '✅')
        lines.append(f"{i}. {emoji} {service['name']}")
    
    # Agregar opciones de navegación
    lines.append("")
    lines.append("❌ Escribe *cancelar* para anular una cita.")
    lines.append("🚪 Escribe *salir* para finalizar.")
    
    return "\n".join(lines)

def handle_initial_state(resp, user):
    appointments_collection = current_app.appointments_collection
    active_services = current_app.active_services
    santiago_tz = pytz.timezone('America/Santiago')
    
    # Verificar si el calendario está bloqueado
    settings = get_settings()
    calendar_blocked = settings.get('calendar_blocked', False)
    
    if calendar_blocked:
        resp.message("🔒 **CALENDARIO CERRADO**\n\nLo sentimos, hoy no estamos tomando nuevas citas.\n\n📅 **Estado:** Temporalmente cerrado\n⏰ **Reapertura:** Próximamente\n\nPara cancelar citas existentes, escribe: *cancelar*")
        return

    user_appointments = list(appointments_collection.find({
        'client_id': user['_id'],
        'status': 'confirmed'
    }))
    booked_service_names = {app['service'] for app in user_appointments}
    available_services_to_book = [s for s in active_services if s['name'] not in booked_service_names]

    message = (
        f"✨ ¡Hola, {user.get('name', 'Usuario')}!\n"
        "🎉 ¡Bienvenida! Estas son tus citas confirmadas:\n\n"
        f"{format_confirmed_appointments(user_appointments, active_services, santiago_tz)}\n\n"
        f"{format_services_menu(available_services_to_book)}"
    )

    current_app.clients_collection.update_one(
        {'_id': user['_id']},
        {'$set': {'last_shown_services': [s['name'] for s in available_services_to_book], 'state': 'awaiting_service_choice'}}
    )
    resp.message(message)

def handle_service_selection(resp, user, incoming_msg):
    """Maneja la selección de servicio del cliente, evitando duplicados."""
    clients_collection = current_app.clients_collection
    messages = current_app.messages
    settings = current_app.settings
    
    last_shown_services = user.get('last_shown_services', [])

    if not incoming_msg.isdigit():
        # Incrementar contador de intentos incorrectos
        invalid_attempts = user.get('invalid_command_attempts', 0) + 1
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'invalid_command_attempts': invalid_attempts}}
        )
        
        # Verificar si debe mostrar advertencia o bloquear
        if invalid_attempts >= 6:
            # Bloquear usuario
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'is_blocked': True}}
            )
            resp.message("Tu cuenta ha sido bloqueada por spam. Por favor, contacta al administrador.")
            return
        elif invalid_attempts == 5:
            # Mostrar advertencia
            resp.message("⚠️ ADVERTENCIA: Has escrito comandos incorrectos 5 veces. Una vez más y serás bloqueado por spam.")
            return
        else:
            # Mensaje normal
            resp.message("Por favor, responde con el número del servicio que deseas.")
            return

    try:
        choice = int(incoming_msg)
        if 1 <= choice <= len(last_shown_services):
            selected_service_name = last_shown_services[choice - 1]
            active_services = current_app.active_services
            selected_service = next((s for s in active_services if s['name'] == selected_service_name), None)
            if not selected_service:
                resp.message("Hubo un error al seleccionar el servicio. Intenta de nuevo.")
                return
            service_name = selected_service['name']
            emoji = selected_service.get('emoji', '✅')
            business_hours = settings.get('business_hours', {'start': '09:00', 'end': '19:00'})
            clients_collection.update_one(
                {'_id': user['_id']},
                {
                    '$set': {'state': 'awaiting_date', 'service_pending': service_name},
                    '$unset': {'last_shown_services': ''}
                }
            )
            resp.message(messages.get('date_prompt').format(
                emoji=emoji,
                service_name=service_name,
                start_hour=business_hours['start'],
                end_hour=business_hours['end']
            ))
            return
        resp.message(messages.get('invalid_service'))
    except (ValueError, IndexError):
        resp.message(messages.get('invalid_service'))

def handle_date_selection(resp, user, incoming_msg):
    """Maneja la selección de fecha y hora del cliente."""
    clients_collection = current_app.clients_collection
    settings = current_app.settings
    messages = current_app.messages
    
    service_pending = user.get('service_pending')
    if not service_pending:
        resp.message("Hubo un error, no hay un servicio pendiente. Por favor, empieza de nuevo.")
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}})
        return

    parsed_date = parse_datetime(incoming_msg)
    if not parsed_date:
        # Incrementar contador de intentos incorrectos
        invalid_attempts = user.get('invalid_command_attempts', 0) + 1
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'invalid_command_attempts': invalid_attempts}}
        )
        
        # Verificar si debe mostrar advertencia o bloquear
        if invalid_attempts >= 6:
            # Bloquear usuario
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'is_blocked': True}}
            )
            resp.message("Tu cuenta ha sido bloqueada por spam. Por favor, contacta al administrador.")
            return
        elif invalid_attempts == 5:
            # Mostrar advertencia
            resp.message("⚠️ ADVERTENCIA: Has escrito comandos incorrectos 5 veces. Una vez más y serás bloqueado por spam.")
            return
        else:
            # Mensaje normal
            resp.message(messages.get('invalid_date_format'))
            return

    santiago_tz = pytz.timezone('America/Santiago')
    # Refuerzo: asegurar que la fecha siempre tenga zona horaria America/Santiago
    if parsed_date.tzinfo is None:
        parsed_date = santiago_tz.localize(parsed_date)
    else:
        parsed_date = parsed_date.astimezone(santiago_tz)
    # Fin refuerzo
    
    if parsed_date < datetime.now(santiago_tz):
        resp.message("No puedes agendar una cita en el pasado.")
        return
    
    if (parsed_date - datetime.now(santiago_tz)).days > 90:
        resp.message("Solo puedes agendar con hasta 90 días de anticipación.")
        return

    is_available, message = check_availability(parsed_date, service_pending)
    
    if not is_available:
        local_time_for_error_msg = parsed_date.strftime('%H:%M')
        error_message_template = messages.get('unavailable_slot_error', "❌ Lo siento, la hora solicitada ({time}) no está disponible.")
        full_error_message = f"{message}\n\n{error_message_template.format(time=local_time_for_error_msg)}"
        resp.message(full_error_message)
        return

    clients_collection.update_one(
        {'_id': user['_id']},
        # Refuerzo: guardar siempre como string ISO con zona horaria
        {'$set': {'state': 'awaiting_confirmation', 'pending_date': parsed_date.isoformat()}}
    )
    
    active_services = current_app.active_services
    service_info = next((s for s in active_services if s['name'] == service_pending), {})
    service_emoji = service_info.get('emoji', '✅')

    date_str = parsed_date.strftime('%d/%m')
    time_str = parsed_date.strftime('%H:%M')

    confirmation_message = messages.get('pre_booking_confirmation').format(
        emoji=service_emoji,
        service=service_pending,
        date=date_str,
        time=time_str
    )
    resp.message(confirmation_message)

def handle_booking_confirmation(resp, user, incoming_msg):
    """Maneja la confirmación de la reserva y el envío del enlace de pago."""
    clients_collection = current_app.clients_collection
    appointments_collection = current_app.appointments_collection
    messages = current_app.messages
    
    if 'pagar' in incoming_msg:
        service_name = user.get('service_pending')
        pending_date = user.get('pending_date')
        
        if not service_name or not pending_date:
            resp.message("Ha ocurrido un error, no hay suficiente información para confirmar. Por favor, empieza de nuevo.")
            clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'service_pending': '', 'pending_date': ''}})
            return

        # Parsear la fecha desde el string ISO para recuperar tzinfo
        if isinstance(pending_date, str):
            # Es un string ISO, parsearlo
            parsed_pending_date = dateutil.parser.isoparse(pending_date)
            pending_date = parsed_pending_date
        # Refuerzo: asegurar que pending_date tenga tzinfo de Santiago antes de guardar/agendar
        santiago_tz = pytz.timezone('America/Santiago')
        if pending_date.tzinfo is None:
            pending_date = santiago_tz.localize(pending_date)
        else:
            pending_date = pending_date.astimezone(santiago_tz)
        # Fin refuerzo

        appointment_id = ObjectId()
        new_appointment = {
            '_id': appointment_id, 'client_id': user['_id'], 'service': service_name,
            'date': pending_date.isoformat(), 'status': 'pending_payment', 'created_at': datetime.now(pytz.utc)
        }
        
        appointments_collection.insert_one(new_appointment)

        settings = get_settings()
        service_details = next((s for s in settings.get('services', []) if s['name'] == service_name), None)
        payment_amount = service_details.get('payment_amount', 2000) if service_details else 2000

        payment_link = create_payment_link(payment_amount, f"Abono para {service_name}", str(appointment_id))

        if payment_link:
            message = messages.get('booking_payment_prompt').format(
                payment_amount=payment_amount,
                payment_link=payment_link
            )
            resp.message(message)
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'state': 'awaiting_final_confirmation'}, '$unset': {'pending_date': ''}}
            )
            return
        # Mensaje de transferencia bancaria en lugar del error de Mercado Pago
        transfer_message = f"""💳 *Información de Pago*

💰 Monto a transferir: ${payment_amount:,} CLP

🏦 *Datos de la cuenta corriente:*
📋 Banco: Banco de Chile
📋 Tipo: Cuenta Corriente
📋 Número: 12345678
📋 RUT: 12.345.678-9
📋 Nombre: Peluquería Ejemplo Ltda.
📋 Email: peluqueria@ejemplo.cl

📝 *Instrucciones:*
1. Realiza la transferencia con el monto exacto
2. En el asunto escribe: "{service_name} - {user['name']}"
3. Envía el comprobante por WhatsApp
4. Responde *CONFIRMAR* cuando hayas pagado

⚠️ *Importante:* Tu cita quedará pendiente hasta confirmar el pago.

---
También puedes escribir:
*agendar* para volver al menú.
*salir* para cancelar esta reserva."""
        resp.message(transfer_message)
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'state': 'awaiting_final_confirmation'}, '$unset': {'pending_date': ''}}
        )
        return

    elif 'agendar' in incoming_msg:
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'service_pending': '', 'pending_date': '', 'cancellation_pending_id': '', 'cancellation_options': ''}})
        handle_initial_state(resp, user)
        return

    elif 'salir' in incoming_msg:
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'service_pending': '', 'pending_date': '', 'cancellation_pending_id': '', 'cancellation_options': ''}})
        resp.message(messages.get('booking_cancelled_by_user'))
        return

    else:
        # Incrementar contador de intentos incorrectos
        invalid_attempts = user.get('invalid_command_attempts', 0) + 1
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'invalid_command_attempts': invalid_attempts}}
        )
        
        # Verificar si debe mostrar advertencia o bloquear
        if invalid_attempts >= 6:
            # Bloquear usuario
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'is_blocked': True}}
            )
            resp.message("Tu cuenta ha sido bloqueada por spam. Por favor, contacta al administrador.")
            return
        elif invalid_attempts == 5:
            # Mostrar advertencia
            resp.message("⚠️ ADVERTENCIA: Has escrito comandos incorrectos 5 veces. Una vez más y serás bloqueado por spam.")
            return
        else:
            # Mensaje normal
            resp.message(messages.get('invalid_booking_confirmation_option'))
            return

def handle_final_confirmation(resp, user, incoming_msg):
    """Maneja la confirmación final post-pago, creando el evento en el calendario."""
    clients_collection = current_app.clients_collection
    appointments_collection = current_app.appointments_collection
    messages = current_app.messages
    
    appointment_to_process = appointments_collection.find_one({
        'client_id': user['_id'],
        'status': 'pending_payment'
    }, sort=[('created_at', -1)])

    if 'confirmar' in incoming_msg:
        if not appointment_to_process:
            resp.message(messages.get('no_pending_appointment_error'))
            return

        # Parsear la fecha desde el string ISO para recuperar tzinfo
        if isinstance(appointment_to_process['date'], str):
            # Es un string ISO, parsearlo
            parsed_date = dateutil.parser.isoparse(appointment_to_process['date'])
        else:
            # Es un datetime, usarlo directamente
            parsed_date = appointment_to_process['date']
        # Refuerzo: asegurar que la fecha tenga zona horaria America/Santiago
        santiago_tz = pytz.timezone('America/Santiago')
        if parsed_date.tzinfo is None:
            parsed_date = santiago_tz.localize(parsed_date)
        else:
            parsed_date = parsed_date.astimezone(santiago_tz)
        # Fin refuerzo

        # Crear evento en Google Calendar
        logger.info(f"[APP] Iniciando creación de evento en Google Calendar para cita {appointment_to_process['_id']}")
        logger.info(f"[APP] Datos de la cita: servicio={appointment_to_process['service']}, cliente={user['name']}, fecha={parsed_date}")
        
        event = create_calendar_event(
            service_type=appointment_to_process['service'],
            client_name=user['name'],
            phone_number=user['phone_number'],
            date_time_santiago=parsed_date
        )

        if event and event.get('id'):
            logger.info(f"[APP] ✅ Evento creado exitosamente en Google Calendar. ID: {event.get('id')}")
            appointments_collection.update_one(
                {'_id': appointment_to_process['_id']},
                {'$set': {'status': 'confirmed', 'calendar_event_id': event.get('id')}}
            )
            logger.info(f"[APP] Cita actualizada en base de datos con calendar_event_id: {event.get('id')}")
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'state': 'initial'}, '$unset': {'service_pending': ''}}
            )
            # Conversión robusta de UTC a Santiago SOLO SI ES UTC
            santiago_tz = pytz.timezone('America/Santiago')
            appt_date_raw = appointment_to_process['date']
            
            # Parsear la fecha desde string ISO para recuperar la hora exacta
            if isinstance(appt_date_raw, str):
                # Es un string ISO, parsearlo
                appt_date = dateutil.parser.isoparse(appt_date_raw)
            else:
                # Es un datetime, usarlo directamente
                appt_date = appt_date_raw
            
            if appt_date.tzinfo is not None and hasattr(appt_date.tzinfo, 'zone') and appt_date.tzinfo.zone == 'UTC':
                local_time = appt_date.astimezone(santiago_tz)
            else:
                local_time = appt_date
            confirmation_date_time_str = local_time.strftime('%d/%m a las %H:%M')
            
            total_services_count = len(current_app.active_services)
            user_confirmed_appointments_count = appointments_collection.count_documents({
                'client_id': user['_id'],
                'status': 'confirmed'
            })
            if user_confirmed_appointments_count >= total_services_count:
                message_key = 'final_confirmation_no_more_booking'
            else:
                message_key = 'final_confirmation_can_book_more'
            resp.message(messages.get(message_key).format(
                service=appointment_to_process['service'],
                date=confirmation_date_time_str
            ))
        else:
            resp.message(messages.get('calendar_error'))

    elif 'agendar' in incoming_msg:
        if appointment_to_process:
            appointments_collection.delete_one({'_id': appointment_to_process['_id']})
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'service_pending': ''}})
        handle_initial_state(resp, user)

    elif 'salir' in incoming_msg:
        if appointment_to_process:
            appointments_collection.delete_one({'_id': appointment_to_process['_id']})
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'service_pending': ''}})
        resp.message(messages.get('booking_exit_message'))
    else:
        # Incrementar contador de intentos incorrectos
        invalid_attempts = user.get('invalid_command_attempts', 0) + 1
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'invalid_command_attempts': invalid_attempts}}
        )
        
        # Verificar si debe mostrar advertencia o bloquear
        if invalid_attempts >= 6:
            # Bloquear usuario
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'is_blocked': True}}
            )
            resp.message("Tu cuenta ha sido bloqueada por spam. Por favor, contacta al administrador.")
            return
        elif invalid_attempts == 5:
            # Mostrar advertencia
            resp.message("⚠️ ADVERTENCIA: Has escrito comandos incorrectos 5 veces. Una vez más y serás bloqueado por spam.")
            return
        else:
            # Mensaje normal
            resp.message(messages.get('invalid_final_confirmation_option'))
            return

def handle_cancellation_start(resp, user):
    """Inicia el flujo de cancelación de citas para un cliente."""
    appointments_collection = current_app.appointments_collection
    clients_collection = current_app.clients_collection
    messages = current_app.messages

    user_appointments = list(appointments_collection.find({
        'client_id': user['_id'],
        'status': 'confirmed'
    }).sort('date', 1))

    if not user_appointments:
        resp.message(messages.get('no_appointments_to_cancel'))
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}})
        return

    if len(user_appointments) == 1:
        appointment = user_appointments[0]
        fecha = appointment['date']
        if isinstance(fecha, str):
            import dateutil.parser
            fecha = dateutil.parser.isoparse(fecha)
        local_time = fecha.astimezone(pytz.timezone('America/Santiago'))
        
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {
                'state': 'awaiting_cancellation_confirmation',
                'cancellation_pending_id': str(appointment['_id'])
            }}
        )
        resp.message(messages.get('confirm_cancellation_single').format(
            emoji=appointment['service'],
            service=appointment['service'],
            date=local_time.strftime('%d/%m'),
            time=local_time.strftime('%H:%M')
        ))
    else:
        # Formato bonito para mostrar citas activas con emoji y separador —
        santiago_tz = pytz.timezone('America/Santiago')
        appointment_lines = []
        active_services = current_app.active_services
        for i, appt in enumerate(user_appointments, 1):
            service_info = next((s for s in active_services if s['name'] == appt['service']), {})
            emoji = service_info.get('emoji', '✅')
            
            # Verificar si la fecha es string y convertirla si es necesario
            fecha = appt['date']
            if isinstance(fecha, str):
                import dateutil.parser
                fecha = dateutil.parser.isoparse(fecha)
            
            local_time = fecha.astimezone(santiago_tz)
            # Calcular hora de fin usando la duración del servicio
            duration_minutes = get_service_duration(appt['service'])
            end_time = local_time + timedelta(minutes=duration_minutes)
            date_str = f"{local_time.strftime('%d/%m a las %H:%M')}-{end_time.strftime('%H:%M')}"
            appointment_lines.append(f"{emoji} {appt['service']} — {date_str}")
        message = "📅 Estas son tus citas activas:\n\n" + "\n".join(appointment_lines)
        message += "\n\n❓¿Cuál deseas cancelar?\n✍️ Responde con el número de la cita (1, 2, 3 o 4) para continuar\n🚪 O escribe '*salir*' para volver al menú principal"
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {
                'state': 'awaiting_cancellation_choice',
                'cancellation_options': [str(a['_id']) for a in user_appointments]
            }}
        )
        resp.message(message)

def handle_cancellation_choice(resp, user, incoming_msg):
    """Maneja la selección del usuario cuando tiene múltiples citas para cancelar."""
    clients_collection = current_app.clients_collection
    appointments_collection = current_app.appointments_collection
    messages = current_app.messages
    
    # Manejar la opción "salir"
    if incoming_msg.lower() == 'salir':
        clients_collection.update_one(
            {'_id': user['_id']}, 
            {'$set': {'state': 'initial'}, '$unset': {'cancellation_options': ''}}
        )
        resp.message("Ok, has salido del menú de cancelación. Escribe 'hola' para volver al menú principal.")
        return
    
    cancellation_options = user.get('cancellation_options', [])
    if not incoming_msg.isdigit() or not (1 <= int(incoming_msg) <= len(cancellation_options)):
        # Incrementar contador de intentos incorrectos
        invalid_attempts = user.get('invalid_command_attempts', 0) + 1
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'invalid_command_attempts': invalid_attempts}}
        )
        
        # Verificar si debe mostrar advertencia o bloquear
        if invalid_attempts >= 6:
            # Bloquear usuario
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'is_blocked': True}}
            )
            resp.message("Tu cuenta ha sido bloqueada por spam. Por favor, contacta al administrador.")
            return
        elif invalid_attempts == 5:
            # Mostrar advertencia
            resp.message("⚠️ ADVERTENCIA: Has escrito comandos incorrectos 5 veces. Una vez más y serás bloqueado por spam.")
            return
        else:
            # Mensaje normal
            resp.message("Por favor, responde con un número válido de la lista o escribe '*salir*' para volver al menú principal.")
            return

    choice_index = int(incoming_msg) - 1
    appointment_id_to_cancel = cancellation_options[choice_index]

    appointment = appointments_collection.find_one({'_id': ObjectId(appointment_id_to_cancel)})
    
    if not appointment:
        resp.message("Lo siento, no pudimos encontrar esa cita. Por favor, intenta de nuevo.")
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}})
        return
        
    # Verificar si la fecha es string y convertirla si es necesario
    fecha = appointment['date']
    if isinstance(fecha, str):
        import dateutil.parser
        fecha = dateutil.parser.isoparse(fecha)
    
    local_time = fecha.astimezone(pytz.timezone('America/Santiago'))
    
    clients_collection.update_one(
        {'_id': user['_id']},
        {'$set': {
            'state': 'awaiting_cancellation_confirmation',
            'cancellation_pending_id': str(appointment['_id'])
        }, '$unset': {'cancellation_options': ''}}
    )
    
    resp.message(messages.get('confirm_cancellation_single').format(
        emoji=appointment['service'],
        service=appointment['service'],
        date=local_time.strftime('%d/%m'),
        time=local_time.strftime('%H:%M')
    ))

def handle_cancellation_confirmation(resp, user, incoming_msg):
    """Confirma o aborta la cancelación final de la cita de forma segura."""
    clients_collection = current_app.clients_collection
    appointments_collection = current_app.appointments_collection
    messages = current_app.messages

    appointment_id_str = user.get('cancellation_pending_id')
    
    def reset_state():
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'cancellation_pending_id': ''}})

    if not appointment_id_str:
        resp.message("Hubo un error, no hay una cancelación pendiente. Por favor, empieza de nuevo.")
        reset_state()
        return
        
    appointment = appointments_collection.find_one({'_id': ObjectId(appointment_id_str)})
    
    if incoming_msg == 'si':
        if not appointment:
            resp.message("Error: No se pudo encontrar la cita a cancelar. Ya podría haber sido cancelada.")
            reset_state()
            return

        event_id = appointment.get('calendar_event_id')
        if not event_id:
            msg = f"Error CRÍTICO: No se encontró la referencia al evento en Google Calendar para tu cita de *{appointment['service']}*. Por favor, contacta al administrador para cancelarla manualmente. Tu cita NO ha sido cancelada en el sistema."
            resp.message(msg)
            reset_state()
            return

        if remove_from_calendar(event_id):
            # Borrado lógico: marcar como cancelada y guardar fecha
            appointments_collection.update_one(
                {'_id': appointment['_id']},
                {'$set': {'status': 'cancelled', 'cancelled_at': datetime.now(pytz.timezone('America/Santiago'))}}
            )
            handle_cancellation(user['_id'], appointment['service']) # Lógica de Blacklist
            resp.message(f"✅ Tu cita para {appointment['service']} ha sido cancelada correctamente.\nEscribe *agendar* para reservar otra cita o *salir* para finalizar.")
        else:
            resp.message(f"Hubo un error al intentar borrar tu cita de *{appointment['service']}* del calendario. Por favor, contacta al administrador. Tu cita NO ha sido cancelada.")
        reset_state()
        return

    elif incoming_msg == 'no':
        resp.message(messages.get('cancellation_aborted'))
    else:
        # Incrementar contador de intentos incorrectos
        invalid_attempts = user.get('invalid_command_attempts', 0) + 1
        clients_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'invalid_command_attempts': invalid_attempts}}
        )
        
        # Verificar si debe mostrar advertencia o bloquear
        if invalid_attempts >= 6:
            # Bloquear usuario
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'is_blocked': True}}
            )
            resp.message("Tu cuenta ha sido bloqueada por spam. Por favor, contacta al administrador.")
            return
        elif invalid_attempts == 5:
            # Mostrar advertencia
            resp.message("⚠️ ADVERTENCIA: Has escrito comandos incorrectos 5 veces. Una vez más y serás bloqueado por spam.")
            return
        else:
            # Formato personalizado para la confirmación de cancelación
            santiago_tz = pytz.timezone('America/Santiago')
            active_services = current_app.active_services
            service_info = next((s for s in active_services if s['name'] == appointment['service']), {})
            emoji = service_info.get('emoji', '✅')
            
            # Verificar si la fecha es string y convertirla si es necesario
            fecha = appointment['date']
            if isinstance(fecha, str):
                import dateutil.parser
                fecha = dateutil.parser.isoparse(fecha)
            
            local_time = fecha.astimezone(santiago_tz)
            # Calcular hora de fin usando la duración del servicio
            duration_minutes = get_service_duration(appointment['service'])
            end_time = local_time + timedelta(minutes=duration_minutes)
            date_str = f"{local_time.strftime('%d/%m a las %H:%M')}-{end_time.strftime('%H:%M')}"
            message = f"❌ Has seleccionado cancelar tu cita:\n{emoji} {appointment['service']} — {date_str}\n\n❓¿Estás seguro/a de que deseas cancelarla?\n✍️ Responde con sí para confirmar o no para mantener tu cita"
            resp.message(message)
            return # No reseteamos el estado, esperamos una respuesta válida

    reset_state()

def handle_client_flow(resp, user, incoming_msg):
    """Gestiona el flujo de conversación para un cliente."""
    clients_collection = current_app.clients_collection

    # --- COMANDOS GLOBALES ---
    # Estos comandos interrumpen cualquier estado y comienzan su propio flujo.
    if incoming_msg in ['hola', 'menu', 'inicio']:
        # Resetear contador de intentos incorrectos
        clients_collection.update_one(
            {'_id': user['_id']}, 
            {'$set': {'state': 'initial'}, '$unset': {'service_pending': '', 'pending_date': '', 'cancellation_pending_id': '', 'cancellation_options': '', 'invalid_command_attempts': ''}}
        )
        handle_initial_state(resp, user)
        return

    if incoming_msg == 'agendar':
        # Resetear contador de intentos incorrectos
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'service_pending': '', 'pending_date': '', 'cancellation_pending_id': '', 'cancellation_options': '', 'invalid_command_attempts': ''}})
        handle_initial_state(resp, user)
        return

    if incoming_msg == 'cancelar':
        # Resetear contador de intentos incorrectos
        clients_collection.update_one({'_id': user['_id']}, {'$unset': {'invalid_command_attempts': ''}})
        handle_cancellation_start(resp, user)
        return

    if incoming_msg == 'salir':
        # Resetear contador de intentos incorrectos
        clients_collection.update_one({'_id': user['_id']}, {'$set': {'state': 'initial'}, '$unset': {'service_pending': '', 'pending_date': '', 'cancellation_pending_id': '', 'cancellation_options': '', 'invalid_command_attempts': ''}})
        send_goodbye_message(resp, user['_id'])
        return

    # --- LÓGICA BASADA EN ESTADOS ---
    current_state = user.get('state', 'initial')
    try:
        if current_state == 'initial':
            # Si el usuario está en el estado inicial y escribe algo incorrecto, responde con mensaje de error
            # Incrementar contador de intentos incorrectos
            invalid_attempts = user.get('invalid_command_attempts', 0) + 1
            clients_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'invalid_command_attempts': invalid_attempts}}
            )
            
            # Verificar si debe mostrar advertencia o bloquear
            if invalid_attempts >= 6:
                # Bloquear usuario
                clients_collection.update_one(
                    {'_id': user['_id']},
                    {'$set': {'is_blocked': True}}
                )
                resp.message("Tu cuenta ha sido bloqueada por spam. Por favor, contacta al administrador.")
                return
            elif invalid_attempts == 5:
                # Mostrar advertencia
                resp.message("⚠️ ADVERTENCIA: Has escrito comandos incorrectos 5 veces. Una vez más y serás bloqueado por spam.")
                return
            else:
                # Mensaje normal
                resp.message('No entendí lo que dices. 😊\n\nPuedes volver a intentar escribiendo *agendar* o *cancelar*.')
                return

        elif current_state == 'awaiting_service_choice':
            # Resetear contador si escribe un comando correcto
            if incoming_msg.isdigit():
                clients_collection.update_one({'_id': user['_id']}, {'$unset': {'invalid_command_attempts': ''}})
            handle_service_selection(resp, user, incoming_msg)
        
        elif current_state == 'awaiting_date':
            # Resetear contador si escribe una fecha válida
            if parse_datetime(incoming_msg):
                clients_collection.update_one({'_id': user['_id']}, {'$unset': {'invalid_command_attempts': ''}})
            handle_date_selection(resp, user, incoming_msg)

        elif current_state == 'awaiting_confirmation':
            # Resetear contador si escribe un comando correcto
            if incoming_msg in ['pagar', 'agendar', 'salir']:
                clients_collection.update_one({'_id': user['_id']}, {'$unset': {'invalid_command_attempts': ''}})
            handle_booking_confirmation(resp, user, incoming_msg)
        
        elif current_state == 'awaiting_final_confirmation':
            # Resetear contador si escribe un comando correcto
            if incoming_msg in ['confirmar', 'agendar', 'salir']:
                clients_collection.update_one({'_id': user['_id']}, {'$unset': {'invalid_command_attempts': ''}})
            handle_final_confirmation(resp, user, incoming_msg)
        
        elif current_state == 'awaiting_cancellation_choice':
            # Resetear contador si escribe un comando correcto
            if incoming_msg.isdigit() or incoming_msg == 'salir':
                clients_collection.update_one({'_id': user['_id']}, {'$unset': {'invalid_command_attempts': ''}})
            handle_cancellation_choice(resp, user, incoming_msg)
            
        elif current_state == 'awaiting_cancellation_confirmation':
            # Resetear contador si escribe un comando correcto
            if incoming_msg in ['si', 'no']:
                clients_collection.update_one({'_id': user['_id']}, {'$unset': {'invalid_command_attempts': ''}})
            handle_cancellation_confirmation(resp, user, incoming_msg)

    except Exception as e:
        logger.error(f"Error CRÍTICO en handle_client_flow: {e}", exc_info=True)
        resp.message("Lo siento, ocurrió un error inesperado. Por favor, intenta de nuevo.")

@app.route('/webhook-whatsapp', methods=['POST'])
def whatsapp_dispatcher():
    resp = MessagingResponse()
    incoming_msg = request.values.get('Body', '').strip().lower()
    phone_number = request.values.get('From', '')

    logger.info(f"--- INCOMING --- From: {phone_number}, Msg: '{incoming_msg}'")

    if current_app.db is None:
        logger.error("No DB connection. Aborting.")
        resp.message("El servicio no está disponible. Intenta más tarde.")
        return str(resp)

    # --- LÓGICA DE DISTRIBUCIÓN (DISPATCHER) ---
    settings = get_settings()
    admin_numbers = settings.get('admin_numbers', [])
    
    # Comprobar si el usuario es un administrador
    if phone_number in admin_numbers:
        # Revisar el estado actual del admin
        admin_collection = current_app.db.admins
        admin_state_doc = admin_collection.find_one({'phone_number': phone_number})
        admin_state = admin_state_doc.get('state', 'initial') if admin_state_doc else 'initial'
        # handle_admin_flow devuelve True si ha gestionado el mensaje.
        is_handled_by_admin_flow = handle_admin_flow(resp, phone_number, incoming_msg)
        if is_handled_by_admin_flow:
            logger.info(f"--- ADMIN OUTGOING --- To: {phone_number}, Response:\n{str(resp)}")
            return str(resp)
        # Solo permitir flujo de cliente si el admin está en estado 'initial'
        if admin_state != 'initial':
            logger.info(f"--- ADMIN IN ADMIN MODE, SKIPPING CLIENT FLOW --- To: {phone_number}")
            return str(resp)
    
    # --- FLUJO DE CLIENTE (Se ejecuta si no es admin, o si el admin no usó un comando de admin) ---
    clients_collection = current_app.clients_collection
    user = clients_collection.find_one({'phone_number': phone_number})
    
    if not user:
        user_name = request.values.get('ProfileName', 'Nuevo Usuario')
        user = {
            '_id': ObjectId(), 'phone_number': phone_number, 'name': user_name,
            'state': 'initial', 'created_at': datetime.now(pytz.utc)
        }
        clients_collection.insert_one(user)
        logger.info(f"Nuevo usuario creado: {user_name} ({phone_number})")
    
    # Recargar el usuario por si acaso fue recién creado
    user = clients_collection.find_one({'phone_number': phone_number})

    if user.get('is_blocked'):
        if user.get('block_message_sent'):
            # No responder nada si ya se envió el mensaje de bloqueo
            logger.info(f"Usuario bloqueado {phone_number} intentó enviar mensaje: '{incoming_msg}' (mensaje de bloqueo ya enviado)")
            return ''
        else:
            # Enviar mensaje de bloqueo solo una vez
            resp.message("Tu cuenta ha sido bloqueada. Por favor, contacta al administrador.")
            clients_collection.update_one({'_id': user['_id']}, {'$set': {'block_message_sent': True}})
            logger.info(f"Usuario bloqueado {phone_number} intentó enviar mensaje: '{incoming_msg}' (mensaje de bloqueo enviado)")
            return str(resp)
    else:
        handle_client_flow(resp, user, incoming_msg)
    
    logger.info(f"--- OUTGOING --- To: {phone_number}, Response:\n{str(resp)}")
    return str(resp)

@app.route('/')
def home():
    return "¡Bienvenido al Bot de la Peluquería! 💇‍♀️"

@app.route('/test', methods=['GET'])
def test():
    return "El servidor está funcionando correctamente ✅"

@app.route('/reload-services', methods=['POST'])
def reload_services():
    """Recarga los servicios desde la base de datos."""
    try:
        current_app.active_services = get_active_services()
        logger.info(f"Services reloaded successfully. {len(current_app.active_services)} active services.")
        return {"status": "success", "message": f"Services reloaded. {len(current_app.active_services)} active services.", "count": len(current_app.active_services)}
    except Exception as e:
        logger.error(f"Error reloading services: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}, 500

@app.route('/services', methods=['GET'])
def get_services():
    """Obtiene la lista de servicios activos."""
    try:
        return {"status": "success", "services": current_app.active_services, "count": len(current_app.active_services)}
    except Exception as e:
        logger.error(f"Error getting services: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}, 500

# ============================================================================
# BLACKLIST SYSTEM FUNCTIONS
# ============================================================================

def handle_cancellation(user_id, service_name):
    """
    Maneja la cancelación y verifica si debe bloquear el servicio.
    3 cancelaciones del MISMO servicio en el MISMO DÍA = BLOQUEADO
    """
    try:
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        # Contar cancelaciones para este servicio HOY
        cancellations_today = current_app.appointments_collection.count_documents({
            'client_id': user_id,
            'service': service_name,
            'status': 'cancelled',
            'cancelled_at': {'$gte': today_start, '$lte': today_end}
        })
        
        # Obtener usuario
        user = current_app.clients_collection.find_one({'_id': user_id})
        if not user:
            return "Usuario no encontrado."
        
        # Inicializar campos si no existen
        if 'cancellation_counts' not in user:
            user['cancellation_counts'] = {}
        if 'blocked_services' not in user:
            user['blocked_services'] = {}
        
        # Actualizar contador
        current_count = user['cancellation_counts'].get(service_name, 0) + 1
        
        # Actualizar en base de datos
        current_app.clients_collection.update_one(
            {'_id': user_id},
            {
                '$set': {
                    f'cancellation_counts.{service_name}': current_count
                }
            }
        )
        
        # Verificar si debe bloquear
        settings = get_settings()
        max_cancellations = settings.get('max_cancellations_per_service', 3)
        if current_count >= max_cancellations:
            # Bloquear servicio
            current_app.clients_collection.update_one(
                {'_id': user_id},
                {'$set': {f'blocked_services.{service_name}': True}}
            )
            
            # Notificar por correo
            notify_blocked_users()
            
            return f"🚫 Has sido bloqueado para {service_name} por {max_cancellations} cancelaciones en el mismo día."
        elif current_count == 2:
            return f"🚨 ADVERTENCIA: Esta es tu 2ª cancelación de {service_name} hoy. Una más y serás bloqueado."
        else:
            return f"✅ Cancelación registrada. Cancelaciones de {service_name} hoy: {current_count}/{max_cancellations}"
            
    except Exception as e:
        logger.error(f"Error en handle_cancellation: {e}", exc_info=True)
        return "Error al procesar cancelación."

def check_inappropriate_language(user_id, message):
    """
    Verifica si el mensaje contiene lenguaje inapropiado.
    3 veces = BLOQUEO TOTAL
    """
    try:
        settings = get_settings()
        inappropriate_words = settings.get('inappropriate_words', [])
        
        message_lower = message.lower()
        inappropriate_count = sum(1 for word in inappropriate_words if word in message_lower)
        
        if inappropriate_count > 0:
            user = current_app.clients_collection.find_one({'_id': user_id})
            if not user:
                return "Usuario no encontrado."
            
            # Incrementar contador
            current_count = user.get('inappropriate_language_count', 0) + 1
            
            # Actualizar en base de datos
            current_app.clients_collection.update_one(
                {'_id': user_id},
                {'$set': {'inappropriate_language_count': current_count}}
            )
            
            # Verificar si debe bloquear
            max_inappropriate = settings.get('max_inappropriate_language', 3)
            if current_count >= max_inappropriate:
                # Bloquear usuario completamente
                current_app.clients_collection.update_one(
                    {'_id': user_id},
                    {'$set': {'is_blocked': True}}
                )
                
                # Notificar por correo
                notify_blocked_users()
                
                return "🚫 Has sido bloqueado por usar lenguaje inapropiado 3 veces."
            else:
                return f"⚠️ ADVERTENCIA {current_count}/{max_inappropriate}: Por favor, mantén un lenguaje respetuoso."
        
        return None  # No hay lenguaje inapropiado
        
    except Exception as e:
        logger.error(f"Error en check_inappropriate_language: {e}", exc_info=True)
        return None

def create_blocked_users_message():
    """
    Crea el mensaje con la lista de usuarios bloqueados y motivos.
    """
    try:
        message_parts = ["🚫 USUARIOS BLOQUEADOS - REPORTE AUTOMÁTICO"]
        message_parts.append(f"📅 Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        message_parts.append("")
        
        # Usuarios completamente bloqueados
        blocked_users = list(current_app.clients_collection.find({'is_blocked': True}))
        if blocked_users:
            message_parts.append("🔴 USUARIOS COMPLETAMENTE BLOQUEADOS:")
            for user in blocked_users:
                reason = "Lenguaje inapropiado" if user.get('inappropriate_language_count', 0) >= 3 else "Múltiples violaciones"
                message_parts.append(f"• {user['name']} ({user.get('phone_number', 'N/A')}) - {reason}")
            message_parts.append("")
        
        # Usuarios con servicios bloqueados
        users_with_blocked_services = []
        for user in current_app.clients_collection.find({}):
            blocked_services = user.get('blocked_services', {})
            blocked_service_names = [service for service, blocked in blocked_services.items() if blocked]
            if blocked_service_names:
                users_with_blocked_services.append((user, blocked_service_names))
        
        if users_with_blocked_services:
            message_parts.append("🟡 USUARIOS CON SERVICIOS BLOQUEADOS:")
            for user, blocked_services in users_with_blocked_services:
                message_parts.append(f"• {user['name']} ({user.get('phone_number', 'N/A')})")
                for service in blocked_services:
                    count = user.get('cancellation_counts', {}).get(service, 0)
                    message_parts.append(f"  - {service}: {count} cancelaciones")
            message_parts.append("")
        
        if not blocked_users and not users_with_blocked_services:
            message_parts.append("✅ No hay usuarios bloqueados actualmente.")
        
        return "\n".join(message_parts)
        
    except Exception as e:
        logger.error(f"Error en create_blocked_users_message: {e}", exc_info=True)
        return "Error al generar reporte de usuarios bloqueados."

def notify_blocked_users():
    """Recupera la lista de usuarios bloqueados."""
    blocked_users_collection = current_app.blocked_users_collection
    return list(blocked_users_collection.find())

def display_admin_menu(resp, menu_config):
    """Construye y envía un menú de administrador a partir de un diccionario de configuración."""
    title = menu_config.get('title', "Menú de Administrador")
    options = menu_config.get('options', [])
    
    message_parts = [title]
    for opt in options:
        message_parts.append(f"{opt['key']}. {opt['text']}")
    # Unir con salto de línea para evitar que se peguen
    resp.message("\n".join(message_parts))

def handle_admin_flow(resp, phone_number, incoming_msg):
    """Maneja el flujo de conversación para administradores de forma dinámica desde la BD."""
    admin_collection = current_app.db.admins
    state_doc = admin_collection.find_one_and_update(
        {'phone_number': phone_number},
        {'$setOnInsert': {'state': 'initial'}},
        upsert=True,
        return_document=pymongo.ReturnDocument.AFTER
    )
    current_state = state_doc.get('state', 'initial')
    settings = get_settings()

    def update_admin_state(new_state):
        admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': new_state}})
        logger.info(f"Admin state for {phone_number} updated to {new_state}")

    # Comando 'admin' siempre resetea al menú principal
    if incoming_msg.lower() == 'admin':
        update_admin_state('admin_menu')
        main_menu_config = settings.get('admin_main_menu')
        if main_menu_config:
            display_admin_menu(resp, main_menu_config)
        else:
            resp.message("Error: Configuración del menú de administrador no encontrada.")
        return True

    # ---- MANEJO DE MENÚS DINÁMICOS ----
    menu_map = {
        'admin_menu': 'admin_main_menu',
        'manage_schedule_menu': 'admin_schedule_menu'
    }

    if current_state in menu_map:
        menu_key = menu_map[current_state]
        menu_config = settings.get(menu_key)

        if not menu_config:
            resp.message(f"Error: Configuración para '{menu_key}' no encontrada.")
            update_admin_state('initial')
            return True

        selected_option = next((opt for opt in menu_config.get('options', []) if opt['key'] == incoming_msg), None)

        if selected_option:
            if 'next_state' in selected_option:
                next_state = selected_option['next_state']
                update_admin_state(next_state)
                if next_state in menu_map:
                    next_menu_config = settings.get(menu_map[next_state])
                    if next_menu_config:
                        display_admin_menu(resp, next_menu_config)
                elif 'prompt' in selected_option:
                    resp.message(selected_option['prompt'])
            
            elif 'action' in selected_option:
                action = selected_option['action']
                if action == 'show_blocked_users':
                    resp.message(create_blocked_users_message())
                elif action == 'exit_admin_mode':
                    update_admin_state('initial')
                    if 'prompt' in selected_option:
                        resp.message(selected_option['prompt'])
                elif action == 'return_to_main_menu':
                    update_admin_state('admin_menu')
                    main_menu_config = settings.get(menu_map['admin_menu'])
                    if main_menu_config:
                        display_admin_menu(resp, main_menu_config)
                elif action == 'show_cancellations_today':
                    mostrar_cancelaciones_del_dia(resp)
                elif action == 'show_todays_appointments':
                    mostrar_citas_del_dia(resp)
                elif action == 'toggle_calendar_block':
                    handle_toggle_calendar_block(resp)
        else:
            display_admin_menu(resp, menu_config)
        
        return True

    # ---- MANEJO DE ESTADOS ESPECÍFICOS (NO MENÚS) ----
    elif current_state == 'view_appointments_date':
        return handle_view_appointments(resp, phone_number, incoming_msg)
    elif current_state == 'update_start_hour':
        return handle_update_start_hour(resp, phone_number, incoming_msg)
    elif current_state == 'awaiting_new_end_hour':
        return handle_update_end_hour(resp, phone_number, incoming_msg)
    elif current_state == 'update_end_hour':
        return handle_update_end_hour(resp, phone_number, incoming_msg)
    elif current_state in ['cancel_appointments_date', 'awaiting_cancellation_choice']:
        return handle_cancellation_decision(resp, phone_number, incoming_msg)
    elif current_state == 'unblock_user_number':
        return handle_unblock_user(resp, phone_number, incoming_msg)

    return False

def handle_view_appointments(resp, phone_number, incoming_msg):
    """Maneja la visualización de citas para una fecha dada por el admin."""
    admin_collection = current_app.db.admins
    appointments_collection = current_app.db.appointments
    santiago_tz = pytz.timezone('America/Santiago')

    date_obj = parse_date_only(incoming_msg)
    if not date_obj:
        resp.message("No entendí la fecha. Por favor, usa 'hoy', 'mañana' o el formato DD/MM.\n\nVolviendo al menú principal.")
        admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}})
        return

    start_of_day = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    # Convertir a strings ISO para comparar con las fechas guardadas como strings
    start_of_day_iso = start_of_day.isoformat()
    end_of_day_iso = end_of_day.isoformat()

    appointments_cursor = appointments_collection.find({
        'date': {'$gte': start_of_day_iso, '$lt': end_of_day_iso},
        'status': 'confirmed'
    }).sort('date', 1)

    appointments = list(appointments_cursor)
    
    if not appointments:
        resp.message(f"No hay citas confirmadas para el {start_of_day.strftime('%d/%m/%Y')}.")
    else:
        message = f"--- Citas para el {start_of_day.strftime('%d/%m/%Y')} ---\n"
        for appt in appointments:
            # Parsear la fecha string a datetime para mostrar la hora
            appt_date = dateutil.parser.isoparse(appt['date'])
            local_time = appt_date.astimezone(santiago_tz)
            message += f"• {local_time.strftime('%H:%M')} - {appt['service']} ({appt['client_name']})\n"
        resp.message(message)
    
    admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}})

def handle_update_start_hour(resp, phone_number, incoming_msg):
    """Maneja la actualización de la hora de inicio de atención."""
    admin_collection = current_app.db.admins
    try:
        # Simple validation for HH:MM format
        datetime.strptime(incoming_msg, '%H:%M')
        admin_collection.update_one(
            {'phone_number': phone_number},
            {'$set': {'state': 'awaiting_new_end_hour', 'new_start_hour': incoming_msg}}
        )
        resp.message("✅ Hora de apertura guardada. Ahora, escribe la nueva hora de CIERRE (ej: 18:00).")
    except ValueError:
        resp.message("Formato de hora inválido. Por favor, usa HH:MM (ej: 09:30).")

def handle_update_end_hour(resp, phone_number, incoming_msg):
    from utils import get_settings_collection # Import locally to avoid circular dependency issues
    admin_collection = current_app.db.admins
    admin_state_doc = admin_collection.find_one({'phone_number': phone_number})
    new_start_hour = admin_state_doc.get('new_start_hour')
    try:
        datetime.strptime(incoming_msg, '%H:%M')
        settings_collection = get_settings_collection()
        settings_collection.update_one(
            {'_id': 'global_settings'},
            {'$set': {'business_hours': {'start': new_start_hour, 'end': incoming_msg}, 'last_updated': datetime.now()}}
        )
        resp.message(f"✅ ¡Horario actualizado! El nuevo horario de atención es de {new_start_hour} a {incoming_msg}.")
        admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}})
        # Recargar settings globales para reflejar el nuevo horario en el cliente
        current_app.settings = get_settings()
        # Mostrar menú de admin automáticamente
        settings = get_settings()
        main_menu_config = settings.get('admin_main_menu')
        if main_menu_config:
            display_admin_menu(resp, main_menu_config)
    except ValueError:
        resp.message("Formato de hora inválido. Por favor, usa HH:MM (ej: 18:00).")

def handle_cancellation_decision(resp, phone_number, incoming_msg):
    """Maneja la lógica de cancelación de citas para el administrador, desde la selección de fecha hasta la cancelación."""
    admin_collection = current_app.db.admins
    appointments_collection = current_app.db.appointments
    state_doc = admin_collection.find_one({'phone_number': phone_number})
    current_state = state_doc.get('state') if state_doc else 'initial'

    def cancel_single_appointment(appt_id_str):
        """Helper to cancel one appointment by su ID string."""
        try:
            from bson import ObjectId
            appt_id = ObjectId(appt_id_str)
            appt = appointments_collection.find_one({'_id': appt_id})
            
            if not appt:
                logger.error(f"Appointment {appt_id_str} not found")
                return False

            event_id = appt.get('calendar_event_id')
            if event_id:
                logger.info(f"Attempting to remove calendar event: {event_id}")
                remove_from_calendar(event_id)
            # Borrado lógico: marcar como cancelada por admin y guardar fecha
            appointments_collection.update_one(
                {'_id': appt_id},
                {'$set': {'status': 'cancelled_by_admin', 'cancelled_at': datetime.now(pytz.timezone('America/Santiago'))}}
            )
            logger.info(f"Appointment {appt_id_str} marked as cancelled_by_admin")
            return True
        except Exception as e:
            logger.error(f"Error canceling single appointment {appt_id_str}: {e}", exc_info=True)
            return False

    # State 1: Admin has asked to cancel, now provides a date.
    if current_state == 'cancel_appointments_date':
        parsed_date_result = parse_date_only(incoming_msg)
        if not parsed_date_result:
            resp.message("No entendí la fecha. Por favor, intenta de nuevo con formatos como 'hoy', 'mañana', o 'DD/MM'.")
            return True # Stop flow if date is invalid

        target_date = parsed_date_result
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # Convertir a strings ISO para comparar con las fechas guardadas como strings
        start_of_day_iso = start_of_day.isoformat()
        end_of_day_iso = end_of_day.isoformat()

        query = {
            'date': {'$gte': start_of_day_iso, '$lt': end_of_day_iso},
            'status': 'confirmed'
        }
        appointments_to_cancel = list(appointments_collection.find(query).sort('date', ASCENDING))

        if not appointments_to_cancel:
            # Buscar eventos en Google Calendar para ese día
            try:
                from googleapiclient.discovery import build
                from google.oauth2 import service_account
                santiago_tz = pytz.timezone('America/Santiago')
                credentials = service_account.Credentials.from_service_account_file(
                    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                service = build('calendar', 'v3', credentials=credentials)
                events_result = service.events().list(
                    calendarId=CALENDAR_ID,
                    timeMin=start_of_day.isoformat(),
                    timeMax=end_of_day.isoformat(),
                    singleEvents=True,
                    orderBy='startTime',
                    timeZone='America/Santiago'
                ).execute()
                events = events_result.get('items', [])
                if not events:
                    resp.message(f"No hay citas programadas ni eventos en el calendario para el {target_date.strftime('%d/%m/%Y')}.")
                    admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}})
                    return True
                # Guardar eventos en el estado del admin para la siguiente interacción
                event_options = {}
                message = f"No hay citas programadas para el {target_date.strftime('%d/%m/%Y')}, pero se encontraron los siguientes eventos en el calendario:\n"
                for i, event in enumerate(events, 1):
                    start_time = event['start'].get('dateTime', '')
                    summary = event.get('summary', 'Sin título')
                    message += f"\n*{i}.* {summary} a las {start_time[-14:-9]}"
                    event_options[str(i)] = event['id']
                message += "\n\nResponde con el número para eliminar solo ese evento, o escribe *'todas'* para eliminar todos los eventos del día, o *'salir'* para volver."
                resp.message(message)
                admin_collection.update_one(
                    {'phone_number': phone_number},
                    {'$set': {'state': 'awaiting_calendar_event_choice', 'calendar_event_options': event_options, 'calendar_event_date': start_of_day_iso}}
                )
                return True
            except Exception as e:
                resp.message(f"No hay citas programadas para el {target_date.strftime('%d/%m/%Y')}. Además, ocurrió un error al consultar el calendario: {e}")
                admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}})
                return True

        message = "Encontramos las siguientes citas. ¿Cuál quieres cancelar?\n"
        cancellation_options = {}
        for i, appt in enumerate(appointments_to_cancel, 1):
            client = current_app.clients_collection.find_one({'_id': appt['client_id']})
            client_name = client.get('name', 'N/A') if client else 'N/A'
            # Parsear la fecha string a datetime para mostrar la hora
            appt_date = dateutil.parser.isoparse(appt['date'])
            appt_time = appt_date.astimezone(pytz.timezone('America/Santiago')).strftime('%H:%M')
            message += f"\n*{i}.* {appt['service']} para *{client_name}* a las {appt_time}"
            cancellation_options[str(i)] = str(appt['_id'])

        message += "\n\nResponde con el número, escribe *'todas'* para cancelarlas todas, o *'salir'* para volver."
        resp.message(message)
        
        admin_collection.update_one(
            {'phone_number': phone_number},
            {'$set': {'state': 'awaiting_cancellation_choice', 'cancellation_options': cancellation_options}}
        )
        return True

    # Nuevo estado: esperando elección de evento de calendario
    elif current_state == 'awaiting_calendar_event_choice':
        event_options = state_doc.get('calendar_event_options', {})
        calendar_event_date = state_doc.get('calendar_event_date')
        if incoming_msg == 'todas':
            # Confirmar antes de eliminar todos
            resp.message("¿Está seguro que desea eliminar todos los eventos del día de hoy? Responde 'si' para confirmar o 'no' para cancelar.")
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'confirm_delete_all_calendar_events'}})
            return True
        elif incoming_msg.isdigit() and incoming_msg in event_options:
            event_id = event_options[incoming_msg]
            try:
                from googleapiclient.discovery import build
                from google.oauth2 import service_account
                credentials = service_account.Credentials.from_service_account_file(
                    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                service = build('calendar', 'v3', credentials=credentials)
                service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
                resp.message("✅ Evento eliminado del calendario.")
            except Exception as e:
                resp.message(f"Ocurrió un error al eliminar el evento: {e}")
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}, '$unset': {'calendar_event_options': '', 'calendar_event_date': ''}})
            return True
        elif incoming_msg == 'salir':
            resp.message("Operación cancelada. Volviendo al menú de administrador.")
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}, '$unset': {'calendar_event_options': '', 'calendar_event_date': ''}})
            return True
        else:
            resp.message("Opción no válida. Responde con el número, 'todas' o 'salir'.")
            return True

    elif current_state == 'confirm_delete_all_calendar_events':
        if incoming_msg.lower() == 'si':
            # Eliminar todos los eventos guardados en el estado
            event_options = state_doc.get('calendar_event_options', {})
            try:
                from googleapiclient.discovery import build
                from google.oauth2 import service_account
                credentials = service_account.Credentials.from_service_account_file(
                    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                service = build('calendar', 'v3', credentials=credentials)
                deleted_count = 0
                for event_id in event_options.values():
                    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
                    deleted_count += 1
                resp.message(f"✅ Se eliminaron {deleted_count} eventos del calendario para ese día.")
            except Exception as e:
                resp.message(f"Ocurrió un error al eliminar los eventos: {e}")
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}, '$unset': {'calendar_event_options': '', 'calendar_event_date': ''}})
            return True
        else:
            resp.message("Operación cancelada. No se eliminaron eventos.")
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}, '$unset': {'calendar_event_options': '', 'calendar_event_date': ''}})
            return True

    elif current_state == 'awaiting_cancellation_choice':
        cancellation_options = state_doc.get('cancellation_options', {})
        settings = get_settings() # Cargar settings para acceder al menú
        main_menu_config = settings.get('admin_main_menu')

        def return_to_main_menu(message):
            """Helper to send a message and display the main admin menu."""
            resp.message(message)
            if main_menu_config:
                display_admin_menu(resp, main_menu_config)
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}, '$unset': {'cancellation_options': ''}})

        if incoming_msg == 'todas':
            # Confirmar antes de cancelar todas
            resp.message("¿Está seguro que desea cancelar todas las citas del día de hoy? Responde 'si' para confirmar o 'no' para cancelar.")
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'confirm_cancel_all_appointments', 'cancellation_options': cancellation_options}})
            return True
        elif incoming_msg.isdigit() and incoming_msg in cancellation_options:
            appt_id_to_cancel = cancellation_options[incoming_msg]
            if cancel_single_appointment(appt_id_to_cancel):
                return_to_main_menu(f"✅ Cita cancelada con éxito.")
            else:
                return_to_main_menu(f"❌ No se pudo cancelar la cita. Intenta de nuevo.")
            return True

        elif incoming_msg == 'salir':
            return_to_main_menu("Cancelación abortada. Volviendo al menú de administrador.")
            return True
        
        else:
            resp.message("Opción no válida. Por favor, elige un número de la lista, 'todas' o 'salir'.")
            return True

    elif current_state == 'confirm_cancel_all_appointments':
        if incoming_msg.lower() == 'si':
            cancellation_options = state_doc.get('cancellation_options', {})
            cancelled_count = 0
            for appt_id in cancellation_options.values():
                if cancel_single_appointment(appt_id):
                    cancelled_count += 1
            resp.message(f"✅ Se han cancelado con éxito {cancelled_count} citas.")
            settings = get_settings()
            main_menu_config = settings.get('admin_main_menu')
            if main_menu_config:
                display_admin_menu(resp, main_menu_config)
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}, '$unset': {'cancellation_options': ''}})
            return True
        elif incoming_msg.lower() == 'no':
            resp.message("Operación cancelada. No se eliminaron citas. Volviendo al menú de administrador.")
            settings = get_settings()
            main_menu_config = settings.get('admin_main_menu')
            if main_menu_config:
                display_admin_menu(resp, main_menu_config)
            admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}, '$unset': {'cancellation_options': ''}})
            return True
        else:
            resp.message("Opción no válida. Responde 'si' para confirmar o 'no' para cancelar.")
            return True

    elif current_state == 'unblock_user_number':
        return handle_unblock_user(resp, phone_number, incoming_msg)

    return False

def handle_unblock_user(resp, phone_number, incoming_msg):
    user_to_unblock = incoming_msg.strip()
    if not re.match(r'^569\d{8}$', user_to_unblock):
        resp.message("El formato del número es incorrecto. Debe ser '569' seguido de 8 dígitos. Inténtalo de nuevo o escribe 'cancelar'.")
        return True
    clients_collection = current_app.clients_collection
    user_doc = clients_collection.find_one({'phone_number': f'whatsapp:+{user_to_unblock}'})
    if not user_doc or not user_doc.get('is_blocked', False):
        resp.message(f"El usuario {user_to_unblock} no se encuentra o no está bloqueado.")
    else:
        clients_collection.update_one(
            {'_id': user_doc['_id']},
            {'$set': {'is_blocked': False, 'blocked_reason': ''}, '$unset': {'blocked_services': '', 'block_message_sent': ''}}
        )
        resp.message(f"✅ Usuario {user_to_unblock} desbloqueado exitosamente.")
    # Volver al estado inicial del admin y mostrar menú
    admin_collection = current_app.db.admins
    admin_collection.update_one({'phone_number': phone_number}, {'$set': {'state': 'admin_menu'}})
    settings = get_settings()
    main_menu_config = settings.get('admin_main_menu')
    if main_menu_config:
        display_admin_menu(resp, main_menu_config)
    return True

def handle_toggle_calendar_block(resp):
    from utils import get_settings_collection
    try:
        settings_collection = get_settings_collection()
        current_settings = settings_collection.find_one({'_id': 'global_settings'})
        calendar_blocked = current_settings.get('calendar_blocked', False) if current_settings else False
        new_blocked_state = not calendar_blocked
        settings_collection.update_one(
            {'_id': 'global_settings'},
            {
                '$set': {
                    'calendar_blocked': new_blocked_state,
                    'calendar_blocked_at': datetime.now() if new_blocked_state else None
                }
            },
            upsert=True
        )
        if new_blocked_state:
            resp.message("🔒 Calendario BLOQUEADO. Los usuarios no podrán *agendar* citas hasta que lo desbloquees.")
        else:
            resp.message("✅ Calendario DESBLOQUEADO. Los usuarios pueden *agendar* citas normalmente.")
        # Mostrar menú de admin automáticamente
        settings = get_settings()
        main_menu_config = settings.get('admin_main_menu')
        if main_menu_config:
            display_admin_menu(resp, main_menu_config)
    except Exception as e:
        logger.error(f"Error al cambiar estado del bloqueo de calendario: {e}", exc_info=True)
        resp.message("❌ Ocurrió un error al cambiar el estado del calendario. Intenta de nuevo.")

def mostrar_cancelaciones_del_dia(resp):
    from datetime import datetime, timedelta
    import pytz
    db = current_app.db
    appointments_collection = db.appointments
    clients_collection = db.clients
    santiago_tz = pytz.timezone('America/Santiago')
    hoy = datetime.now(santiago_tz).date()
    inicio = datetime.combine(hoy, datetime.min.time()).astimezone(santiago_tz)
    fin = inicio + timedelta(days=1)
    # Buscar solo citas canceladas por usuarios
    citas = list(appointments_collection.find({
        'status': 'cancelled',
        'cancelled_at': {'$gte': inicio, '$lt': fin}
    }))
    if not citas:
        resp.message('No hay cancelaciones registradas para hoy.')
        return
    mensaje = '--- Cancelaciones de hoy (usuarios) ---\n'
    for c in citas:
        cliente = clients_collection.find_one({'_id': c.get('client_id')})
        nombre = cliente.get('name', 'N/A') if cliente else 'N/A'
        telefono = cliente.get('phone_number', 'N/A') if cliente else 'N/A'
        servicio = c.get('service', 'N/A')
        # Obtener hora de la cita cancelada
        fecha = c.get('date')
        if isinstance(fecha, str):
            import dateutil.parser
            fecha = dateutil.parser.isoparse(fecha)
        hora = fecha.astimezone(santiago_tz).strftime('%H:%M') if fecha else 'N/A'
        mensaje += f"\n• {servicio} — {nombre} — {telefono} — {hora}"
    resp.message(mensaje)

def mostrar_citas_del_dia(resp):
    from datetime import datetime, timedelta
    import pytz
    db = current_app.db
    appointments_collection = db.appointments
    clients_collection = db.clients
    santiago_tz = pytz.timezone('America/Santiago')
    hoy = datetime.now(santiago_tz).date()
    inicio = datetime.combine(hoy, datetime.min.time()).astimezone(santiago_tz)
    fin = inicio + timedelta(days=1)
    # Buscar citas confirmadas hoy
    citas = list(appointments_collection.find({
        'status': 'confirmed',
        'date': {'$gte': inicio.isoformat(), '$lt': fin.isoformat()}
    }))
    if not citas:
        resp.message('No hay citas confirmadas para hoy.')
        return
    mensaje = '--- Citas confirmadas de hoy ---\n'
    for c in citas:
        cliente = clients_collection.find_one({'_id': c.get('client_id')})
        nombre = cliente.get('name', 'N/A') if cliente else 'N/A'
        telefono = cliente.get('phone_number', 'N/A') if cliente else 'N/A'
        servicio = c.get('service', 'N/A')
        # Obtener hora de la cita
        fecha = c.get('date')
        if isinstance(fecha, str):
            import dateutil.parser
            fecha = dateutil.parser.isoparse(fecha)
        hora = fecha.astimezone(santiago_tz).strftime('%H:%M') if fecha else 'N/A'
        mensaje += f"\n• {servicio} — {nombre} — {telefono} — {hora}"
    resp.message(mensaje)

# Crear la instancia de la aplicación para Gunicorn
app = create_app()

if __name__ == '__main__':
    # For development, run directly. For production, Gunicorn will use the `app` variable above.
    app.run(debug=True, port=5001)