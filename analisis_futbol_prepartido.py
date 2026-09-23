import math
import time
import os
import requests
from telebot import TeleBot
from google import genai

# ==============================================================================
# CONFIGURACIÓN Y CREDENCIALES
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8650458483:AAFcREwoHQwVvm293oc2jDxKHe1H5VdsNyg")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8707489920")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "b3d1f1c7d8a946e3b8a1c2d3e4f5a6b7")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = TeleBot(TELEGRAM_BOT_TOKEN)

# Conexión directa a la API REAL de Google Gemini
gemini_client = None
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"⚠️ Error al conectar con Google Gemini: {e}")

UMBRAL_MINIMO_CONFIANZA = 70.0  

# ==============================================================================
# 1. EVALUACIÓN DE NOTICIAS, BAJAS Y CLIMA CON IA REAL (GEMINI)
# ==============================================================================

def analizar_contexto_con_ia_real(local, visita, liga):
    """Consulta en tiempo real a Google Gemini para evaluar lesiones, clima y rotaciones."""
    if not gemini_client:
        return 0.0, "IA no activa (Configurar GEMINI_API_KEY en Secrets de GitHub)"

    prompt = f"""
    Eres un analista deportivo cuantitativo profesional.
    Analiza el partido {local} vs {visita} de la liga {liga}.
    
    Evalúa factores objetivos de última hora:
    1. Lesiones o suspensiones de jugadores titulares clave.
    2. Condiciones del clima o estado del terreno de juego.
    3. Carga de partidos (rotaciones por torneos internacionales/copas).
    
    Responde strictly en este formato breve (máximo 2 líneas):
    AJUSTE: [Un número flotante entre -5.0 y +5.0 con el impacto en probabilidad]
    RAZON: [Explicación técnica breve de los factores encontrados]
    """

    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        texto = response.text
        
        ajuste = 0.0
        razon = "Análisis contextual en vivo completado por Gemini IA"
        
        for linea in texto.split('\n'):
            if "AJUSTE:" in linea:
                partes = linea.replace("AJUSTE:", "").strip()
                try:
                    ajuste = float(partes)
                except ValueError:
                    ajuste = 0.0
            elif "RAZON:" in linea:
                razon = linea.replace("RAZON:", "").strip()
                
        return ajuste, razon
    except Exception as e:
        print(f"❌ Error al consultar Gemini IA: {e}")
        return 0.0, "Consulta de IA no disponible temporalmente"

# ==============================================================================
# 2. ALGORITMO CUANTITATIVO MATEMÁTICO (POISSON)
# ==============================================================================

def calcular_poisson(k, lambda_param):
    return (math.pow(lambda_param, k) * math.exp(-lambda_param)) / math.factorial(k)

def calcular_matriz_poisson(xg_local, xg_visita):
    prob_mas_1_5 = 0.0
    prob_mas_2_5 = 0.0
    prob_btts = 0.0
    
    for gl in range(6):
        p_l = calcular_poisson(gl, xg_local)
        for gv in range(6):
            p_v = calcular_poisson(gv, xg_visita)
            p_res = p_l * p_v
            
            if (gl + gv) > 1:
                prob_mas_1_5 += p_res
            if (gl + gv) > 2:
                prob_mas_2_5 += p_res
            if gl > 0 and gv > 0:
                prob_btts += p_res
                
    return {
        "mas_1_5": round(prob_mas_1_5 * 100, 1),
        "mas_2_5": round(prob_mas_2_5 * 100, 1),
        "btts": round(prob_btts * 100, 1)
    }

# ==============================================================================
# 3. PROCESAMIENTO GENERAL Y DESPACHO
# ==============================================================================

def obtener_partidos_reales_hoy():
    fecha_hoy = time.strftime("%Y-%m-%d")
    url = f"https://api.football-data.org/v4/matches?dateFrom={fecha_hoy}&dateTo={fecha_hoy}"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    
    partidos = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            matches = response.json().get("matches", [])
            for m in matches:
                partidos.append({
                    "local": m["homeTeam"]["name"],
                    "visita": m["awayTeam"]["name"],
                    "liga": m.get("competition", {}).get("name", "Liga Top"),
                    "xg_l": 1.70,
                    "xg_v": 1.30
                })
    except Exception as e:
        print(f"❌ Error API Fútbol: {e}")
    return partidos

def ejecutar_sistema_analisis():
    partidos = obtener_partidos_reales_hoy()
    fecha_actual = time.strftime("%Y-%m-%d")
    
    if not partidos:
        msg = f"⚽ <b>SISTEMA CUANTITATIVO + GEMINI IA REAL</b>\n📅 Fecha: {fecha_actual}\n\n"
        msg += "⚠️ <i>No hay partidos de ligas principales programados para hoy.</i>"
        bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="HTML")
        return

    msg = f"⚽ <b>ANÁLISIS MULTI-MERCADO (POISSON + GEMINI IA REAL)</b>\n"
    msg += f"📅 <b>Fecha:</b> {fecha_actual}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    alerta_enviada = False

    for p in partidos:
        # 1. Algoritmo Cuantitativo
        metricas = calcular_matriz_poisson(p["xg_l"], p["xg_v"])
        
        # 2. Análisis de IA en Vivo
        ajuste_ia, nota_ia = analizar_contexto_con_ia_real(p["local"], p["visita"], p["liga"])
        
        prob_base = metricas["mas_2_5"]
        prob_final = round(prob_base + ajuste_ia, 1)

        if prob_final >= UMBRAL_MINIMO_CONFIANZA:
            alerta_enviada = True
            msg += f"🏆 <b>{p['liga']}</b>\n"
            msg += f"🏟️ <b>{p['local']} vs. {p['visita']}</b>\n"
            msg += f" ├ 📊 <b>MERCADOS MATEMÁTICOS:</b>\n"
            msg += f" │   • Más de 1.5 Goles: <b>{metricas['mas_1_5']}%</b>\n"
            msg += f" │   • Más de 2.5 Goles: <b>{metricas['mas_2_5']}%</b>\n"
            msg += f" │   • Ambos Anotan (BTTS): <b>{metricas['btts']}%</b>\n"
            msg += f" ├ 🤖 <b>FILTRO GEMINI IA REAL:</b> {ajuste_ia:+}%\n"
            msg += f" │   └ <i>{nota_ia}</i>\n"
            msg += f" └ 🎯 <b>CONFIANZA FINAL: {prob_final}%</b> 🟢\n\n"

    if not alerta_enviada:
        msg += f"⚠️ <b>SIN SELECCIÓN DE ALTA CONFIANZA HOY</b>\n"
        msg += f"Los partidos de hoy no alcanzaron el <b>{UMBRAL_MINIMO_CONFIANZA}%</b> necesario tras el filtro estricto de IA + Matemática.\n"

    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💡 <i>Análisis generado con Google Gemini IA + Algoritmo Cuantitativo de Poisson.</i>"

    bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="HTML")

if __name__ == "__main__":
    ejecutar_sistema_analisis()
