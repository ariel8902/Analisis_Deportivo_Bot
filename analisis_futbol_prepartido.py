import os
import requests
from scipy.stats import poisson
import google.generativeai as genai

# ---------------------------------------------------------
# 1. CONFIGURACIÓN DE APIS Y CREDENCIALES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Inicializar Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Ligas monitorizadas en Football API 7 (RapidAPI)
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
def calcular_probabilidades_poisson(lambda_local, lambda_visitante, max_goles=6):
    p_local_mas15, p_visitante_mas15 = 0, 0
    p_over15, p_over25, p_btts = 0, 0, 0

    for i in range(max_goles + 1):
        p_i = poisson.pmf(i, lambda_local)
        for j in range(max_goles + 1):
            p_j = poisson.pmf(j, lambda_visitante)
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
# 3. FILTRO CONTEXTUAL DE IA (GEMINI API)
# ---------------------------------------------------------
def evaluar_con_gemini(equipo_local, equipo_visitante, datos_poisson):
    if not GEMINI_API_KEY:
        return "Análisis de IA no disponible (Falta GEMINI_API_KEY)."

    prompt = f"""
    Actúa como un analista deportivo cuantitativo profesional.
    Evalúa el siguiente partido usando las probabilidades del modelo de Poisson calculadas:
    - Partido: {equipo_local} vs {equipo_visitante}
    - Probabilidad Over 1.5 Goles: {datos_poisson['over_1_5']}%
    - Probabilidad Over 2.5 Goles: {datos_poisson['over_2_5']}%
    - Probabilidad Ambos Anotan (BTTS): {datos_poisson['btts']}%

    Proporciona un veredicto sintético de 3 a 4 líneas considerando noticias recientes, bajas o contexto competitivo.
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Error al consultar Gemini API: {str(e)}"

# ---------------------------------------------------------
# 4. INGESTIÓN DE DATOS (RAPIDAPI - FOOTBALL API 7)
# ---------------------------------------------------------
def obtener_partidos_hoy():
    if not RAPIDAPI_KEY:
        print("Error: No se encontró la variable RAPIDAPI_KEY en los Secrets.")
        return []

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "football-api-7.p.rapidapi.com"
    }

    partidos_analizados = []

    for nombre_liga, league_id in LIGAS.items():
        url = f"https://football-api-7.p.rapidapi.com/api/v3/matches/live?league_id={league_id}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                datos = res.json()
                # Extraer partidos del payload devuelto
                matches = datos.get("events", []) or datos.get("matches", [])
                for match in matches:
                    eq_local = match.get("homeTeam", {}).get("name", "Local")
                    eq_vis = match.get("awayTeam", {}).get("name", "Visitante")
                    
                    # Promedios de gol estimados / dinámicos
                    exp_goles_local = 1.45
                    exp_goles_vis = 1.15
                    
                    poisson_stats = calcular_probabilidades_poisson(exp_goles_local, exp_goles_vis)
                    analisis_ia = evaluar_con_gemini(eq_local, eq_vis, poisson_stats)

                    partidos_analizados.append({
                        "liga": nombre_liga,
                        "local": eq_local,
                        "visitante": eq_vis,
                        "poisson": poisson_stats,
                        "gemini": analisis_ia
                    })
        except Exception as e:
            print(f"Error consultando liga {nombre_liga}: {e}")

    return partidos_analizados

# ---------------------------------------------------------
# 5. ENVÍO DE REPORTES A TELEGRAM
# ---------------------------------------------------------
def enviar_reporte_telegram(partidos):
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN no configurado.")
        return

    url_telegram = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Obtener ID del chat asignado
    url_updates = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url_updates).json()
        chat_id = res['result'][-1]['message']['chat']['id']
    except Exception:
        print("Error al obtener chat_id de Telegram. Asegúrate de haber enviado un mensaje previo a tu Bot.")
        return

    if not partidos:
        mensaje = "⚽ **SISTEMA CUANTITATIVO + GEMINI IA REAL**\n\n⚠️ *No hay partidos en vivo o agendados para hoy en las ligas monitorizadas.*"
        requests.post(url_telegram, data={"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"})
        return

    for p in partidos:
        mensaje = (
            f"⚽ **ANALISIS PREPARTIDO MULTI-MERCADO**\n"
            f"🏆 **{p['liga']}**\n"
            f"⚔️ **{p['local']} vs {p['visitante']}**\n\n"
            f"📊 **Matriz Cuantitativa (Poisson):**\n"
            f"• Over 1.5 Goles: `{p['poisson']['over_1_5']}%`\n"
            f"• Over 2.5 Goles: `{p['poisson']['over_2_5']}%`\n"
            f"• Ambos Anotan (BTTS): `{p['poisson']['btts']}%`\n\n"
            f"🤖 **Filtro Contextual Gemini IA:**\n"
            f"{p['gemini']}"
        )
        requests.post(url_telegram, data={"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"})

# ---------------------------------------------------------
# EJECUCIÓN PRINCIPAL
# ---------------------------------------------------------
if __name__ == "__main__":
    partidos = obtener_partidos_hoy()
    enviar_reporte_telegram(partidos)
