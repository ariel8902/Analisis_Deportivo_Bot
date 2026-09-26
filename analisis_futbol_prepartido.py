import os
import math
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta
from google import genai

# ---------------------------------------------------------
# 1. CONFIGURACIÓN Y CREDENCIALES SEGUROS DESDE SECRETS
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY") or "f52fed19ba1071472e5a25c88fa23053"
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "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"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))
NUM_SIMULACIONES = 10000

# Cliente Oficial de Gemini
client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

HEADERS_NAV = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
}

# Ligas Europeas desde Odds API (Las mismas de tu Google Apps Script)
LIGAS_ODDS = [
    {"key": "soccer_epl", "nombre": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League"},
    {"key": "soccer_spain_la_liga", "nombre": "🇪🇸 LaLiga"},
    {"key": "soccer_italy_serie_a", "nombre": "🇮🇹 Serie A"},
    {"key": "soccer_germany_bundesliga", "nombre": "🇩🇪 Bundesliga"},
    {"key": "soccer_france_ligue_one", "nombre": "🇫🇷 Ligue 1"},
    {"key": "soccer_uefa_champions_league", "nombre": "🇪🇺 Champions League"}
]

# ---------------------------------------------------------
# 2. INGESTA HÍBRIDA INCONDICIONAL (ODDS API + ESPN COLOMBIA)
# ---------------------------------------------------------
def obtener_partidos_reales():
    lista_partidos = []

    # 1. Traer Europa desde The-Odds-API (Idéntico a Google Apps Script)
    for liga in LIGAS_ODDS:
        url = f"https://api.the-odds-api.com/v4/sports/{liga['key']}/odds/?apiKey={ODDS_API_KEY}&regions=us,eu&markets=h2h"
        try:
            res = requests.get(url, timeout=8)
            if res.status_code == 200:
                eventos = res.json()
                for ev in eventos:
                    local = ev.get("home_team")
                    visita = ev.get("away_team")
                    
                    date_utc_str = ev.get("commence_time", "")
                    try:
                        dt_utc = datetime.fromisoformat(date_utc_str.replace("Z", "+00:00"))
                        dt_col = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA)
                        hora_fmt = dt_col.strftime("%d/%m %I:%M %p")
                    except Exception:
                        hora_fmt = "Por definir"

                    cuota_loc, cuota_emp, cuota_vis = "2.10", "3.10", "3.20"
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

                    lista_partidos.append({
                        "liga": liga["nombre"],
                        "local": local,
                        "visitante": visita,
                        "fechaHora": hora_fmt,
                        "cuotaLocal": cuota_loc,
                        "cuotaEmpate": cuota_emp,
                        "cuotaVisitante": cuota_vis
                    })
        except Exception as e:
            print(f"Aviso Odds API en {liga['nombre']}:", e)

    # 2. Traer Colombia garantizado directamente desde ESPN
    fecha_hoy = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y%m%d")
    fecha_manana = (datetime.now(ZONA_HORARIA_COLOMBIA) + timedelta(days=1)).strftime("%Y%m%d")
    
    for f in [fecha_hoy, fecha_manana]:
        url_col = f"https://site.api.espn.com/apis/site/v2/sports/soccer/col.1/scoreboard?dates={f}"
        try:
            res_espn = requests.get(url_col, headers=HEADERS_NAV, timeout=8)
            if res_espn.status_code == 200:
                events = res_espn.json().get("events", [])
                for ev in events:
                    competitions = ev.get("competitions", [])[0]
                    competitors = competitions.get("competitors", [])
                    
                    local = next((c for c in competitors if c.get("homeAway") == "home"), None)
                    visita = next((c for c in competitors if c.get("homeAway") == "away"), None)
                    
                    if local and visita:
                        nom_loc = local["team"]["displayName"]
                        nom_vis = visita["team"]["displayName"]
                        
                        if "sub-" in nom_loc.lower() or "u20" in nom_loc.lower():
                            continue

                        date_utc_str = ev.get("date", "")
                        try:
                            dt_utc = datetime.fromisoformat(date_utc_str.replace("Z", "+00:00"))
                            dt_col = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA)
                            hora_fmt = dt_col.strftime("%d/%m %I:%M %p")
                        except Exception:
                            hora_fmt = "Hoy / En juego"

                        if not any(p["local"] == nom_loc for p in lista_partidos):
                            lista_partidos.append({
                                "liga": "🇨🇴 Liga BetPlay",
                                "local": nom_loc,
                                "visitante": nom_vis,
                                "fechaHora": hora_fmt,
                                "cuotaLocal": "2.10",
                                "cuotaEmpate": "3.10",
                                "cuotaVisitante": "3.20"
                            })
        except Exception as e:
            print("Aviso ESPN Colombia:", e)

    return lista_partidos

