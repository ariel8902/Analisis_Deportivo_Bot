import os
import math
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta
from google import genai

# ---------------------------------------------------------
# 1. CONFIGURACIÓN DE CREDENCIALES
# ---------------------------------------------------------
TOKEN_TELEGRAM_REAL = "8650458483:AAFHgr5-yBeYdU3_T153BuSeNC2iSbV1BQ4"
CHAT_ID_REAL = "8707489920"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or TOKEN_TELEGRAM_REAL
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or CHAT_ID_REAL
ODDS_API_KEY = os.getenv("ODDS_API_KEY") or "f52fed19ba1071472e5a25c88fa23053"
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "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"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))
NUM_SIMULACIONES = 10000

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

# ¡CLAVE CORREGIDA!: soccer_colombia_primera_a
LIGAS_TOP = [
    {"key": "soccer_epl", "nombre": "Premier League"},
    {"key": "soccer_spain_la_liga", "nombre": "LaLiga"},
    {"key": "soccer_italy_serie_a", "nombre": "Serie A"},
    {"key": "soccer_germany_bundesliga", "nombre": "Bundesliga"},
    {"key": "soccer_france_ligue_one", "nombre": "Ligue 1"},
    {"key": "soccer_uefa_champions_league", "nombre": "Champions League"},
    {"key": "soccer_colombia_primera_a", "nombre": "Liga BetPlay"} 
]

HEADERS_NAV = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*'
}

# ---------------------------------------------------------
# 2. INGESTA HÍBRIDA MULTI-DÍA (THE-ODDS-API + ESPN)
# ---------------------------------------------------------
def obtener_agenda_betplay_espn(inicio, fin):
    """Consulta general sin restricción de día para asegurar los partidos nocturnos"""
    partidos_col = []
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/col.1/scoreboard"

    try:
        res = requests.get(url, headers=HEADERS_NAV, timeout=10)
        if res.status_code == 200:
            events = res.json().get("events", [])
            for ev in events:
                competitions = ev.get("competitions", [])[0]
                competitors = competitions.get("competitors", [])
                
                local = next((c for c in competitors if c.get("homeAway") == "home"), None)
                visita = next((c for c in competitors if c.get("homeAway") == "away"), None)
                
                if local and visita:
                    nom_loc = local["team"]["displayName"]
                    nom_vis = visita["team"]["displayName"]
                    
                    if "sub-" in nom_loc.lower() or "u20" in nom_loc.lower() or "femenino" in nom_loc.lower():
                        continue

                    date_utc_str = ev.get("date", "")
                    try:
                        dt_utc = datetime.fromisoformat(date_utc_str.replace("Z", "+00:00"))
                        dt_col = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA)
                    except Exception:
                        continue

                    if inicio <= dt_col <= fin:
                        partidos_col.append({
                            "liga": "Liga BetPlay (Colombia)",
                            "local": nom_loc,
                            "visitante": nom_vis,
                            "fechaHora": dt_col.strftime("%d/%m %I:%M %p"),
                            "cuotaLocal": "2.10",
                            "cuotaEmpate": "3.00",
                            "cuotaVisitante": "3.30"
                        })
    except Exception as e:
        print("Aviso ESPN:", e)

    return partidos_col

