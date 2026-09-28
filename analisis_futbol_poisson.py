import os
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
APISPORTS_KEY = os.getenv("APISPORTS_KEY")
ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

LIGAS_CONFIGURADAS = [
    { "nombre": "🇨🇴 Liga BetPlay", "id_liga": 239, "temporada": 2026 },
    { "nombre": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League", "id_liga": 39, "temporada": 2026 }
]

def enviar_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={ "chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML" }, timeout=8)

def depurar_api_en_vivo():
    hoy_str = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
    print(f"🔬 MODO DIAGNÓSTICO ACTIVO - Consultando fecha: {hoy_str}")
    
    url_api = "https://v3.football.api-sports.io/fixtures"
    headers = { "x-apisports-key": APISPORTS_KEY }

    for liga in LIGAS_CONFIGURADAS:
        params = { "league": liga["id_liga"], "season": liga["temporada"], "date": hoy_str }
        print(f"\n--- Probando {liga['nombre']} (ID: {liga['id_liga']}, Temporada: {liga['temporada']}) ---")
        try:
            res = requests.get(url_api, headers=headers, params=params, timeout=10)
            print(f"Código HTTP API: {res.status_code}")
            data = res.json()
            print("Respuesta cruda de la API:", data)
            resultados = data.get("response", [])
            print(f"Total partidos encontrados en la respuesta: {len(resultados)}")
        except Exception as e:
            print("Error en la petición:", e)

    enviar_telegram("🛠️ <b>DIAGNÓSTICO EJECUTADO</b>\nRevisa los logs de GitHub Actions para ver la respuesta exacta de la API.")

if __name__ == "__main__":
    depurar_api_en_vivo()
