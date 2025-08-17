from pymongo import MongoClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DB_NAME = "peluqueria_bot"

def get_settings_collection():
    """Get the settings collection from MongoDB."""
    import certifi
    client = MongoClient(
        MONGO_URI,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=10000,
        socketTimeoutMS=10000
    )
    db = client[DB_NAME]
    return db["settings"]

def get_settings():
    """Get the global settings from the database."""
    try:
        collection = get_settings_collection()
        settings = collection.find_one({'_id': 'global_settings'})
        return settings
    except Exception as e:
        print(f"Error getting settings: {e}")
        return {}

def get_db_connection():
    try:
        import certifi
        client = MongoClient(
            MONGO_URI,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000
        )
        db = client[DB_NAME]
        return db
    except Exception as e:
        print(f"Error al conectar a MongoDB: {e}")
        return None

def load_messages():
    """Carga todos los mensajes desde la colección 'messages' y los devuelve como un diccionario."""
    db = get_db_connection()
    messages = {}
    if db is not None:
        try:
            message_cursor = db.messages.find({})
            for msg in message_cursor:
                messages[msg['key']] = msg['value']
        except Exception as e:
            # logger no está disponible aquí de forma sencilla, imprimimos el error
            print(f"Error al cargar mensajes desde la base de datos: {e}")
            return None
    return messages 

def get_active_services():
    """
    Get all active services from the database.
    Returns a list of service dictionaries.
    """
    db = get_db_connection()
    if db is None:
        return []
        
    try:
        services_collection = db.services
        services = list(services_collection.find({'is_active': True}).sort('_id', 1))
        # Asegurarse de que los ObjectIds son convertidos a strings si es necesario
        for service in services:
            service['_id'] = str(service['_id'])
        return services
    except Exception as e:
        # Aquí sería ideal tener un logger, pero por simplicidad usamos print
        print(f"Error getting active services: {e}")
        return [] 

def get_service_duration(service_name: str) -> int:
    """
    Get the duration of a specific service from settings.
    Returns duration in minutes.
    """
    try:
        settings = get_settings()
        service_durations = settings.get('service_durations', {})
        return service_durations.get(service_name, 60)  # Default 60 minutes
    except Exception as e:
        print(f"Error getting service duration: {e}")
        return 60  # Default fallback 