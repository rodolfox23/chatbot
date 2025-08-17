#!/usr/bin/env python3
"""
Script para probar la conexión a MongoDB y verificar que los servicios se carguen correctamente.
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# URI de MongoDB (la misma que usas en Heroku)
MONGODB_URI = "mongodb+srv://engineer3222:F4TmJs44Ljj8M7As@chatbotpeluqueria.aobk0tc.mongodb.net/peluqueria_bot?retryWrites=true&w=majority&ssl=true&ssl_cert_reqs=CERT_NONE&appName=chatbotpeluqueria"

def test_mongo_connection():
    """Prueba la conexión a MongoDB y verifica los servicios."""
    
    print("🔍 Probando conexión a MongoDB...")
    print(f"URI: {MONGODB_URI}")
    print("-" * 50)
    
    try:
        # Conectar a MongoDB
        client = MongoClient(MONGODB_URI)
        db = client['peluqueria_bot']
        
        # Probar conexión básica
        print("📡 Conectando...")
        result = db.command('ping')
        print(f"✅ Ping exitoso: {result}")
        
        # Listar colecciones
        print("\n📚 Colecciones disponibles:")
        collections = db.list_collection_names()
        for coll in collections:
            print(f"  - {coll}")
        
        # Verificar servicios
        print("\n💅 Verificando servicios...")
        services_collection = db.services
        services = list(services_collection.find({'is_active': True}))
        
        if services:
            print(f"✅ Se encontraron {len(services)} servicios activos:")
            for i, service in enumerate(services, 1):
                print(f"  {i}. {service['emoji']} {service['name']} - ${service['price']} ({service['duration_minutes']} min)")
        else:
            print("❌ No se encontraron servicios activos")
        
        # Verificar configuración
        print("\n⚙️ Verificando configuración...")
        settings = db.settings.find_one({})
        if settings:
            print("✅ Configuración encontrada")
            print(f"  - Horario: {settings.get('business_hours', {}).get('start_hour', 'N/A')} - {settings.get('business_hours', {}).get('end_hour', 'N/A')}")
        else:
            print("❌ No se encontró configuración")
        
        # Verificar mensajes
        print("\n💬 Verificando mensajes...")
        messages = list(db.messages.find({}))
        print(f"✅ Se encontraron {len(messages)} mensajes")
        
        print("\n🎉 ¡Conexión exitosa! Todo está funcionando correctamente.")
        
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        print(f"Tipo de error: {type(e).__name__}")
    finally:
        if 'client' in locals():
            client.close()
            print("\n🔌 Conexión cerrada.")

if __name__ == "__main__":
    test_mongo_connection()
