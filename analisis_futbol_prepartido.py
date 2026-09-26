import os
import math
import json
import time
import random
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. CONFIGURACIÓN Y CREDENCIALES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

UMBRAL_MINIMO_FILTRO = 70.0
NUM_SIMULACIONES_MONTECARLO = 10000
ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

MODELO_OFICIAL = 'gemini-3.8-flash'

# PALABRAS CLAVE PERMITIDAS
PALABRAS_CLAVE_LIGAS = [
    "COLOMBIA", "PRIMERA A", "BETPLAY", "LALIGA", "PREMIER", 
    "SERIE A", "BUNDESLIGA", "LIGUE 1", "CHAMPIONS", "EUROPA LEAGUE"
]

# PALABRAS CLAVE EXCLUIDAS (FILTRADO ESTRICTO DE CATEGORÍAS INFERIORES)
EXCLUSIONES_LIGAS = ["UNDER-21", "U21", "SUB-21", "SUB 21", "UNDER-20", "U20", "WOMEN", "FEMENINO"]

class AjusteFuerzaSchema(BaseModel):
    posicion_exacta_local: str = Field(description="Puesto exacto en la tabla del equipo local, ej: '3°'")
    posicion_exacta_visitante: str = Field(description="Puesto exacto en la tabla del equipo visitante, ej: '5°'")
    factor_ajuste_local: float = Field(description="Factor de ajuste de fuerza local (1.0 neutro)")
    factor_ajuste_visitante: float = Field(description="Factor de ajuste de fuerza visitante (1.0 neutro)")

# ---------------------------------------------------------
# 2. MOTOR CUANTITATIVO GENERALIZADO (DIXON-COLES + MONTE CARLO)
# ---------------------------------------------------------
def poisson_pmf(k, lambda_param):
    if lambda_param <= 0:
        return 1.0 if k == 0 else 0.0
    return (lambda_param ** k) * math.exp(-lambda_param) / math.factorial(k)

