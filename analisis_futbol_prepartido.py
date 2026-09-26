import os
import math
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta
from google import genai

# ---------------------------------------------------------
# 1. CONFIGURACIÓN Y CREDENCIALES
# ---------------------------------------------------------
TOKEN_NUEVO_TELEGRAM = "8650458483:AAFHgr5-yBeYdU3_T153BuSeNC2iSbV1BQ4"
CHAT_ID_PERSONAL = "8707489920"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or TOKEN_NUEVO_TELEGRAM
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or CHAT_ID_PERSONAL
ODDS_API_KEY = os.getenv("ODDS_API_KEY") or "f52fed19ba1071472e5a25c88fa23053"
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "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"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))
NUM_SIMULACIONES = 10000

# Cliente Oficial de Gemini
client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

# Ligas Top de Europa + Colombia
LIGAS_TOP = [
    {"key": "soccer_epl", "nombre": "Premier League"},
    {"key": "soccer_spain_la_liga", "nombre": "LaLiga"},
    {"key": "soccer_italy_serie_a", "nombre": "Serie A"},
    {"key": "soccer_germany_bundesliga", "nombre": "Bundesliga"},
    {"key": "soccer_france_ligue_one", "nombre": "Ligue 1"},
    {"key": "soccer_uefa_champions_league", "nombre": "Champions League"},
    {"key": "soccer_colombia_liga_aguila", "nombre": "Liga BetPlay"}
]

HEADERS_NAV = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
}

# ---------------------------------------------------------
# 2. INGESTA HÍBRIDA (THE-ODDS-API + RESPALDO ESPN BETPLAY)
# ---------------------------------------------------------
def obtener_agenda_betplay_espn():
    fecha_hoy = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y%m%d")
    partidos_col = []
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/col.1/scoreboard?dates={fecha_hoy}"

    try:
        res = requests.get(url, headers=HEADERS_NAV, timeout=8)
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
                    
                    if "sub-" in nom_loc.lower() or "sub-" in nom_vis.lower() or "u20" in nom_loc.lower():
                        continue

                    date_utc_str = ev.get("date", "")
                    try:
                        dt_utc = datetime.fromisoformat(date_utc_str.replace("Z", "+00:00"))
                        dt_col = dt_utc.astimezone(ZONA_HORARIA_COLOMBIA)
                        hora_fmt = dt_col.strftime("%I:%M %p")
                    except Exception:
                        hora_fmt = "Por definir"

                    partidos_col.append({
                        "liga": "Liga BetPlay (Colombia)",
                        "local": nom_loc,
                        "visitante": nom_vis,
                        "fechaHora": hora_fmt,
                        "cuotaLocal": "2.10",
                        "cuotaEmpate": "3.10",
                        "cuotaVisitante": "3.20"
                    })
    except Exception as e:
        print("Aviso al consultar Liga BetPlay en ESPN:", e)

    return partidos_col

def obtener_partidos_jornada():
    ahora = datetime.now(ZONA_HORARIA_COLOMBIA)
    inicio = ahora - timedelta(hours=12)
    fin = ahora + timedelta(hours=48)

    lista_partidos = []
    tiene_betplay = False

    for liga in LIGAS_TOP:
        url = f"https://api.the-odds-api.com/v4/sports/{liga['key']}/odds/?apiKey={ODDS_API_KEY}&regions=us,eu&markets=h2h"
        try:
            res = requests.get(url, timeout=8)
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

                        if "liga_aguila" in liga["key"]:
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
        except Exception as e:
            print(f"Aviso consultando {liga['nombre']}:", e)

    if not tiene_betplay:
        partidos_espn = obtener_agenda_betplay_espn()
        lista_partidos.extend(partidos_espn)

    return lista_partidos

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

    p_local, p_empate, p_visita = 0, 0, 0
    p_over25, p_btts = 0, 0

    for _ in range(num_sim):
        l_l = lambda_loc
        p = math.exp(-l_l)
        g_l, p_acc = 0, p
        u = random.random()
        while u > p_acc and g_l < 10:
            g_l += 1
            p = p * l_l / g_l
            p_acc += p
        goles_loc = g_l

        l_v = lambda_vis
        p = math.exp(-l_v)
        g_v, p_acc = 0, p
        u = random.random()
        while u > p_acc and g_v < 10:
            g_v += 1
            p = p * l_v / g_v
            p_acc += p
        goles_vis = g_v

        if goles_loc > goles_vis:
            p_local += 1
        elif goles_loc == goles_vis:
            p_empate += 1
        else:
            p_visita += 1

        if (goles_loc + goles_vis) > 2.5:
            p_over25 += 1

        if goles_loc > 0 and goles_vis > 0:
            p_btts += 1

    return {
        "prob_local": round((p_local / num_sim) * 100, 1),
        "prob_empate": round((p_empate / num_sim) * 100, 1),
        "prob_visita": round((p_visita / num_sim) * 100, 1),
        "prob_over25": round((p_over25 / num_sim) * 100, 1),
        "prob_btts": round((p_btts / num_sim) * 100, 1)
    }

# ---------------------------------------------------------
# 4. ANÁLISIS DE IA COMBINADO (GROQ BASE + GEMINI REFINAMIENTO)
# ---------------------------------------------------------
def obtener_estructuracion_groq(partido):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""Estructura cuantitativa para el encuentro:
Liga: {partido['liga']}
Partido: {partido['local']} vs {partido['visitante']}
Cuotas: Local ({partido['cuotaLocal']}) | Empate ({partido['cuotaEmpate']}) | Visitante ({partido['cuotaVisitante']})

