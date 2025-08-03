from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
import json
import os

# Google Calendar API settings
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'service_account_credentials.json'
CALENDAR_ID = 'trabajoingeniero272@gmail.com'  # Tu correo electrónico aquí

def test_calendar_integration():
    try:
        print("\n=== INICIO TEST CALENDARIO ===")
        print("Directorio actual:", os.getcwd())
        
        # Verify credentials file exists
        try:
            print(f"\nBuscando archivo: {SERVICE_ACCOUNT_FILE}")
            with open(SERVICE_ACCOUNT_FILE, 'r') as f:
                creds_content = json.load(f)
                print(f"✅ Archivo de credenciales encontrado")
                print(f"📧 Cuenta de servicio: {creds_content.get('client_email')}")
                print(f"📅 ID del calendario: {CALENDAR_ID}")
        except FileNotFoundError as e:
            print(f"❌ Error: No se encontró el archivo {SERVICE_ACCOUNT_FILE}")
            print(f"Error completo: {str(e)}")
            return
        except json.JSONDecodeError as e:
            print(f"❌ Error: El archivo {SERVICE_ACCOUNT_FILE} no es un JSON válido")
            print(f"Error completo: {str(e)}")
            return
        except Exception as e:
            print(f"❌ Error inesperado al leer credenciales: {str(e)}")
            print(f"Tipo de error: {type(e)}")
            return
        
        # Get credentials
        print("\nObteniendo credenciales...")
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        print("✅ Credenciales obtenidas correctamente")
        
        # Build service
        print("\nConectando con Google Calendar API...")
        service = build('calendar', 'v3', credentials=credentials)
        print("✅ Conexión establecida")
        
        # Create test event (15 minutes from now)
        start_time = datetime.now(pytz.timezone('America/Santiago')) + timedelta(minutes=15)
        end_time = start_time + timedelta(minutes=30)
        
        event = {
            'summary': 'Evento de prueba',
            'description': 'Este es un evento de prueba para verificar la integración',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'America/Santiago',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'America/Santiago',
            },
        }
        
        print("\nIntentando crear evento de prueba...")
        try:
            event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            print(f'✅ Evento creado exitosamente!')
            print(f'🔗 Link del evento: {event.get("htmlLink")}')
        except Exception as e:
            print(f"❌ Error al crear el evento: {str(e)}")
            if 'permission' in str(e).lower():
                print("\n⚠️ Parece ser un problema de permisos.")
                print("Por favor, asegúrate de haber compartido tu calendario con:")
                print(f"📧 {creds_content.get('client_email')}")
                print("Y haberle dado permisos de 'Realizar cambios y administrar uso compartido'")
            return
        
        # List upcoming events to verify
        print("\nListando próximos eventos...")
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        if not events:
            print('No se encontraron eventos próximos.')
        else:
            print('Eventos próximos:')
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                print(f"- {event['summary']} ({start})")
                
    except Exception as e:
        print(f"\n❌ Error durante la prueba: {str(e)}")
        if hasattr(e, 'content'):
            print("Respuesta del servidor:", e.content)

if __name__ == '__main__':
    test_calendar_integration() 