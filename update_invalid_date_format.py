from utils import get_db_connection

db = current_app.db
nuevo_mensaje = (
    "🕒 Ups, no entendí la fecha.\n"
    "Por favor escribe algo así como:\n"
    "👉 22/06 a las 14:30\n"
    "👉 hoy a las 16:00"
)

result = db.messages.update_one(
    {'key': 'invalid_date_format'},
    {'$set': {'value': nuevo_mensaje}},
    upsert=True
)

if result.modified_count or result.upserted_id:
    print("✅ Mensaje actualizado correctamente.")
else:
    print("ℹ️ El mensaje ya estaba actualizado o no se modificó.") 