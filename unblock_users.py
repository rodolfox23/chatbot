#!/usr/bin/env python3
"""
Script para desbloquear usuarios de la lista negra
"""

import os
from dotenv import load_dotenv
from pymongo import MongoClient
from config import Config

# Cargar variables de entorno
load_dotenv()

def unblock_all_users():
    """Desbloquea todos los usuarios de la lista negra"""
    
    try:
        # Conectar a MongoDB
        client = MongoClient(Config.MONGODB_URI)
        db = client['peluqueria_bot']
        clients_collection = db.clients
        
        print("🔍 Conectando a MongoDB...")
        
        # 1. Ver usuarios bloqueados antes de desbloquear
        blocked_users = list(clients_collection.find({"status": "blocked"}))
        users_with_blocked_services = list(clients_collection.find({"blocked_services": {"$exists": True, "$ne": {}}}))
        
        print(f"📊 Usuarios completamente bloqueados: {len(blocked_users)}")
        print(f"📊 Usuarios con servicios bloqueados: {len(users_with_blocked_services)}")
        
        if blocked_users:
            print("\n👥 Usuarios completamente bloqueados:")
            for user in blocked_users:
                print(f"  - {user.get('name', 'N/A')} ({user.get('phone_number', 'N/A')})")
        
        if users_with_blocked_services:
            print("\n🔒 Usuarios con servicios bloqueados:")
            for user in users_with_blocked_services:
                blocked_services = user.get('blocked_services', {})
                blocked_service_names = [service for service, blocked in blocked_services.items() if blocked]
                print(f"  - {user.get('name', 'N/A')} ({user.get('phone_number', 'N/A')}): {', '.join(blocked_service_names)}")
        
        # 2. Desbloquear usuarios completamente bloqueados
        if blocked_users:
            result1 = clients_collection.update_many(
                {"status": "blocked"},
                {
                    "$unset": {"status": ""},
                    "$set": {"inappropriate_language_count": 0}
                }
            )
            print(f"\n✅ Desbloqueados {result1.modified_count} usuarios completamente bloqueados")
        
        # 3. Desbloquear servicios específicos
        if users_with_blocked_services:
            result2 = clients_collection.update_many(
                {"blocked_services": {"$exists": True}},
                {
                    "$unset": {
                        "blocked_services": "",
                        "cancellation_counts": ""
                    }
                }
            )
            print(f"✅ Desbloqueados servicios para {result2.modified_count} usuarios")
        
        # 4. Verificar que no queden usuarios bloqueados
        remaining_blocked = list(clients_collection.find({"status": "blocked"}))
        remaining_service_blocked = list(clients_collection.find({"blocked_services": {"$exists": True, "$ne": {}}}))
        
        print(f"\n🎯 Verificación final:")
        print(f"  - Usuarios completamente bloqueados restantes: {len(remaining_blocked)}")
        print(f"  - Usuarios con servicios bloqueados restantes: {len(remaining_service_blocked)}")
        
        if len(remaining_blocked) == 0 and len(remaining_service_blocked) == 0:
            print("\n🎉 ¡Todos los usuarios han sido desbloqueados exitosamente!")
        else:
            print("\n⚠️ Algunos usuarios aún están bloqueados")
        
        client.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

def unblock_specific_user(phone_number):
    """Desbloquea un usuario específico por número de teléfono"""
    
    try:
        # Conectar a MongoDB
        client = MongoClient(Config.MONGODB_URI)
        db = client['peluqueria_bot']
        clients_collection = db.clients
        
        print(f"🔍 Buscando usuario: {phone_number}")
        
        # Buscar el usuario
        user = clients_collection.find_one({"phone_number": phone_number})
        
        if not user:
            print(f"❌ Usuario con número {phone_number} no encontrado")
            return
        
        print(f"👤 Usuario encontrado: {user.get('name', 'N/A')}")
        
        # Desbloquear el usuario
        result = clients_collection.update_one(
            {"phone_number": phone_number},
            {
                "$unset": {
                    "status": "",
                    "blocked_services": "",
                    "cancellation_counts": "",
                    "inappropriate_language_count": ""
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"✅ Usuario {user.get('name', 'N/A')} desbloqueado exitosamente")
        else:
            print(f"ℹ️ El usuario {user.get('name', 'N/A')} no estaba bloqueado")
        
        client.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("🚫 SCRIPT DE DESBLOQUEO DE USUARIOS")
    print("=" * 40)
    
    # Desbloquear todos los usuarios
    unblock_all_users()
    
    print("\n" + "=" * 40)
    print("💡 Para desbloquear un usuario específico, ejecuta:")
    print("   unblock_specific_user('whatsapp:+56937523266')") 