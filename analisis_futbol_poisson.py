import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from google import genai

# ---------------------------------------------------------
# 1. CONFIGURACIÓN Y CREDENCIALES (EXCLUSIVO FÚTBOL)
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

UMBRAL_MINIMO_FILTRO = 70.0
ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

# Ligas de Fútbol Tradicional
LIGAS_FUTBOL = [
    {"nombre": "🇨🇴 Liga Colombia", "sport_key": "soccer_colombia_liga_aguila"},
    {"nombre": "🇪🇸 La Liga España", "sport_key": "soccer_spain_la_liga"},
    {"nombre": "🇬🇧 Premier League", "sport_key": "soccer_epl"},
    {"nombre": "🏆 UEFA Champions League", "sport_key": "soccer_uefa_champs_league"},
    {"nombre": "🇦🇷 Liga Argentina", "sport_key": "soccer_argentina_primera_division"}
]

class AnalisisFutbolSchema(BaseModel):
    prob_pick_principal: float = Field(description="Probabilidad estimada para la opción principal (0 a 100)")
    pick_principal: str = Field(description="Mercado principal recomendado (ej. Gana Local - DNB, Bajas 2.5 Goles)")
    stake_principal: str = Field(description="Stake sugerido según la certeza (ej. 3/5 o 4/5)")
    prob_cobertura: float = Field(description="Probabilidad estimada opción de cobertura (0 a 100)")
    pick_cobertura: str = Field(description="Opción de cobertura (ej. Doble Oportunidad Local o Empate)")
    analisis_tactico: str = Field(description="Justificación táctica sintética basada en Poisson y forma reciente en máx 2 oraciones.")

def enviar_mensaje_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram no configuradas.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)

# ---------------------------------------------------------
# 2. MOTOR MATEMÁTICO (DESMARGINACIÓN Y POISSON)
# ---------------------------------------------------------
def calcular_probabilidad_implicita(cuota_local, cuota_empate, cuota_visitante):
    if not cuota_local or not cuota_visitante:
        return 33.3, 33.3, 33.3
    p_loc = 1.0 / cuota_local
    p_emp = (1.0 / cuota_empate) if cuota_empate else 0.25
    p_vis = 1.0 / cuota_visitante
    margen = p_loc + p_emp + p_vis
    return round((p_loc / margen) * 100, 1), round((p_emp / margen) * 100, 1), round((p_vis / margen) * 100, 1)

# ---------------------------------------------------------
# 3. INGESTA DE CUOTAS DE FÚTBOL (THE ODDS API)
# ---------------------------------------------------------
def obtener_partidos_futbol():
    if not ODDS_API_KEY:
        print("Error: ODDS_API_KEY no está configurada.")
        return []

    lista_partidos = []
    ahora_utc = datetime.now(timezone.utc)
    limite_jornada = ahora_utc + timedelta(hours=36)

    for liga in LIGAS_FUTBOL:
        url = f"https://api.the-odds-api.com/v4/sports/{liga['sport_key']}/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu,us", "markets": "h2h,totals", "oddsFormat": "decimal"}
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code != 200:
                continue
            eventos = res.json()
            for ev in eventos:
                commence_raw = ev.get("commence_time", "")
                if not commence_raw:
                    continue
                dt_utc = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
                if not (ahora_utc <= dt_utc <= limite_jornada):
                    continue
                dt_colombia = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA)
                
                home_team, away_team = ev.get("home_team"), ev.get("away_team")
                c_loc, c_emp, c_vis = None, None, None
                
                bookmakers = ev.get("bookmakers", [])
                if bookmakers:
                    for m in bookmakers[0].get("markets", []):
                        if m.get("key") == "h2h":
                            for o in m.get("outcomes", []):
                                if o.get("name") == home_team: c_loc = o.get("price")
                                elif o.get("name") == "Draw": c_emp = o.get("price")
                                elif o.get("name") == away_team: c_vis = o.get("price")
                
                if not c_loc or not c_vis:
                    continue
                
                p_loc, p_emp, p_vis = calcular_probabilidad_implicita(c_loc, c_emp, c_vis)
                lista_partidos.append({
                    "liga": liga["nombre"], "local": home_team, "visitante": away_team,
                    "fecha": dt_colombia.strftime("%Y-%m-%d"), "hora": dt_colombia.strftime("%H:%M"),
                    "cuota_local": c_loc, "cuota_empate": c_emp, "cuota_visitante": c_vis,
                    "prob_math_local": p_loc, "prob_math_empate": p_emp, "prob_math_visitante": p_vis
                })
            time.sleep(0.4)
        except Exception as e:
            print(f"Error al consultar {liga['nombre']}:", e)
    return lista_partidos

