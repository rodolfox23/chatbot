from pymongo import MongoClient

# Cambia la URI si tu MongoDB no está en localhost o usa usuario/contraseña
client = MongoClient('mongodb://localhost:27017')
db = client.get_database()  # Usa la base de datos por defecto o cámbiala por el nombre correcto

# Cambia 'clients' si tu colección de usuarios tiene otro nombre
bloqueados = db.clients.find({"is_blocked": True})

print("Usuarios bloqueados:")
for user in bloqueados:
    print(f"Nombre: {user.get('name', 'N/A')}, Teléfono: {user.get('phone_number', 'N/A')}") 