#!/usr/bin/env python3
"""
Script para enviar notificaciones automáticas una hora antes de las citas.
Se ejecuta via crontab cada 5 minutos.
"""

import os
import sys
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from twilio.rest import Client
from dotenv import load_dotenv
import logging

# Cargar variables de entorno
load_dotenv()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('notification_scheduler.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Configuración de MongoDB
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = 'peluqueria_bot'

# Configuración de Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

def connect_to_mongodb():
    """Conecta a MongoDB y retorna las colecciones necesarias."""
    try:
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]
        return db.appointments, db.clients
    except Exception as e:
        logger.error(f"Error conectando a MongoDB: {e}")
        return None, None

def send_whatsapp_notification(phone_number, message):
    """Envía notificación por WhatsApp usando Twilio."""
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Formatear número de teléfono para WhatsApp
        if not phone_number.startswith('whatsapp:'):
            phone_number = f'whatsapp:{phone_number}'
        
        message_obj = client.messages.create(
            from_=f'whatsapp:{TWILIO_PHONE_NUMBER}',
            body=message,
            to=phone_number
        )
        
        logger.info(f"Notificación enviada exitosamente a {phone_number}")
        return True
        
    except Exception as e:
        logger.error(f"Error enviando notificación a {phone_number}: {e}")
        return False

def check_upcoming_appointments():
    """Revisa citas que están a 1 hora y envía notificaciones."""
    appointments_collection, clients_collection = connect_to_mongodb()
    
    if appointments_collection is None:
        logger.error("No se pudo conectar a MongoDB")
        return
    
    # Configurar zona horaria
    santiago_tz = pytz.timezone('America/Santiago')
    now = datetime.now(santiago_tz)
    one_hour_from_now = now + timedelta(hours=1)
    
    logger.info(f"Buscando citas entre {now.strftime('%H:%M')} y {one_hour_from_now.strftime('%H:%M')}")
    
    try:
        # Buscar citas confirmadas que están a 1 hora
        appointments = list(appointments_collection.find({
            'status': 'confirmed',
            'date': {
                '$gte': now,
                '$lte': one_hour_from_now
            },
            'notification_sent': {'$ne': True}  # Evitar duplicados
        }))
        
        logger.info(f"Encontradas {len(appointments)} citas para notificar")
        
        for appointment in appointments:
            try:
                # Obtener información del cliente
                client = clients_collection.find_one({'_id': appointment['client_id']})
                if not client:
                    logger.warning(f"No se encontró cliente para cita {appointment['_id']}")
                    continue
                
                # Verificar si la fecha es string y convertirla si es necesario
                fecha = appointment['date']
                if isinstance(fecha, str):
                    import dateutil.parser
                    fecha = dateutil.parser.isoparse(fecha)
                
                # Crear mensaje de recordatorio
                message = f"⏰ *Recordatorio de cita*\n\n"
                message += f" Servicio: {appointment['service']}\n"
                message += f"📅 Fecha: {fecha.strftime('%d/%m/%Y')}\n"
                message += f"🕖 Hora: {fecha.strftime('%H:%M')}\n\n"
                message += f"Tu cita es en 1 hora. ¡Te esperamos! 💅"
                
                # Enviar notificación
                if send_whatsapp_notification(client['phone_number'], message):
                    # Marcar como notificada
                    appointments_collection.update_one(
                        {'_id': appointment['_id']},
                        {'$set': {'notification_sent': True}}
                    )
                    logger.info(f"Notificación enviada y marcada para cita {appointment['_id']}")
                
            except Exception as e:
                logger.error(f"Error procesando cita {appointment['_id']}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Error en check_upcoming_appointments: {e}")

def main():
    """Función principal que ejecuta el check de notificaciones."""
    logger.info("=== Iniciando verificación de notificaciones ===")
    check_upcoming_appointments()
    logger.info("=== Verificación completada ===")

if __name__ == "__main__":
    main() 