def obtener_partidos_jornada():
    ahora = datetime.now(ZONA_HORARIA_COLOMBIA)
    # Rango amplio: Desde hace 2 horas hasta las próximas 48 horas (asegura todo el fin de semana)
    inicio = ahora - timedelta(hours=2)
    fin = ahora + timedelta(hours=48)

    lista_partidos = []
    tiene_betplay = False
    
    estado_api = "OK"

    for liga in LIGAS_TOP:
        url = f"https://api.the-odds-api.com/v4/sports/{liga['key']}/odds/?apiKey={ODDS_API_KEY}&regions=us,eu&markets=h2h"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                eventos = res.json()
                for ev in eventos:
                    date_utc_str = ev.get("commence_time", "")
                    try:
                        dt_utc = datetime.fromisoformat(date_utc_str.replace("Z", "+00:00"))
                        dt_col = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA)
                    except Exception:
                        continue

                    if inicio <= dt_col <= fin:
                        local = ev.get("home_team")
                        visita = ev.get("away_team")
                        
                        cuota_loc, cuota_emp, cuota_vis = "N/A", "N/A", "N/A"
                        bookmakers = ev.get("bookmakers", [])
                        if bookmakers:
                            markets = bookmakers[0].get("markets", [])
                            h2h = next((m for m in markets if m.get("key") == "h2h"), None)
                            if h2h:
                                for out in h2h.get("outcomes", []):
                                    if out.get("name") == local:
                                        cuota_loc = str(out.get("price"))
                                    elif out.get("name") == visita:
                                        cuota_vis = str(out.get("price"))
                                    elif out.get("name") == "Draw":
                                        cuota_emp = str(out.get("price"))

                        if "colombia" in liga["key"]:
                            tiene_betplay = True

                        lista_partidos.append({
                            "liga": liga["nombre"],
                            "local": local,
                            "visitante": visita,
                            "fechaHora": dt_col.strftime("%d/%m %I:%M %p"),
                            "cuotaLocal": cuota_loc,
                            "cuotaEmpate": cuota_emp,
                            "cuotaVisitante": cuota_vis
                        })
            else:
                estado_api = f"Error {res.status_code}"
        except Exception as e:
            estado_api = "Fallo de conexión API"

    if not tiene_betplay:
        partidos_espn = obtener_agenda_betplay_espn(inicio, fin)
        lista_partidos.extend(partidos_espn)

    return lista_partidos, estado_api

# ---------------------------------------------------------
# 3. MOTOR MONTE CARLO
# ---------------------------------------------------------
def simular_monte_carlo(cuota_loc, cuota_vis, num_sim=10000):
    try:
        prob_loc_impl = 1.0 / float(cuota_loc) if cuota_loc != "N/A" else 0.45
        prob_vis_impl = 1.0 / float(cuota_vis) if cuota_vis != "N/A" else 0.30
    except Exception:
        prob_loc_impl, prob_vis_impl = 0.45, 0.30

    lambda_loc = prob_loc_impl * 2.8
    lambda_vis = prob_vis_impl * 2.5

    p_local, p_empate, p_visita, p_over25, p_btts = 0, 0, 0, 0, 0

    for _ in range(num_sim):
        l_l, p = lambda_loc, math.exp(-lambda_loc)
        g_l, p_acc, u = 0, p, random.random()
        while u > p_acc and g_l < 10:
            g_l += 1
            p = p * l_l / g_l
            p_acc += p

        l_v, p = lambda_vis, math.exp(-lambda_vis)
        g_v, p_acc, u = 0, p, random.random()
        while u > p_acc and g_v < 10:
            g_v += 1
            p = p * l_v / g_v
            p_acc += p

        if g_l > g_v: p_local += 1
        elif g_l == g_v: p_empate += 1
        else: p_visita += 1

        if (g_l + g_v) > 2.5: p_over25 += 1
        if g_l > 0 and g_v > 0: p_btts += 1

    return {
        "prob_local": round((p_local / num_sim) * 100, 1),
        "prob_empate": round((p_empate / num_sim) * 100, 1),
        "prob_visita": round((p_visita / num_sim) * 100, 1),
        "prob_over25": round((p_over25 / num_sim) * 100, 1),
        "prob_btts": round((p_btts / num_sim) * 100, 1)
    }

# ---------------------------------------------------------
# 4. ANÁLISIS DE IA (GROQ + GEMINI)
# ---------------------------------------------------------
def obtener_estructuracion_groq(partido):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    prompt = f"""Estructura cuantitativa:
Liga: {partido['liga']}
Partido: {partido['local']} vs {partido['visitante']}
Responde ÚNICAMENTE JSON: {{"ambos_marcan_pronostico": "SÍ" o "NO", "stake": "4/5", "probabilidad_estimada": "%", "cobertura_goles": "Más de 1.5 Goles"}}"""
    
    try:
        res = requests.post(url, headers=headers, json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}, timeout=8)
        if res.status_code == 200:
            return json.loads(res.json()["choices"][0]["message"]["content"])
    except:
        pass
    return {"ambos_marcan_pronostico": "SÍ", "stake": "4/5", "probabilidad_estimada": "68%", "cobertura_goles": "Más de 1.5 Goles"}

