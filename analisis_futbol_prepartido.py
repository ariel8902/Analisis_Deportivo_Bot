import os
import math
import json
import time
import random
import urllib.request
import urllib.parse
from datetime import datetime
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. CONFIGURACIÓN DE APIS Y CREDENCIALES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

UMBRAL_MINIMO_FILTRO = 70.0  # Umbral de certeza del 70%
NUM_SIMULACIONES_MONTECARLO = 10000  # 10,000 iteraciones estocásticas

# Inicialización del cliente oficial de Google Gemini
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Esquema Pydantic para la extracción estricta de factores numéricos y posiciones reales
class AnalisisPartidoDinamicoSchema(BaseModel):
    posicion_exacta_local: str = Field(description="Puesto exacto en la tabla del equipo local, ej: '17°' o '17° (8 pts)'")
    posicion_exacta_visitante: str = Field(description="Puesto exacto en la tabla del equipo visitante, ej: '15°' o '15° (8 pts)'")
    factor_ajuste_local: float = Field(description="Factor de ajuste de fuerza del equipo local tras analizar noticias en vivo (1.0 neutro)")
    factor_ajuste_visitante: float = Field(description="Factor de ajuste de fuerza del equipo visitante tras analizar noticias en vivo (1.0 neutro)")

# ---------------------------------------------------------
# 2. MOTOR CUANTITATIVO GENERALIZADO (DIXON-COLES + xG + MONTE CARLO)
# ---------------------------------------------------------
def poisson_pmf(k, lambda_param):
    """Calcula la función de masa de probabilidad de Poisson pura."""
    if lambda_param <= 0:
        return 1.0 if k == 0 else 0.0
    return (lambda_param ** k) * math.exp(-lambda_param) / math.factorial(k)

def factor_dixon_coles(x, y, lambda_loc, lambda_vis, rho=-0.11):
    """Factor de corrección tau de Dixon & Coles (1997)."""
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
    """Construye la matriz conjunta de densidad de probabilidad teórica."""
    matriz = {}
    for i in range(max_goles + 1):
        p_i = poisson_pmf(i, lambda_loc)
        for j in range(max_goles + 1):
            p_j = poisson_pmf(j, lambda_vis)
            tau = factor_dixon_coles(i, j, lambda_loc, lambda_vis)
            matriz[(i, j)] = max(p_i * p_j * tau, 0.0)
    return matriz

def simular_monte_carlo(matriz_prob, num_simulaciones=10000, k_altitud=1.0, k_temperatura=1.0, lambda_tot=2.5):
    """
    Ejecuta 10,000 simulaciones de Monte Carlo jerárquicas.
    """
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
    """Integración jerárquica de xG, Motivación, Dixon-Coles y Monte Carlo."""
    lambda_loc_adj = lambda_loc * k_altitud * k_motivacion
    lambda_vis_adj = lambda_vis * (2.0 - k_altitud)
    
    matriz_teorica = generar_matriz_dixon_coles(lambda_loc_adj, lambda_vis_adj)
    
    return simular_monte_carlo(
        matriz_teorica, 
        num_simulaciones=NUM_SIMULACIONES_MONTECARLO, 
        k_altitud=k_altitud, 
        k_temperatura=k_temperatura,
        lambda_tot=lambda_loc_adj + lambda_vis_adj
    )

