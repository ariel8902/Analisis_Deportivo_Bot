import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from google import genai

# ---------------------------------------------------------
# 1. CREDENCIALES SEGURAS Y CONFIGURACIÓN DE ENTORNO
# ---------------------------------------------------------
PANDASCORE_TOKEN = os.getenv("PANDASCORE_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

UMBRAL_MINIMO_FILTRO = 70.0
ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

LIGAS_PRIORITARIAS = [
    "WORLDS", "WORLD CHAMPIONSHIP", "MSI", "MID-SEASON INVITATIONAL",
    "LCK", "LPL", "LEC", "LCS", "VCS", "CBLOL", "PCS",
    "MAJOR", "IEM", "INTEL EXTREME MASTERS", "ESL PRO LEAGUE", 
    "BLAST", "BLAST PREMIER", "WORLD FINAL", "PGL", "CCT Europe"
]

class AnalisiseSportsSchema(BaseModel):
    prob_pick_principal: float = Field(description="Probabilidad estimada de la opción principal (0 a 100)")
    pick_principal: str = Field(description="Nombre exacto del mercado principal (ej. Total de Mapas > 2.5, Hándicap +1.5 Local)")
    stake_principal: str = Field(description="Stake sugerido (ej. 4/5)")
    prob_cobertura: float = Field(description="Probabilidad estimada de la cobertura (0 a 100)")
    pick_cobertura: str = Field(description="Nombre exacto de la cobertura (ej. Hándicap +1.5 Visitante)")
    analisis_tactico: str = Field(description="Justificación técnica sintética del partido en máximo 2 oraciones.")

def enviar_mensaje_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram eSports no configuradas.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML"}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            if res.status != 200:
                print(f"Telegram eSports respondió con código HTTP {res.status}")
    except Exception as e:
        print("Error enviando Telegram eSports:", e)

# ---------------------------------------------------------
# 2. INGESTA PANDASCORE CON FILTRO TEMPORAL
# ---------------------------------------------------------
def obtener_partidos_pandascore():
    if not PANDASCORE_TOKEN:
        print("Error: PANDASCORE_TOKEN no está configurada.")
        return []

    url = "https://api.pandascore.co/matches/upcoming?page[size]=25&sort=scheduled_at"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {PANDASCORE_TOKEN}", "Accept": "application/json"})
    
    partidos_filtrados = []
    ahora_utc = datetime.now(timezone.utc)
    limite_jornada = ahora_utc + timedelta(hours=20)

    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            if res.status == 200:
                eventos = json.loads(res.read().decode('utf-8'))
                for ev in eventos:
                    if ev.get("opponents") and len(ev["opponents"]) >= 2:
                        hora_raw = ev.get("scheduled_at", "")
                        if not hora_raw:
                            continue
                        try:
                            dt_utc = datetime.fromisoformat(hora_raw.replace("Z", "+00:00"))
                            if not (ahora_utc <= dt_utc <= limite_jornada):
                                continue
                            hora_fmt = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA).strftime("%H:%M")
                        except Exception:
                            continue

                        liga_nom = ev.get("league", {}).get("name", "")
                        torneo_nom = ev.get("tournament", {}).get("name", "")
                        liga_completa = f"{liga_nom} {torneo_nom}".strip().upper()
                        
                        if any(l in liga_completa for l in LIGAS_PRIORITARIAS):
                            eq1 = ev["opponents"][0]["opponent"]["name"]
                            eq2 = ev["opponents"][1]["opponent"]["name"]
                            num_mapas = ev.get("number_of_games", 3)
                            juego_nombre = ev.get("videogame", {}).get("name", "eSports")

                            if "league of legends" in juego_nombre.lower() or "lol" in juego_nombre.lower():
                                juego_formateado = "🎮 LoL"
                            elif "counter-strike" in juego_nombre.lower() or "cs" in juego_nombre.lower():
                                juego_formateado = "🔫 CS2"
                            else:
                                juego_formateado = f"🎮 {juego_nombre}"

                            partidos_filtrados.append({
                                "juego": juego_formateado,
                                "local": eq1,
                                "visitante": eq2,
                                "liga": liga_nom if liga_nom else liga_completa,
                                "num_mapas": num_mapas,
                                "hora": hora_fmt
                            })
    except Exception as e:
        print("Aviso al consultar PandaScore:", e)
        
    return partidos_filtrados