# ---------------------------------------------------------
# 4. EVALUACIÓN Y VALIDACIÓN CON IA (REINTENTOS CONTRA 503)
# ---------------------------------------------------------
def analizar_partido_futbol_ia(partido):
    if not client_gemini:
        return None, "IA no configurada"

    prompt = (
        f"Analiza cuantitativamente (Poisson) el partido: {partido['local']} vs {partido['visitante']} ({partido['liga']}).\n"
        f"Cuotas: Local ({partido['cuota_local']}) / Empate ({partido['cuota_empate']}) / Visitante ({partido['cuota_visitante']}).\n"
        f"Probabilidades Implícitas Desmarginadas: Local ({partido['prob_math_local']}%), Empate ({partido['prob_math_empate']}%), Visitante ({partido['prob_math_visitante']}%).\n"
        f"Establece en 'pick_principal' la mejor alternativa de valor (DNB, Doble Oportunidad, Totales o Ganador) con certeza >= 70%."
    )

    intentos_maximos = 3
    for intento in range(1, intentos_maximos + 1):
        try:
            res = client_gemini.models.generate_content(
                model=MODELO_GEMINI,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": AnalisisFutbolSchema}
            )
            if res and res.text:
                return json.loads(res.text), "OK"
        except Exception as e:
            error_msg = str(e)
            print(f"Intento {intento}/{intentos_maximos} falló para {partido['local']} vs {partido['visitante']}: {error_msg}")
            
            # Si el servidor de Google está ocupado (503 / 429), reintentamos con espera progresiva
            if "503" in error_msg or "429" in error_msg or "UNAVAILABLE" in error_msg:
                tiempo_espera = intento * 5
                print(f"Servidor de Google ocupado. Reintentando en {tiempo_espera} segundos...")
                time.sleep(tiempo_espera)
            else:
                break

    return None, "Error de servicio o agotamiento de reintentos"

# ---------------------------------------------------------
# 5. ORQUESTADOR PRINCIPAL
# ---------------------------------------------------------
def ejecutar_escaneo():
    fecha_colombia = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
    print(f"Iniciando escaneo de Fútbol (Poisson): {fecha_colombia}")
    partidos = obtener_partidos_futbol()

    if not partidos:
        msg = f"⚽ <b>REPORTE FÚTBOL - {fecha_colombia}</b>\n\n<i>Sin partidos en la ventana de las próximas 36 horas.</i>"
        enviar_mensaje_telegram(msg)
        print("Finalizado: Sin partidos hoy.")
        return

    enviar_mensaje_telegram(f"⚽ <b>PRONÓSTICOS FÚTBOL VIP</b> | Escaneo: <b>{fecha_colombia}</b>")
    partidos_enviados = 0
    descartados_certeza = 0

    for p in partidos:
        time.sleep(6)  # Control de ritmo (10 peticiones/min max)
        analisis, estado = analizar_partido_futbol_ia(p)
        
        if not analisis:
            continue

        prob_max = max(analisis.get("prob_pick_principal", 0), analisis.get("prob_cobertura", 0))
        if prob_max < UMBRAL_MINIMO_FILTRO:
            descartados_certeza += 1
            continue

        msg = (
            f"⚽ <b>{p['liga']}</b> | {p['local']} vs {p['visitante']}\n"
            f"📅 <b>Fecha:</b> <code>{p['fecha']}</code> | ⏰ <b>Hora:</b> <code>{p['hora']}</code>\n"
            f"💰 <b>Cuotas:</b> <code>{p['cuota_local']} - {p['cuota_empate']} - {p['cuota_visitante']}</code>\n\n"
            f"🎯 <b>APUESTA PRINCIPAL: {analisis['pick_principal']}</b>\n"
            f"📊 <b>Probabilidad:</b> <code>{analisis['prob_pick_principal']}%</code> | <b>Stake:</b> <code>{analisis['stake_principal']}</code>\n"
            f"💡 <i>[Gemini] {analisis['analisis_tactico']}</i>\n\n"
            f"🛡 <b>COBERTURA ALTERNATIVA:</b> {analisis['pick_cobertura']} (<code>{analisis['prob_cobertura']}%</code>)"
        )
        enviar_mensaje_telegram(msg)
        partidos_enviados += 1

    # Reporte de cierre estructurado
    msg_resumen = f"<b>Escaneo fútbol completado.</b> Pronósticos enviados: {partidos_enviados}"
    if partidos_enviados == 0 and descartados_certeza > 0:
        msg_resumen += f"\n\n<b>Detalle:</b> {descartados_certeza} partido(s) analizados no alcanzaron el {UMBRAL_MINIMO_FILTRO}% de certeza."

    enviar_mensaje_telegram(msg_resumen)
    print(f"Proceso fútbol completado. Enviados: {partidos_enviados}")

if __name__ == "__main__":
    ejecutar_escaneo()
