import os
import urllib.request
import urllib.parse

# Lectura de variables desde GitHub Secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def probar_telegram():
    print(f"Token detectado: {bool(TELEGRAM_BOT_TOKEN)}")
    print(f"Chat ID detectado: {bool(TELEGRAM_CHAT_ID)}")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR CRÍTICO: Las variables no están llegando desde GitHub Secrets.")
        return

    mensaje = "🤖 **PRUEBA EXITOSA DESDE GITHUB ACTIONS**\n\nSi estás leyendo esto, las credenciales están correctamente conectadas y las notificaciones funcionan."
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=10) as res:
            print(f"Respuesta de Telegram HTTP: {res.status}")
            print("MENSAJE ENVIADO CORRECTAMENTE A TELEGRAM.")
    except Exception as e:
        print("Error en el envío a Telegram:", e)

if __name__ == "__main__":
    probar_telegram()
