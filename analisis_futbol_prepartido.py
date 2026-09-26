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
# 1. CONFIGURACIÓN DE APIS Y CREDENCIALES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

UMBRAL_MINIMO_FILTRO = 70.0
NUM_SIMULACIONES_MONTECARLO = 10000
ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# SECUENCIA RIGUROSA DE RESPALDO DE MODELOS (EVITA ERRORES 404 DE ENPOINT)
MODELOS_CANDIDATOS = ['gemini-3.8-flash', 'gemini-2.5-flash', 'gemini-1.5-flash']

# Esquemas Pydantic estructurados
class PartidoDetalleSchema(BaseModel):
    liga: str = Field(description="Nombre de la liga o torneo")
    local: str = Field(description="Equipo local")
    visitante: str = Field(description="Equipo visitante")
    hora: str = Field(description="Hora programada de hoy")
    pos_local: str = Field(description="Puesto en la tabla del local, ej: '3°'")
    pos_visita: str = Field(description="Puesto en la tabla del visitante, ej: '5°'")
    factor_ajuste_local: float = Field(description="Factor de fuerza local (1.0 neutro)")
    factor_ajuste_visitante: float = Field(description="Factor de fuerza visitante (1.0 neutro)")

class JornadaConsolidadaSchema(BaseModel):
    partidos: list[PartidoDetalleSchema] = Field(description="Lista de partidos oficiales programados para jugar HOY")

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
# 3. EXTRACCIÓN CON RECORRIDO DE MODELOS CANDIDATOS
# ---------------------------------------------------------
def obtener_jornada_completa():
    if not client:
        return []

    fecha_hoy = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
    print(f"Iniciando consulta de agenda web para la fecha {fecha_hoy}...")

    prompt = (
        f"Investiga en Google Search los partidos de fútbol profesionales que se juegan HOY {fecha_hoy}.\n"
        f"Incluye la Liga BetPlay Colombia y ligas europeas (Premier League, LaLiga, Serie A, Bundesliga, Ligue 1).\n"
        f"Para cada partido, extrae las posiciones en la tabla de ambos equipos y evalúa factores de ajuste de fuerza (1.0 neutro).\n"
        f"Devuelve la agenda completa en formato JSON exacto."
    )

    for modelo in MODELOS_CANDIDATOS:
        try:
            print(f"Probando conexión con modelo: {modelo}...")
            response = client.models.generate_content(
                model=modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    response_mime_type="application/json",
                    response_schema=JornadaConsolidadaSchema,
                )
            )
            if response.text:
                data = json.loads(response.text)
                partidos_raw = data.get("partidos", [])
                if partidos_raw:
                    print(f"¡Éxito! Agenda cargada desde {modelo}. Partidos encontrados: {len(partidos_raw)}")
                    
                    partidos_analizados = []
                    for item in partidos_raw:
                        lambda_loc_base = 1.40 * float(item.get("factor_ajuste_local", 1.0))
                        lambda_vis_base = 1.10 * float(item.get("factor_ajuste_visitante", 1.0))
                        
                        stats = evaluar_partido_completo(lambda_loc_base, lambda_vis_base)
                        
                        hora_fmt = f"{fecha_hoy} — {item.get('hora', 'Hoy')}"
                        partidos_analizados.append({
                            "liga": item.get("liga", "Fútbol Profesional"),
                            "local": item.get("local", "Local"),
                            "visitante": item.get("visitante", "Visitante"),
                            "pos_local": item.get("pos_local", "En tabla"),
                            "pos_visita": item.get("pos_visita", "En tabla"),
                            "hora_fecha": hora_fmt,
                            "stats": stats
                        })
                    return partidos_analizados
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                print(f"Aviso en {modelo}: Límite de frecuencia (429). Pausando 8 segundos para reintentar...")
                time.sleep(8)
            else:
                print(f"Aviso en {modelo}: {e}. Evaluando siguiente candidato...")
            continue

    return []

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
            f"📊 *No se registran partidos programados en la agenda pública de hoy.*\n\n"
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
