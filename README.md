# 🤖 Bot de WhatsApp para Peluquería

Bot automatizado para agendar citas en peluquería a través de WhatsApp, con integración a Google Calendar y Mercado Pago.

## 🚀 Características

- ✅ Agendamiento automático de citas
- ✅ Integración con Google Calendar
- ✅ Pagos a través de Mercado Pago
- ✅ Gestión de clientes en MongoDB
- ✅ Validación de horarios disponibles
- ✅ Notificaciones automáticas

## 📋 Requisitos Previos

- Python 3.9+
- MongoDB
- Cuenta de Twilio
- Cuenta de Mercado Pago
- Google Calendar API

## 🛠️ Instalación

### 1. Clonar el repositorio
```bash
git clone <repository-url>
cd peluqueria_whatsapp_bot
```

### 2. Crear entorno virtual
```bash
python3 -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
Crear archivo `.env` en la raíz del proyecto:

```env
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here

# MongoDB Configuration
MONGODB_URI=mongodb://localhost:27017/peluqueria_bot

# Mercado Pago Configuration
MERCADOPAGO_ACCESS_TOKEN=your_mercadopago_access_token_here

# Google Calendar Configuration
GOOGLE_CALENDAR_ID=your_calendar_id@gmail.com

# Application Configuration
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5001
```

### 5. Configurar Google Calendar
1. Crear proyecto en Google Cloud Console
2. Habilitar Google Calendar API
3. Crear cuenta de servicio
4. Descargar credenciales como `service_account_credentials.json`
5. Compartir calendario con la cuenta de servicio

## 🚀 Ejecución

### Desarrollo y Producción
```bash
python app.py
```

El archivo `app.py` es ahora el punto de entrada principal. No se requieren scripts adicionales.

## 🔧 Configuración de Twilio

1. Crear cuenta en [Twilio](https://www.twilio.com)
2. Obtener Account SID y Auth Token
3. Configurar webhook URL: `https://tu-dominio.com/webhook-whatsapp`

## 💳 Configuración de Mercado Pago

1. Crear cuenta en [Mercado Pago](https://www.mercadopago.com)
2. Obtener Access Token
3. Configurar webhooks para notificaciones de pago

## 📊 Estructura del Proyecto

```
peluqueria_whatsapp_bot/
├── app.py                  # Aplicación principal Flask
├── calendar_utils.py       # Utilidades de Google Calendar
├── utils.py                # Utilidades generales y acceso a la base de datos
├── check_appointments.py   # Script para revisar citas
├── verify_admin.py         # Script para verificar administradores
├── unblock_users.py        # Script para desbloquear usuarios
├── requirements.txt        # Dependencias
├── .env                    # Variables de entorno (crear)
├── README.md               # Documentación
├── salon.db                # Base de datos local (si aplica)
├── service_account_credentials.json # Credenciales de Google
├── test_calendar.py        # Pruebas de calendario
└── venv/                   # Entorno virtual (no subir a git)
```

## 🐛 Solución de Problemas

### Error: "Address already in use"
```bash
# Verificar procesos usando el puerto
lsof -ti :5001

# Matar procesos
kill -9 <PID>
```

### Error: "MongoDB connection failed"
1. Verificar que MongoDB esté ejecutándose
2. Verificar URI de conexión en `.env`
3. Verificar permisos de red

### Error: "Google Calendar credentials error"
1. Verificar que `service_account_credentials.json` existe
2. Verificar permisos del calendario
3. Verificar que la API esté habilitada

### Error: "Twilio credentials not found"
1. Verificar variables de entorno en `.env`
2. Verificar que las credenciales sean correctas

## 📝 Logs

Los logs principales se guardan en:
- `app.log` - Logs de la aplicación

Puedes eliminar los archivos de log si necesitas limpiar espacio, no afectan el funcionamiento.

## 🔒 Seguridad

- ✅ Variables de entorno para credenciales
- ✅ Validación de entrada
- ✅ Manejo seguro de errores
- ✅ Logs sin información sensible

## 📞 Soporte

Para soporte técnico, contactar al administrador del sistema.

## 📄 Licencia

Este proyecto es privado y confidencial. 