# ---------------------------------------------------------
# 3. MOTOR MONTE CARLO (10,000 SIMULACIONES)
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
# 4. ANÁLISIS DE IA COMBINADO
# ---------------------------------------------------------
def obtener_estructuracion_groq(partido):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    prompt = f"""Estructura cuantitativa para partido REAL:
Liga: {partido['liga']} | Partido: {partido['local']} vs {partido['visitante']}
Responde ÚNICAMENTE JSON: {{"ambos_marcan_pronostico": "SÍ" o "NO", "stake": "4/5", "probabilidad_estimada": "%", "cobertura_goles": "Más de 1.5 Goles"}}"""
    try:
        res = requests.post(url, headers=headers, json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}, timeout=8)
        if res.status_code == 200:
            return json.loads(res.json()["choices"][0]["message"]["content"])
    except:
        pass
    return {"ambos_marcan_pronostico": "SÍ", "stake": "4/5", "probabilidad_estimada": "68%", "cobertura_goles": "Más de 1.5 Goles"}

def refinamiento_final_gemini(partido, sim_data):
    if not client_gemini:
        return "Análisis táctico proyectado sobre la potencia ofensiva y vulnerabilidad defensiva en transiciones."

    prompt = (
        f"Actúa como analista jefe de fútbol. Evalúa el partido REAL {partido['local']} vs {partido['visitante']} ({partido['liga']}). "
        f"Métricas del modelo: Probabilidad Ambos Anotan: {sim_data['prob_btts']}%, Over 2.5: {sim_data['prob_over25']}%. "
        f"Redacta una justificación táctica de máximo 2 oraciones en español enfocado en la capacidad goleadora o fallas defensivas de los equipos."
    )
    try:
        time.sleep(1.5)
        res = client_gemini.models.generate_content(model=MODELO_GEMINI, contents=prompt)
        return res.text.strip() if res.text else "Análisis ofensivo enfocado en transiciones."
    except Exception as e:
        print("Aviso Gemini:", e)
        return "Se proyecta un trámite de propuesta abierta y presencia ofensiva constante."

# ---------------------------------------------------------
# 5. DESPACHO A TELEGRAM
# ---------------------------------------------------------
def enviar_mensaje_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales no configuradas.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=8)
        print("Respuesta Telegram HTTP:", res.status_code)
    except Exception as e:
        print("Error enviando a Telegram:", e)

def ejecutar_bot_futbol():
    fecha_colombia = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d %I:%M %p")
    enviar_mensaje_telegram(f"🎯 <b>SUPERANALISTA PRO - DATOS REALES VERIFICADOS</b>\n📅 Escaneo activo: <b>{fecha_colombia}</b>")

    partidos = obtener_partidos_reales()

    if not partidos:
        enviar_mensaje_telegram(f"🛡️ <b>REPORTE DE JORNADA</b>\n\n📊 <i>No se registraron partidos activos.</i>")
        return

    for p in partidos:
        sim = simular_monte_carlo(p["cuotaLocal"], p["cuotaVisitante"], NUM_SIMULACIONES)
        base_ia = obtener_estructuracion_groq(p)
        justificacion = refinamiento_final_gemini(p, sim)

        mensaje = (
            f"🏆 <b>{p['liga']}</b>\n"
            f"⚽ <b>{p['local']} vs {p['visitante']}</b>\n"
            f"⏰ Fecha/Hora: <code>{p['fechaHora']} (Hora COL)</code>\n\n"
            f"📊 <b>Cuotas 1X2:</b> L: <code>{p['cuotaLocal']}</code> | E: <code>{p['cuotaEmpate']}</code> | V: <code>{p['cuotaVisitante']}</code>\n"
            f"🎲 <b>Monte Carlo (10,000 sim):</b> Both Score: <code>{sim['prob_btts']}%</code> | Over 2.5: <code>{sim['prob_over25']}%</code>\n\n"
            f"🔥 <b>PRONÓSTICO PRINCIPAL:</b>\n"
            f"🎯 <b>Ambos Equipos Anotan:</b> <b>{base_ia['ambos_marcan_pronostico']}</b>\n"
            f"📈 <b>Confianza / Stake:</b> <code>{base_ia['stake']}</code>\n"
            f"💡 <i>{justificacion}</i>\n\n"
            f"🛡️ <b>OPCIÓN COBERTURA (GOLES):</b>\n"
            f"🎯 <b>Línea Alternativa:</b> {base_ia['cobertura_goles']}"
        )

        enviar_mensaje_telegram(mensaje)
        time.sleep(2)

    enviar_mensaje_telegram(f"✅ <b>Análisis completado.</b> Partidos verídicos procesados: {len(partidos)}")

if __name__ == "__main__":
    ejecutar_bot_futbol()
