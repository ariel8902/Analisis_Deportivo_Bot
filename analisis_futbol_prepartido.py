import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from google import genai

# ---------------------------------------------------------
# 1. CONFIGURACIÓN Y CREDENCIALES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

# ---------------------------------------------------------
# 2. IA DE GEMINI PARA OBTENER Y ANALIZAR PARTIDOS
# ---------------------------------------------------------
def obtener_analisis_ia_gemini():
    if not client_gemini:
        return []

    fecha_hoy = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
    
    prompt = f"""Actúa como el motor principal de análisis deportivo y búsqueda de fútbol prepartido.
Fecha de evaluación (Colombia): {fecha_hoy}.

TAREA:
1. Busca e identifica los partidos principales de fútbol programados para HOY y MAÑANA en la Liga BetPlay (Colombia), Premier League, LaLiga, Serie A, Bundesliga, Ligue 1 o Champions League.
2. Para cada partido encontrado, analiza la tendencia del mercado 'AMBOS EQUIPOS ANOTAN' (BTTS) y el Over/Under de goles.
3. Genera una justificación táctica de máximo 2 oraciones por encuentro.

Responde ÚNICAMENTE con una lista JSON válida con la siguiente estructura de objetos:
[
  {{
    "liga": "Nombre de la Liga",
    "local": "Equipo Local",
    "visitante": "Equipo Visitante",
    "fechaHora": "Hora o Fecha (Ejemplo: Hoy 06:15 PM)",
    "cuotaLocal": "Cuota o N/A",
    "cuotaEmpate": "Cuota o N/A",
    "cuotaVisitante": "Cuota o N/A",
    "prob_btts": "Porcentaje estimado (Ejemplo: 65%)",
    "ambos_marcan_pronostico": "SÍ" o "NO",
    "stake": "Stake (Ejemplo: 4/5)",
    "cobertura_goles": "Línea de gol (Ejemplo: Más de 1.5 Goles)",
    "justificacion": "Texto táctico de 2 oraciones."
  }}
]"""

    try:
        res = client_gemini.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt
        )
        
        texto_resp = res.text.strip() if res.text else ""
        if "```json" in texto_resp:
            texto_resp = texto_resp.split("```json")[1].split("```")[0].strip()
        elif "```" in texto_resp:
            texto_resp = texto_resp.split("```")[1].split("```")[0].strip()

        return json.loads(texto_resp)
    except Exception as e:
        print("Error en extracción IA Gemini:", e)
        return []

# ---------------------------------------------------------
# 3. DESPACHO A TELEGRAM
# ---------------------------------------------------------
def enviar_mensaje_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram no configuradas en Secrets.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        print("Respuesta Telegram HTTP:", res.status_code)
    except Exception as e:
        print("Error enviando a Telegram:", e)

def ejecutar_bot_futbol():
    fecha_colombia = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d %I:%M %p")
    enviar_mensaje_telegram(f"🎯 <b>SUPERANALISTA PRO - ESPECIALISTA AMBOS MARCAN</b>\n📅 Escaneo e IA Activa: <b>{fecha_colombia}</b>")

    partidos_analizados = obtener_analisis_ia_gemini()

    if not partidos_analizados:
        enviar_mensaje_telegram(f"🛡️ <b>REPORTE DE JORNADA</b>\n\n📊 <i>No se registraron partidos en el escaneo de la IA.</i>")
        return

    for p in partidos_analizados:
        mensaje = (
            f"🏆 <b>{p.get('liga', 'Fútbol')}</b>\n"
            f"⚽ <b>{p.get('local', 'Local')} vs {p.get('visitante', 'Visitante')}</b>\n"
            f"⏰ Horario: <code>{p.get('fechaHora', 'Hoy')} (Hora COL)</code>\n\n"
            f"📊 <b>Cuotas 1X2:</b> L: <code>{p.get('cuotaLocal', '2.10')}</code> | E: <code>{p.get('cuotaEmpate', '3.10')}</code> | V: <code>{p.get('cuotaVisitante', '3.20')}</code>\n"
            f"🎲 <b>Probabilidad Both Score:</b> <code>{p.get('prob_btts', '60%')}</code>\n\n"
            f"🔥 <b>PRONÓSTICO PRINCIPAL:</b>\n"
            f"🎯 <b>Ambos Equipos Anotan:</b> <b>{p.get('ambos_marcan_pronostico', 'SÍ')}</b>\n"
            f"📈 <b>Confianza / Stake:</b> <code>{p.get('stake', '4/5')}</code>\n"
            f"💡 <i>{p.get('justificacion', 'Análisis enfocado en potencia ofensiva y balance defensivo.')}</i>\n\n"
            f"🛡️ <b>OPCIÓN COBERTURA (GOLES):</b>\n"
            f"🎯 <b>Línea Alternativa:</b> {p.get('cobertura_goles', 'Más de 1.5 Goles')}"
        )

        enviar_mensaje_telegram(mensaje)
        time.sleep(2)

    enviar_mensaje_telegram(f"✅ <b>Análisis completado con Gemini IA.</b> Partidos procesados: {len(partidos_analizados)}")

if __name__ == "__main__":
    ejecutar_bot_futbol()
