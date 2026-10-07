import math
import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. CONFIGURACIÓN Y CREDENCIALES (FÚTBOL ANCLADO A CUOTAS REALES)
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

UMBRAL_MINIMO_FILTRO = 75.0  # FILTRO DE RIGOR COMERCIAL
ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

LIGAS_FUTBOL = [
    {"nombre": "⚽ Champions League", "sport_key": "soccer_uefa_champs_league"},
    {"nombre": "⚽ Europa League", "sport_key": "soccer_uefa_europa_league"},
    {"nombre": "⚽ Premier League (Inglaterra)", "sport_key": "soccer_epl"},
    {"nombre": "⚽ LaLiga (España)", "sport_key": "soccer_spain_la_liga"},
    {"nombre": "⚽ Serie A (Italia)", "sport_key": "soccer_italy_serie_a"},
    {"nombre": "⚽ Bundesliga (Alemania)", "sport_key": "soccer_germany_bundesliga"},
    {"nombre": "⚽ Liga BetPlay (Colombia)", "sport_key": "soccer_colombia_liga_dimayor"},
    {"nombre": "⚽ Copa Libertadores", "sport_key": "soccer_conmebol_copa_libertadores"}
]

class AnalisisFutbolSchema(BaseModel):
    prob_pick_principal: float = Field(description="Probabilidad estimada final (0 a 100)")
    pick_principal: str = Field(description="Mercado comercial disponible en BetPlay (ej. Gana Local ML, Over 2.5 Goles, Ambos Anotan)")
    regla_valor_betplay: str = Field(description="Rango de cuota exacto en BetPlay para validar la apuesta. Indica explícitamente cuándo ABSTENERSE si la cuota es sospechosamente alta.")
    stake_principal: str = Field(description="Stake sugerido según certeza (ej. 3/5 o 4/5)")
    prob_cobertura: float = Field(description="Probabilidad estimada cobertura (0 a 100)")
    pick_cobertura: str = Field(description="Opción de cobertura accesible en BetPlay (ej. Over 1.5 Goles o Doble Oportunidad)")
    analisis_tactico: str = Field(description="Justificación táctica basada en xG, bajas y coherencia de cuota en máx 2 oraciones.")

def enviar_mensaje_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram no configuradas.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)
        return False

def calcular_poisson(k, lambda_param):
    return (math.pow(lambda_param, k) * math.exp(-lambda_param)) / math.factorial(k)

def calcular_probabilidades_poisson(xg_local, xg_visita):
    prob_over_1_5, prob_over_2_5, prob_btts = 0.0, 0.0, 0.0
    for gl in range(6):
        p_l = calcular_poisson(gl, xg_local)
        for gv in range(6):
            p_v = calcular_poisson(gv, xg_visita)
            p_res = p_l * p_v
            if (gl + gv) > 1: prob_over_1_5 += p_res
            if (gl + gv) > 2: prob_over_2_5 += p_res
            if gl > 0 and gv > 0: prob_btts += p_res
    return {
        "poisson_over_1_5": round(prob_over_1_5 * 100, 1),
        "poisson_over_2_5": round(prob_over_2_5 * 100, 1),
        "poisson_btts": round(prob_btts * 100, 1)
    }

def obtener_partidos_futbol():
    if not ODDS_API_KEY:
        print("Error: ODDS_API_KEY no configurada.")
        return []

    lista_partidos = []
    ahora_utc = datetime.now(timezone.utc)
    fin_ventana_utc = ahora_utc + timedelta(hours=12)

    for liga in LIGAS_FUTBOL:
        url = f"https://api.the-odds-api.com/v4/sports/{liga['sport_key']}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu,us",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code != 200:
                continue
            eventos = res.json()
            for ev in eventos:
                commence_raw = ev.get("commence_time", "")
                if not commence_raw:
                    continue
                dt_utc = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
                
                if not (ahora_utc <= dt_utc <= fin_ventana_utc):
                    continue

                dt_colombia = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA)
                home_team, away_team = ev.get("home_team"), ev.get("away_team")
                c_loc, c_emp, c_vis = None, None, None
                
                bookmakers = ev.get("bookmakers", [])
                if bookmakers:
                    bm = bookmakers[0]
                    for m in bm.get("markets", []):
                        if m.get("key") == "h2h":
                            for o in m.get("outcomes", []):
                                if o.get("name") == home_team: c_loc = o.get("price")
                                elif o.get("name") == away_team: c_vis = o.get("price")
                                elif o.get("name") == "Draw": c_emp = o.get("price")

                if not c_loc or not c_vis:
                    continue

                # Estimación contextual de xG derivada de las probabilidades implícitas del mercado real
                p_loc = (1.0 / c_loc)
                p_vis = (1.0 / c_vis)
                xg_local_est = round(p_loc * 2.6, 2)
                xg_visita_est = round(p_vis * 2.2, 2)

                stats_poisson = calcular_probabilidades_poisson(xg_local_est, xg_visita_est)

                lista_partidos.append({
                    "liga": liga["nombre"],
                    "local": home_team,
                    "visita": away_team,
                    "fecha": dt_colombia.strftime("%Y-%m-%d"),
                    "hora": dt_colombia.strftime("%I:%M %p"),
                    "cuota_local": c_loc,
                    "cuota_empate": c_emp,
                    "cuota_visita": c_vis,
                    "poisson": stats_poisson
                })
            time.sleep(0.3)
        except Exception as e:
            print(f"Error consultando {liga['nombre']}:", e)
    return lista_partidos