def factor_dixon_coles(x, y, lambda_loc, lambda_vis, rho=-0.11):
    if x == 0 and y == 0:
        return 1.0 - (lambda_loc * lambda_vis * rho)
    elif x == 1 and y == 0:
        return 1.0 + (lambda_vis * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lambda_loc * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0

def generar_matriz_dixon_coles(lambda_loc, lambda_vis, max_goles=6):
    matriz = {}
    for i in range(max_goles + 1):
        p_i = poisson_pmf(i, lambda_loc)
        for j in range(max_goles + 1):
            p_j = poisson_pmf(j, lambda_vis)
            tau = factor_dixon_coles(i, j, lambda_loc, lambda_vis)
            matriz[(i, j)] = max(p_i * p_j * tau, 0.0)
    return matriz

def simular_monte_carlo(matriz_prob, num_simulaciones=10000, k_altitud=1.0, k_temperatura=1.0, lambda_tot=2.5):
    resultados = list(matriz_prob.keys())
    pesos = list(matriz_prob.values())
    
    partidos_simulados = random.choices(resultados, weights=pesos, k=num_simulaciones)
    
    cierre_1, cierre_x, cierre_2 = 0, 0, 0
    over_15, over_25, under_25 = 0, 0, 0
    btts_si, btts_no = 0, 0

    for i, j in partidos_simulados:
        if i > j:
            cierre_1 += 1
        elif i == j:
            cierre_x += 1
        else:
            cierre_2 += 1
            
        total = i + j
        if total > 1.5:
            over_15 += 1
        if total > 2.5:
            over_25 += 1
        else:
            under_25 += 1
            
        if i > 0 and j > 0:
            btts_si += 1
        else:
            btts_no += 1

    p_1 = (cierre_1 / num_simulaciones) * 100
    p_x = (cierre_x / num_simulaciones) * 100
    p_2 = (cierre_2 / num_simulaciones) * 100
    p_1x = p_1 + p_x
    p_x2 = p_2 + p_x
    
    p_over15 = (over_15 / num_simulaciones) * 100
    p_under25 = (under_25 / num_simulaciones) * 100
    p_btts_si = (btts_si / num_simulaciones) * 100
    p_btts_no = (btts_no / num_simulaciones) * 100

    p_corners_over85 = min(round(((lambda_tot / 3.2) * 68.0) * k_altitud, 1), 78.0)
    p_tarjetas_over45 = min(round(((lambda_tot / 3.0) * 65.0) * k_temperatura, 1), 76.0)

    opciones_principales = [
        ("Doble Oportunidad: 1X (Gana Local o Empate)", round(p_1x, 1)),
        ("Doble Oportunidad: X2 (Gana Visitante o Empate)", round(p_x2, 1)),
        ("Goles: Over 1.5 Total", round(p_over15, 1)),
        ("Goles: Under 2.5 Total", round(p_under25, 1)),
        ("Ambos Anotan: SÍ", round(p_btts_si, 1)),
        ("Ambos Anotan: NO", round(p_btts_no, 1)),
    ]

    opciones_secundarias = [
        ("Tiros de Esquina: Over 8.5", p_corners_over85),
        ("Tarjetas: Over 4.5", p_tarjetas_over45)
    ]

    principales_ordenadas = sorted(opciones_principales, key=lambda x: x[1], reverse=True)
    secundarias_ordenadas = sorted(opciones_secundarias, key=lambda x: x[1], reverse=True)

    top_opcion, top_prob = principales_ordenadas[0]

    todas_ordenadas = principales_ordenadas[:2] + secundarias_ordenadas[:1]
    todas_ordenadas = sorted(todas_ordenadas, key=lambda x: x[1], reverse=True)

    opciones_destacadas = []
    for opt, prob in todas_ordenadas:
        marca = "⭐️" if prob >= UMBRAL_MINIMO_FILTRO else "🔹"
        opciones_destacadas.append(f"{marca} {opt}: `{prob}%`")

    return {
        "top_pick": top_opcion,
        "top_prob": top_prob,
        "over_1_5": round(p_over15, 1),
        "btts_si": round(p_btts_si, 1),
        "opciones_destacadas": opciones_destacadas
    }

def evaluar_partido_completo(lambda_loc, lambda_vis, k_altitud=1.0, k_temperatura=1.0, k_motivacion=1.0):
    lambda_loc_adj = lambda_loc * k_altitud * k_motivacion
    lambda_vis_adj = lambda_vis * (2.0 - k_altitud)
    matriz_teorica = generar_matriz_dixon_coles(lambda_loc_adj, lambda_vis_adj)
    return simular_monte_carlo(matriz_teorica, num_simulaciones=NUM_SIMULACIONES_MONTECARLO, k_altitud=k_altitud, k_temperatura=k_temperatura, lambda_tot=lambda_loc_adj + lambda_vis_adj)

# ---------------------------------------------------------
# 3. AGENDA FILTRADA FLEXIBLE + VALIDACIÓN ROBUSTA EN GEMINI
# ---------------------------------------------------------
def analizar_partido_con_gemini(local, visitante, liga):
    factor_loc, factor_vis = 1.0, 1.0
    pos_local, pos_visita = "En tabla", "En tabla"

    if client:
        fecha_hoy = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
        prompt = (
            f"Investiga en Google Search el partido de hoy ({fecha_hoy}): {local} vs {visitante} ({liga}).\n"
            f"Obtén el puesto exacto en la tabla de posiciones de cada equipo y estima el factor de ajuste de fuerza."
        )
        
        # Bucle de reintento para evitar fallas por rate limit (429)
        for intento in range(2):
            try:
                time.sleep(4)
                response = client.models.generate_content(
                    model=MODELO_OFICIAL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        response_mime_type="application/json",
                        response_schema=AjusteFuerzaSchema,
                    )
                )
                if response.text:
                    data = json.loads(response.text)
                    factor_loc = float(data.get("factor_ajuste_local", 1.0))
                    factor_vis = float(data.get("factor_ajuste_visitante", 1.0))
                    pl = str(data.get("posicion_exacta_local", "")).strip()
                    pv = str(data.get("posicion_exacta_visitante", "")).strip()
                    if pl and "DESCONOCIDO" not in pl.upper():
                        pos_local = pl if "°" in pl else f"{pl}°"
                    if pv and "DESCONOCIDO" not in pv.upper():
                        pos_visita = pv if "°" in pv else f"{pv}°"
                    break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    print(f"Límite de frecuencia (429) en {local} vs {visitante}. Pausando 10s...")
                    time.sleep(10)
                else:
                    print("Aviso al consultar Gemini:", e)
                    break

    stats = evaluar_partido_completo(1.40 * factor_loc, 1.10 * factor_vis)
    return pos_local, pos_visita, stats

