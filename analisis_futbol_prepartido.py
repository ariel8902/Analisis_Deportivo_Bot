import os
import math
import json
import urllib.request
import urllib.parse
from datetime import datetime

# ---------------------------------------------------------
# 1. CONFIGURACIÓN DE APIS Y CREDENCIALES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

UMBRAL_MINIMO_CONFIANZA = 70.0

LIGAS = {
    "Liga BetPlay Colombia": "239",
    "Premier League": "39",
    "La Liga España": "140",
    "Serie A Italia": "135",
    "UEFA Champions League": "2",
    "Copa Libertadores": "13"
}

# ---------------------------------------------------------
# 2. MOTOR CUANTITATIVO DE POISSON
# ---------------------------------------------------------
def poisson_pmf(k, lambda_param):
    return (lambda_param ** k) * math.exp(-lambda_param) / math.factorial(k)

def calcular_probabilidades_poisson(lambda_local, lambda_visitante, max_goles=6):
    p_over15, p_over25, p_btts = 0, 0, 0

    for i in range(max_goles + 1):
        p_i = poisson_pmf(i, lambda_local)
        for j in range(max_goles + 1):
            p_j = poisson_pmf(j, lambda_visitante)
            prob_matriz = p_i * p_j

            if i + j > 1.5:
                p_over15 += prob_matriz
            if i + j > 2.5:
                p_over25 += prob_matriz
            if i > 0 and j > 0:
                p_btts += prob_matriz

    return {
        "over_1_5": round(p_over15 * 100, 1),
        "over_2_5": round(p_over25 * 100, 1),
        "btts": round(p_btts * 100, 1)
    }

# ---------------------------------------------------------
# 3. FILTRO CONTEXTUAL DE IA (GEMINI API REST)
# ---------------------------------------------------------
def evaluar_con_gemini(equipo_local, equipo_visitante, datos_poisson):
    if not GEMINI_API_KEY:
        return "Análisis cualitativo no disponible.", 0.0

    prompt = (
        f"Actúa como un analista deportivo cuantitativo profesional. "
        f"Evalúa el siguiente partido usando las probabilidades del modelo de Poisson calculadas:\n"
        f"- Partido: {equipo_local} vs {equipo_visitante}\n"
        f"- Probabilidad Over 1.5 Goles: {datos_poisson['over_1_5']}%\n"
        f"- Probabilidad Over 2.5 Goles: {datos_poisson['over_2_5']}%\n"
        f"- Probabilidad Ambos Anotan (BTTS): {datos_poisson['btts']}%\n\n"
        f"Proporciona un veredicto sintético de 2 a 3 líneas considerando noticias recientes o contexto competitivo."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
    headers = {"Content-Type": "application/json"}

    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            texto_ia = res_data['candidates'][0]['content']['parts'][0]['text'].strip()
            return texto_ia, 0.0
    except Exception as e:
        return f"Nota contextual no disponible: {str(e)}", 0.0

# ---------------------------------------------------------
# 4. INGESTIÓN DE DATOS DE FÚTBOL
# ---------------------------------------------------------
def obtener_partidos_hoy():
    if not RAPIDAPI_KEY:
        print("Error: RAPIDAPI_KEY no configurada.")
        return []

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "football-api-7.p.rapidapi.com"
    }

    partidos_analizados = []
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    for nombre_liga, league_id in LIGAS.items():
        url = f"https://football-api-7.p.rapidapi.com/api/v1/custom/matches?league_id={league_id}&date={fecha_hoy}"
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    datos = json.loads(response.read().decode('utf-8'))
                    matches = datos.get("events", []) or datos.get("matches", []) or datos.get("data", [])
                    for match in matches:
                        eq_local = match.get("homeTeam", {}).get("name", "Local")
                        eq_vis = match.get("awayTeam", {}).get("name", "Visitante")
                        
                        poisson_stats = calcular_probabilidades_poisson(1.45, 1.15)
                        analisis_ia, ajuste = evaluar_con_gemini(eq_local, eq_vis, poisson_stats)
                        prob_combinada = round(poisson_stats["over_2_5"] + ajuste, 1)

                        partidos_analizados.append({
                            "liga": nombre_liga,
                            "local": eq_local,
                            "visitante": eq_vis,
                            "poisson": poisson_stats,
                            "gemini": analisis_ia,
                            "prob_final": prob_combinada
                        })
        except Exception as e:
            print(f"Información liga {nombre_liga}: {e}")

    return partidos_analizados

# ---------------------------------------------------------
# 5. ENVÍO DE REPORTES A TELEGRAM
# ---------------------------------------------------------
def enviar_mensaje_telegram(token, chat_id, texto):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            print("Mensaje despachado a Telegram. Código HTTP:", res.status)
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)

def enviar_reporte_telegram(partidos):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram faltantes.")
        return

    partidos_validos = [p for p in partidos if p["prob_final"] >= UMBRAL_MINIMO_CONFIANZA]

    if not partidos_validos:
        fecha_actual = datetime.now().strftime("%Y-%m-%d")
        mensaje = (
            f"🛡️ **REPORTE DE GESTIÓN DE RIESGO - {fecha_actual}**\n\n"
            f"📊 **Análisis de la jornada finalizado:**\n"
            f"Se evaluaron las ligas monitorizadas, pero **ningún partido superó el umbral mínimo del {UMBRAL_MINIMO_CONFIANZA}% de probabilidad combinada**.\n\n"
            f"💡 *Recomendación del Algoritmo: Abstenerse de operar en esta jornada para preservar la gestión de bankroll.*"
        )
        enviar_mensaje_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)
        return

    for p in partidos_validos:
        mensaje = (
            f"⚽ **ANÁLISIS PREPARTIDO MULTI-MERCADO**\n"
            f"🏆 **{p['liga']}**\n"
            f"⚔️ **{p['local']} vs {p['visitante']}**\n\n"
            f"📊 **Matriz Cuantitativa (Poisson):**\n"
            f"• Over 1.5 Goles: `{p['poisson']['over_1_5']}%`\n"
            f"• Over 2.5 Goles: `{p['poisson']['over_2_5']}%`\n"
            f"• Ambos Anotan (BTTS): `{p['poisson']['btts']}%`\n\n"
            f"🎯 **Puntuación Combinada:** `{p['prob_final']}%`\n\n"
            f"🤖 **Filtro Contextual Gemini IA:**\n"
            f"{p['gemini']}"
        )
        enviar_mensaje_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)

# ---------------------------------------------------------
# EJECUCIÓN PRINCIPAL
# ---------------------------------------------------------
if __name__ == "__main__":
    partidos = obtener_partidos_hoy()
    enviar_reporte_telegram(partidos)