def analizar_partido_futbol_ia(p):
    if not client_gemini:
        return None, "IA no configurada"

    prompt = (
        f"Analiza el partido de fútbol para las PRÓXIMAS 12 HORAS: {p['local']} vs {p['visita']} ({p['liga']}).\n"
        f"Cuotas Reales de Casa: Local ({p['cuota_local']}) / Empate ({p['cuota_empate']}) / Visitante ({p['cuota_visita']}).\n"
        f"Poisson Derivado: Over 1.5 ({p['poisson']['poisson_over_1_5']}%), Over 2.5 ({p['poisson']['poisson_over_2_5']}%), BTTS ({p['poisson']['poisson_btts']}%).\n\n"
        f"REGLA DE SEGURIDAD Y COHERENCIA COMERCIAL:\n"
        f"1. Tu 'pick_principal' DEBE SER OBLIGATORIAMENTE un mercado disponible en BetPlay (Ganador ML, Over/Under Goles, Ambos Anotan, Doble Oportunidad).\n"
        f"2. NUNCA propongas un equipo como 'favorito claro' si su cuota en la casa de apuestas supera 2.20. Si la cuota real es alta, adáptate a mercados de goles o coberturas.\n"
        f"3. En 'regla_valor_betplay' entrega el RANGO DE CUOTA PERMITIDO para entrar. Si la cuota en BetPlay está fuera del rango por información de última hora, manda a ABSTENERSE."
    )

    try:
        res = client_gemini.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AnalisisFutbolSchema,
                temperature=0.10
            )
        )
        if res and res.text:
            return json.loads(res.text), "OK"
    except Exception as e:
        print(f"Error evaluando {p['local']} vs {p['visita']}: {e}")
        return None, str(e)

    return None, "ERROR_GENERAL"

def ejecutar_escaneo():
    ahora_colombia = datetime.now(ZONA_HORARIA_COLOMBIA)
    fecha_hora_col = ahora_colombia.strftime("%Y-%m-%d %I:%M %p")
    print(f"Iniciando escaneo de Fútbol (Cuotas Reales BetPlay - Filtro 75%): {fecha_hora_col}")
    
    partidos = obtener_partidos_futbol()

    if not partidos:
        msg = f"⚽ <b>REPORTE FÚTBOL POISSON</b>\n<i>Escaneo: {fecha_hora_col}</i>\n\n<i>Sin partidos programados con cuotas para las próximas 12 horas.</i>"
        enviar_mensaje_telegram(msg)
        return

    enviar_mensaje_telegram(f"⚽ <b>PRONÓSTICOS FÚTBOL VIP (BETPLAY READY)</b>\n<i>Escaneo: {fecha_hora_col}</i>")
    
    partidos_enviados = 0
    descartados_certeza = 0

    for p in partidos:
        time.sleep(1.5)
        analisis, estado = analizar_partido_futbol_ia(p)

        if not analisis:
            continue

        prob_max = max(analisis.get("prob_pick_principal", 0), analisis.get("prob_cobertura", 0))
        if prob_max < UMBRAL_MINIMO_FILTRO:
            descartados_certeza += 1
            continue

        msg = (
            f"⚽ <b>{p['liga']}</b> | {p['local']} vs {p['visita']}\n"
            f"📅 <b>Fecha:</b> <code>{p['fecha']}</code> | ⏰ <b>Hora Col:</b> <code>{p['hora']}</code>\n"
            f"💰 <b>Cuotas Reales:</b> <code>L: {p['cuota_local']} | E: {p['cuota_empate']} | V: {p['cuota_visita']}</code>\n"
            f"📊 <b>Poisson Base:</b> <code>Over 1.5: {p['poisson']['poisson_over_1_5']}% | BTTS: {p['poisson']['poisson_btts']}%</code>\n\n"
            f"🎯 <b>APUESTA PRINCIPAL: {analisis['pick_principal']}</b>\n"
            f"📲 <b>Regla de Validación BetPlay:</b> <i>{analisis['regla_valor_betplay']}</i>\n"
            f"📈 <b>Probabilidad:</b> <code>{analisis['prob_pick_principal']}%</code> | <b>Stake:</b> <code>{analisis['stake_principal']}</code>\n"
            f"💡 <i>[Gemini] {analisis['analisis_tactico']}</i>\n\n"
            f"🛡 <b>COBERTURA ALTERNATIVA:</b> {analisis['pick_cobertura']} (<code>{analisis['prob_cobertura']}%</code>)"
        )
        
        exito_envio = enviar_mensaje_telegram(msg)
        if exito_envio:
            partidos_enviados += 1
            print(f"✅ Enviado a Telegram: {p['local']} vs {p['visita']}")

    msg_resumen = f"<b>Escaneo fútbol completado.</b> Pronósticos enviados: {partidos_enviados}"
    if partidos_enviados == 0 and descartados_certeza > 0:
        msg_resumen += f"\n\n<b>Detalle:</b> {descartados_certeza} partido(s) descartados por no alcanzar el {UMBRAL_MINIMO_FILTRO}% de certeza."

    enviar_mensaje_telegram(msg_resumen)

if __name__ == "__main__":
    ejecutar_escaneo()