def obtener_jornada_completa():
    fecha_hoy = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
    print(f"Iniciando consulta de agenda para la fecha {fecha_hoy}...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    url_tsdb = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={fecha_hoy}&s=Soccer"
    req = urllib.request.Request(url_tsdb, headers=headers)
    
    partidos_analizados = []
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            if res.status == 200:
                data = json.loads(res.read().decode('utf-8'))
                eventos = data.get("events", [])
                
                if eventos:
                    for ev in eventos:
                        liga = ev.get("strLeague", "").strip()
                        liga_upper = liga.upper()
                        
                        # VERIFICACIÓN: INCLUIR PERMITIDAS Y EXCLUIR MENORES
                        es_permitida = any(kw in liga_upper for kw in PALABRAS_CLAVE_LIGAS)
                        es_excluida = any(ex in liga_upper for ex in EXCLUSIONES_LIGAS)

                        if es_permitida and not es_excluida:
                            local = ev.get("strHomeTeam", "Local")
                            visitante = ev.get("strAwayTeam", "Visitante")
                            hora_str = ev.get("strTime", "00:00:00")
                            
                            pos_loc, pos_vis, stats = analizar_partido_con_gemini(local, visitante, liga)
                            
                            hora_fmt = f"{fecha_hoy} — {hora_str[:5]}"
                            partidos_analizados.append({
                                "liga": liga_upper,
                                "local": local,
                                "visitante": visitante,
                                "pos_local": pos_loc,
                                "pos_visita": pos_vis,
                                "hora_fecha": hora_fmt,
                                "stats": stats
                            })
    except Exception as e:
        print(f"Error consultando la API de eventos: {e}")

    return partidos_analizados

# ---------------------------------------------------------
# 4. DESPACHO DE REPORTES A TELEGRAM
# ---------------------------------------------------------
def enviar_mensaje_telegram(token, chat_id, texto):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id, 
        "text": texto, 
        "parse_mode": "Markdown"
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            print("Reporte despachado a Telegram. Código HTTP:", res.status)
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)

def enviar_reporte_telegram(partidos):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram faltantes.")
        return

    if not partidos:
        fecha_actual = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
        mensaje = (
            f"🛡️ **REPORTE DE JORNADA - {fecha_actual}**\n\n"
            f"📊 *No se registran partidos programados en las ligas de primera categoría para el día de hoy.*\n\n"
            f"💡 *El sistema reanudará las simulaciones en la siguiente fecha con agenda activa.*"
        )
        enviar_mensaje_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)
        return

    for p in partidos:
        st = p["stats"]
        destacadas = "\n".join(st["opciones_destacadas"])

        mensaje = (
            f"⚽️ **ANÁLISIS PREPARTIDO**\n"
            f"🏆 **{p['liga']}**\n"
            f"⚔️ **{p['local']} vs {p['visitante']}**\n"
            f"📌 **Posición en Tabla:** `{p['local']}` ({p['pos_local']}) vs `{p['visitante']}` ({p['pos_visita']})\n"
            f"🕓 `{p['hora_fecha']}`\n\n"
            f"🎯 **OPCIÓN PRINCIPAL DE MAYOR CERTEZA:**\n"
            f"👉 **`{st['top_pick']}`** — Probabilidad: **`{st['top_prob']}%`**\n\n"
            f"📊 **Top 3 Opciones Múltiples (10,000 Simulaciones):**\n"
            f"{destacadas}"
        )
        enviar_mensaje_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)
        time.sleep(2)

# ---------------------------------------------------------
# EJECUCIÓN PRINCIPAL
# ---------------------------------------------------------
if __name__ == "__main__":
    partidos = obtener_jornada_completa()
    enviar_reporte_telegram(partidos)