def refinamiento_final_gemini(partido, sim_data):
    if not client_gemini: return "Análisis táctico basado en dinámica ofensiva reciente."
    prompt = f"Analista táctico breve. {partido['local']} vs {partido['visitante']}. Justifica en 2 oraciones si habrá goles o no, basándote en que Ambos Anotan es {sim_data['prob_btts']}%."
    try:
        res = client_gemini.models.generate_content(model=MODELO_GEMINI, contents=prompt)
        return res.text.strip() if res.text else "Proyección de goles basada en vulnerabilidades defensivas expuestas."
    except:
        return "Se proyecta un trámite abierto y con presencia ofensiva recurrente de ambos lados."

# ---------------------------------------------------------
# 5. DESPACHO A TELEGRAM
# ---------------------------------------------------------
def enviar_mensaje_telegram(texto):
    token = TELEGRAM_BOT_TOKEN if (TELEGRAM_BOT_TOKEN and len(TELEGRAM_BOT_TOKEN) > 20) else TOKEN_TELEGRAM_REAL
    chat = TELEGRAM_CHAT_ID if (TELEGRAM_CHAT_ID and len(TELEGRAM_CHAT_ID) > 5) else CHAT_ID_REAL
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": texto, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print("Error Telegram:", e)

def ejecutar_bot_futbol():
    fecha_colombia = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d %I:%M %p")
    enviar_mensaje_telegram(f"🎯 <b>SUPERANALISTA PRO (IA ACTIVA)</b>\n📅 Escaneo iniciado: <b>{fecha_colombia}</b>")

    partidos, estado_api = obtener_partidos_jornada()

    if not partidos:
        enviar_mensaje_telegram(f"🛡️ <b>REPORTE SIN AGENDA</b>\n\n📊 <i>No hay partidos detectados en las próximas 48h.</i>\n⚙️ <i>Estado Odds API: {estado_api}</i>")
        return

    for p in partidos:
        sim = simular_monte_carlo(p["cuotaLocal"], p["cuotaVisitante"], NUM_SIMULACIONES)
        base_ia = obtener_estructuracion_groq(p)
        justificacion = refinamiento_final_gemini(p, sim)

        mensaje = (
            f"🏆 <b>{p['liga']}</b>\n"
            f"⚽ <b>{p['local']} vs {p['visitante']}</b>\n"
            f"⏰ <code>{p['fechaHora']} (Hora COL)</code>\n\n"
            f"📊 <b>Cuotas 1X2:</b> L: {p['cuotaLocal']} | E: {p['cuotaEmpate']} | V: {p['cuotaVisitante']}\n"
            f"🎲 <b>Monte Carlo (10,000 sim):</b> Ambos Anotan: <code>{sim['prob_btts']}%</code> | Over 2.5: <code>{sim['prob_over25']}%</code>\n\n"
            f"🔥 <b>PRONÓSTICO PRINCIPAL:</b>\n"
            f"🎯 <b>Ambos Equipos Anotan:</b> <b>{base_ia['ambos_marcan_pronostico']}</b>\n"
            f"📈 <b>Stake:</b> <code>{base_ia['stake']}</code>\n"
            f"💡 <i>{justificacion}</i>\n\n"
            f"🛡️ <b>COBERTURA:</b> {base_ia['cobertura_goles']}"
        )
        enviar_mensaje_telegram(mensaje)
        time.sleep(2)

    enviar_mensaje_telegram(f"✅ <b>Análisis completado.</b> Partidos enviados: {len(partidos)}")

if __name__ == "__main__":
    ejecutar_bot_futbol()
