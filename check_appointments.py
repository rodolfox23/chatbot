#!/usr/bin/env python3
"""
Script para revisar las citas en la base de datos.
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv
import pytz
from datetime import datetime

# Cargar variables de entorno
load_dotenv()

def check_appointments():
    """Revisa todas las citas en la base de datos."""
    
    client = None
    try:
        print("Conectando a MongoDB...")
        client = MongoClient(os.getenv("MONGODB_URI"))
        db = client['peluqueria_bot']
        appointments_collection = db.appointments
        
        print("\n" + "="*60)
        print("  REVISIÓN DE CITAS EN LA BASE DE DATOS")
        print("="*60)
        
        # Obtener todas las citas
        appointments = list(appointments_collection.find().sort('date', 1))
        
        if not appointments:
            print("No hay citas en la base de datos.")
            return
        
        santiago_tz = pytz.timezone('America/Santiago')
        
        for i, appt in enumerate(appointments, 1):
            print(f"\n{i}. Cita ID: {appt['_id']}")
            print(f"   Cliente: {appt.get('client_name', 'N/A')}")
            print(f"   Servicio: {appt['service']}")
            print(f"   Estado: {appt['status']}")
            
            # Parsear la fecha
            date_str = appt['date']
            if isinstance(date_str, str):
                from dateutil import parser
                parsed_date = parser.isoparse(date_str)
            else:
                parsed_date = date_str
            
            # Convertir a hora local
            if parsed_date.tzinfo is None:
                parsed_date = santiago_tz.localize(parsed_date)
            elif parsed_date.tzinfo != santiago_tz:
                parsed_date = parsed_date.astimezone(santiago_tz)
            
            local_time = parsed_date.strftime('%d/%m/%Y a las %H:%M')
            print(f"   Fecha: {local_time}")
            print(f"   Fecha original en BD: {date_str}")
            
            if 'calendar_event_id' in appt:
                print(f"   Evento Calendar: {appt['calendar_event_id']}")
            
            print("-" * 40)
        
        print(f"\nTotal de citas: {len(appointments)}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if client:
            client.close()

if __name__ == "__main__":
    check_appointments() 