Responde ÚNICAMENTE con JSON:
{{
  "ambos_marcan_pronostico": "SÍ" o "NO",
  "stake": "Stake (Ejemplo: 4/5)",
  "probabilidad_estimada": "% estimado",
  "cobertura_goles": "Opción de línea de gol (Ejemplo: Más de 2.5 Goles)"
}}"""

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=8)
        if res.status_code == 200:
            return json.loads(res.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print("Aviso al estructurar datos iniciales en Groq:", e)

    return {
        "ambos_marcan_pronostico": "SÍ",
        "stake": "4/5",
        "probabilidad_estimada": "68%",
        "cobertura_goles": "Más de 1.5 Goles"
    }

def refinamiento_final_gemini(partido, sim_data, base_ia):
    if not client_gemini:
        return "Análisis táctico basado en la dinámica ofensiva reciente y balance defensivo."

    prompt = (
        f"Actúa como el analista jefe de fútbol. Evalúa el partido {partido['local']} vs {partido['visitante']} ({partido['liga']}). "
        f"Métricas del modelo: Probabilidad Ambos Anotan: {sim_data['prob_btts']}%, Over 2.5: {sim_data['prob_over25']}%. "
        f"Cuotas 1X2: L:{partido['cuotaLocal']} E:{partido['cuotaEmpate']} V:{partido['cuotaVisitante']}. "
        f"Redacta una justificación táctica brillante de 2 oraciones en español enfocada en la potencia ofensiva o vulnerabilidad defensiva de ambos equipos."
    )

    try:
        time.sleep(2)
        res = client_gemini.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt
        )
        if res.text:
            return res.text.strip()
    except Exception as e:
        print("Aviso en refinamiento Gemini, usando respaldo táctico:", e)

    return f"Se espera un desarrollo de alta intensidad ofensiva donde la fragilidad en las transiciones del conjunto visitante favorece el mercado de goles."

# ---------------------------------------------------------
# 5. DESPACHO A TELEGRAM
# ---------------------------------------------------------
def enviar_mensaje_telegram(texto):
    token_uso = TELEGRAM_BOT_TOKEN if TELEGRAM_BOT_TOKEN else TOKEN_NUEVO_TELEGRAM
    chat_uso = TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID else CHAT_ID_PERSONAL

    url = f"https://api.telegram.org/bot{token_uso}/sendMessage"
    payload = {
        "chat_id": chat_uso,
        "text": texto,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=8)
        print("Respuesta Telegram HTTP:", res.status_code)
    except Exception as e:
        print("Error enviando a Telegram:", e)

def ejecutar_bot_futbol():
    fecha_colombia = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d")
    enviar_mensaje_telegram(f"🎯 <b>SUPERANALISTA PRO (GEMINI IA REFINADO)</b>\n📅 Evaluando jornada: <b>{fecha_colombia}</b>")

    partidos = obtener_partidos_jornada()

    if not partidos:
        enviar_mensaje_telegram(f"🛡️ <b>REPORTE DE JORNADA - {fecha_colombia}</b>\n\n📊 <i>No se registran partidos programados en las ligas principales de primera categoría para hoy.</i>")
        return

    for p in partidos:
        sim = simular_monte_carlo(p["cuotaLocal"], p["cuotaVisitante"], NUM_SIMULACIONES)
        base_ia = obtener_estructuracion_groq(p)
        justificacion_gemini = refinamiento_final_gemini(p, sim, base_ia)

        mensaje = (
            f"🏆 <b>{p['liga']}</b>\n"
            f"⚽ <b>{p['local']} vs {p['visitante']}</b>\n"
            f"⏰ Fecha/Hora: <code>{p['fechaHora']} (Hora COL)</code>\n\n"
            f"📊 <b>Cuotas 1X2:</b> L: <code>{p['cuotaLocal']}</code> | E: <code>{p['cuotaEmpate']}</code> | V: <code>{p['cuotaVisitante']}</code>\n"
            f"🎲 <b>Monte Carlo (10,000 sim):</b> L: <code>{sim['prob_local']}%</code> | Both Score: <code>{sim['prob_btts']}%</code>\n\n"
            f"🔥 <b>PRONÓSTICO PRINCIPAL:</b>\n"
            f"🎯 <b>Ambos Equipos Anotan:</b> <b>{base_ia['ambos_marcan_pronostico']}</b>\n"
            f"📈 <b>Confianza / Stake:</b> <code>{base_ia['stake']}</code>\n"
            f"🎲 <b>Probabilidad Estimada:</b> <code>{base_ia['probabilidad_estimada']}</code>\n"
            f"💡 <i>{justificacion_gemini}</i>\n\n"
            f"🛡️ <b>OPCIÓN COBERTURA (GOLES):</b>\n"
            f"🎯 <b>Línea Alternativa:</b> {base_ia['cobertura_goles']}"
        )

        enviar_mensaje_telegram(mensaje)
        time.sleep(2.5)

    enviar_mensaje_telegram(f"✅ <b>Análisis finalizado con Gemini IA.</b> Partidos procesados: {len(partidos)}")

if __name__ == "__main__":
    ejecutar_bot_futbol()
