#!/usr/bin/env python3
"""
Script para verificar y mostrar la lista de administradores desde la base de datos.
"""

import os
from pymongo import MongoClient
from config import Config
import logging

# Configuración del logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def verify_admins_in_db():
    """Se conecta a la BD y muestra la lista de números de administrador."""
    
    client = None
    try:
        logging.info("Conectando a MongoDB...")
        client = MongoClient(Config.MONGODB_URI)
        db = client['peluqueria_bot']
        settings_collection = db.settings
        
        logging.info("Buscando el documento de configuración global...")
        settings = settings_collection.find_one({'_id': 'global_settings'})
        
        if not settings:
            logging.error("¡Error! No se encontró el documento de configuración en la base de datos.")
            return

        admin_numbers = settings.get('admin_numbers', [])
        
        if not admin_numbers:
            logging.warning("El documento de configuración existe, pero no hay administradores definidos en la lista 'admin_numbers'.")
        else:
            print("\n" + "="*40)
            print("  LISTA DE ADMINISTRADORES EN LA BASE DE DATOS")
            print("="*40)
            for i, num in enumerate(admin_numbers, 1):
                print(f"  {i}. {num}")
            print("="*40)
            logging.info("La verificación fue exitosa.")

    except Exception as e:
        logging.error(f"Ocurrió un error durante la verificación: {e}", exc_info=True)
    finally:
        if client:
            client.close()
            logging.info("Conexión a MongoDB cerrada.")

if __name__ == "__main__":
    verify_admins_in_db() 