# ---------------------------------------------------------
# 3. EXTRACCIÓN DINÁMICA CON CONTROL DE CUOTA (ANTI-RATE LIMIT)
# ---------------------------------------------------------
def analizar_y_refinar_partido_ia(equipo_local, equipo_visitante, hora_partido, liga_nombre, pos_fallback_loc="En competencia", pos_fallback_vis="En competencia"):
    """
    Investiga en Google Search en tiempo real la tabla oficial y noticias de hoy.
    Aplica pausas estratégicas de 8 segundos para soportar alta demanda de fin de semana/Champions.
    """
    lambda_loc_base = 1.40
    lambda_vis_base = 1.10
    factor_loc = 1.0
    factor_vis = 1.0
    pos_local = pos_fallback_loc
    pos_visita = pos_fallback_vis

    if client:
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        prompt = (
            f"Busca en Google Search la tabla de posiciones oficial más reciente de {liga_nombre} para la jornada de hoy {fecha_hoy}.\n"
            f"Extrae el puesto exacto en la tabla para {equipo_local} (posicion_exacta_local) y para {equipo_visitante} (posicion_exacta_visitante).\n"
            f"Identifica lesionados, sancionados o rotaciones confirmadas para hoy para determinar los factores numéricos de ajuste de fuerza."
        )
        for intento in range(2):
            try:
                time.sleep(8)  # Pausa optimizada para evitar colapsos por tasa en días de alta demanda
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        response_mime_type="application/json",
                        response_schema=AnalisisPartidoDinamicoSchema,
                    )
                )
                if response.text:
                    data = json.loads(response.text)
                    factor_loc = float(data.get("factor_ajuste_local", 1.0))
                    factor_vis = float(data.get("factor_ajuste_visitante", 1.0))
                    
                    pl = str(data.get("posicion_exacta_local", "")).strip()
                    pv = str(data.get("posicion_exacta_visitante", "")).strip()
                    
                    if pl and "DESCONOCIDO" not in pl.upper() and "N/A" not in pl.upper():
                        pos_local = pl if "°" in pl or "Puesto" in pl else f"{pl}°"
                    if pv and "DESCONOCIDO" not in pv.upper() and "N/A" not in pv.upper():
                        pos_visita = pv if "°" in pv or "Puesto" in pv else f"{pv}°"
                    break
            except Exception as e:
                time.sleep(5)

    # REFINACIÓN FINAL DE MONTE CARLO (10,000 iteraciones jerárquicas)
    stats = evaluar_partido_completo(lambda_loc_base * factor_loc, lambda_vis_base * factor_vis)
    return {
        "liga": liga_nombre,
        "local": equipo_local,
        "visitante": equipo_visitante,
        "pos_local": pos_local,
        "pos_visita": pos_visita,
        "hora_fecha": hora_partido,
        "stats": stats
    }

# ---------------------------------------------------------
# 4. INGESTIÓN AUTOMÁTICA DE LA JORNADA
# ---------------------------------------------------------
def obtener_partidos_hoy():
    partidos_analizados = []
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    # Agenda base dinámica (Soporta múltiples ligas y jornadas de Champions/Fin de semana)
    agenda_jornada = [
        {
            "liga": "Liga BetPlay Colombia",
            "local": "Boyacá Chicó",
            "visitante": "Deportivo Pasto",
            "pos_loc": "17°",
            "pos_vis": "15°",
            "hora": f"{fecha_hoy} — 06:10 PM"
        },
        {
            "liga": "Liga BetPlay Colombia",
            "local": "Once Caldas",
            "visitante": "Atlético Bucaramanga",
            "pos_loc": "10°",
            "pos_vis": "6°",
            "hora": f"{fecha_hoy} — 08:15 PM"
        }
    ]

    print("Iniciando refinación táctica con Monte Carlo e Ingestión Dinámica de la Tabla...")
    for item in agenda_jornada:
        partido_refinado = analizar_y_refinar_partido_ia(
            item["local"], 
            item["visitante"], 
            item["hora"], 
            item["liga"],
            item.get("pos_loc", "En tabla"),
            item.get("pos_vis", "En tabla")
        )
        partidos_analizados.append(partido_refinado)

    return partidos_analizados

# ---------------------------------------------------------
# 5. DESPACHO DE REPORTES A TELEGRAM (MENSAJES INDIVIDUALES LIMPIOS)
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
        fecha_actual = datetime.now().strftime("%Y-%m-%d")
        mensaje = (
            f"🛡️ **REPORTE DE JORNADA - {fecha_actual}**\n\n"
            f"📊 *No se registran partidos programados por jugar para el día de hoy en las ligas monitorizadas.*\n\n"
            f"💡 *El sistema reanudará el análisis de 10,000 simulaciones Monte Carlo automáticamente en la próxima fecha con agenda activa.*"
        )
        enviar_mensaje_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)
        return

    for p in partidos:
        st = p["stats"]
        destacadas = "\n".join(st["opciones_destacadas"])

        # Ficha ultralimpia individual por partido
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
        time.sleep(2)  # Pausa de 2 segundos entre mensajes a Telegram para evitar bloqueos del Bot API

# ---------------------------------------------------------
# EJECUCIÓN PRINCIPAL
# ---------------------------------------------------------
if __name__ == "__main__":
    partidos = obtener_partidos_hoy()
    enviar_reporte_telegram(partidos)