# ---------------------------------------------------------
# 3. EVALUACIÓN Y FILTRADO CON GEMINI IA (CON PAUSA Y REINTENTOS)
# ---------------------------------------------------------
def analizar_partido_esports_ia(partido):
    if not client_gemini:
        return None

    prompt = (
        f"Evalúa objetivamente el partido de eSports: {partido['local']} vs {partido['visitante']} ({partido['liga']}). "
        f"Formato del partido: Al mejor de {partido['num_mapas']} mapas (BO{partido['num_mapas']}).\n"
        f"Analiza la probabilidad real de los mercados: Total de Mapas (Over) y Hándicaps (+1.5 mapas).\n"
        f"Proporciona la probabilidad estimada (0-100) para la mejor opción y la opción de cobertura."
    )

    try:
        res = client_gemini.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": AnalisiseSportsSchema,
            }
        )
        if res and res.text:
            return json.loads(res.text)
    except Exception as e:
        print("Aviso en llamada a Gemini:", e)

    return None

# ---------------------------------------------------------
# 4. ORQUESTADOR Y DESPACHO
# ---------------------------------------------------------
def ejecutar_escaneo():
    fecha_colombia = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
    print(f"Iniciando escaneo de eSports: {fecha_colombia}")
    
    partidos = obtener_partidos_pandascore()
    
    if not partidos:
        mensaje = (
            f"🏆 <b>REPORTE ESPORTS - {fecha_colombia}</b>\n\n"
            f"<i>Sin partidos programados de ligas Tier-1 en las próximas 20 horas.</i>"
        )
        enviar_mensaje_telegram(mensaje)
        print("Finalizado: Sin partidos hoy.")
        return

    enviar_mensaje_telegram(f"🏆 <b>PRONÓSTICOS ESPORTS VIP</b> | Fecha: <b>{fecha_colombia}</b>")
    partidos_enviados = 0

    for p in partidos:
        # Pausa preventiva de 4 segundos para evitar Rate Limit (429) de Gemini
        time.sleep(4)

        analisis = None
        reintentos = 0

        # Lógica de reintento: Hasta 3 intentos si la IA no responde a la primera
        while reintentos < 3 and not analisis:
            analisis = analizar_partido_esports_ia(p)
            if not analisis:
                reintentos += 1
                print(f"Reintentando análisis IA para {p['local']} vs {p['visitante']} (Intento {reintentos})...")
                time.sleep(3)

        if not analisis:
            print(f"No se pudo obtener análisis de IA para {p['local']} vs {p['visitante']} tras 3 intentos.")
            continue

        prob_max = max(analisis.get("prob_pick_principal", 0), analisis.get("prob_cobertura", 0))

        # FILTRO ESTRICTO DE CERTEZA (MÍNIMO 70%)
        if prob_max < UMBRAL_MINIMO_FILTRO:
            continue

        mensaje = (
            f"🏆 <b>{p['juego']} - {p['liga']}</b> | {p['local']} vs {p['visitante']}\n"
            f"⏰ <b>Hora:</b> <code>{p['hora']}</code> <b>(BO{p['num_mapas']})</b>\n\n"
            f"🎯 <b>APUESTA PRINCIPAL: {analisis['pick_principal']}</b>\n"
            f"📊 <b>Probabilidad:</b> <code>{analisis['prob_pick_principal']}%</code> | <b>Stake:</b> <code>{analisis['stake_principal']}</code>\n"
            f"💡 <i>[Gemini] {analisis['analisis_tactico']}</i>\n\n"
            f"🛡️ <b>COBERTURA ALTERNATIVA:</b> {analisis['pick_cobertura']} (<code>{analisis['prob_cobertura']}%</code>)"
        )
        
        enviar_mensaje_telegram(mensaje)
        partidos_enviados += 1
        time.sleep(2)

    enviar_mensaje_telegram(f"<b>Escaneo eSports completado.</b> Pronósticos enviados: {partidos_enviados}")
    print(f"Proceso eSports completado. Enviados: {partidos_enviados}")

if __name__ == "__main__":
    ejecutar_escaneo()
