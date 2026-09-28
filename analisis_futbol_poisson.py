import os
import math
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta
from google import genai

# --- 1. CONFIGURACIÓN SEGURA DE CREDENCIALES Y ENTORNO ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))
NUM_SIMULACIONES = 10000

# Inicialización de Gemini
client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-3.8-flash'

# Ligas monitoreadas
LIGAS_ODDS = [
    { "nombre": "Liga BetPlay", "sport_key": "soccer_colombia_liga_aguila" },
    { "nombre": "Premier League", "sport_key": "soccer_epl" },
    { "nombre": "LaLiga", "sport_key": "soccer_spain_la_liga" },
    { "nombre": "Serie A", "sport_key": "soccer_italy_serie_a" },
    { "nombre": "Bundesliga", "sport_key": "soccer_germany_bundesliga" }
]

def enviar_mensaje_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram no configuradas.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = { "chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML" }
    try:
        response = requests.post(url, json=payload, timeout=8)
        if response.status_code != 200:
            print(f"Telegram respondió con código {response.status_code}: {response.text}")
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)

# --- 2. INGESTA ESTRICTA DE CORTO PLAZO (MÁXIMO 48 HORAS) ---
def obtener_partidos_odds_api():
    lista_partidos = []
    if not ODDS_API_KEY:
        print("Error: ODDS_API_KEY no está configurada.")
        return []

    ahora_utc = datetime.now(timezone.utc)
    limite_cercano = ahora_utc + timedelta(hours=48)

    for liga in LIGAS_ODDS:
        url = f"https://api.the-odds-api.com/v4/sports/{liga['sport_key']}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu,us",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                print(f"Error {response.status_code} en The Odds API ({liga['nombre']})")
                continue
            
            eventos = response.json()
            for evento in eventos:
                commence_raw = evento.get("commence_time", "")
                if not commence_raw:
                    continue
                
                try:
                    fecha_dt = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
                    if not (ahora_utc <= fecha_dt <= limite_cercano):
                        continue
                    commence_time = fecha_dt.astimezone(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    continue

                home_team = evento.get("home_team")
                away_team = evento.get("away_team")
                
                cuota_local, cuota_empate, cuota_visitante = None, None, None
                
                bookmakers = evento.get("bookmakers", [])
                if bookmakers:
                    markets = bookmakers[0].get("markets", [])
                    for market in markets:
                        if market.get("key") == "h2h":
                            for outcome in market.get("outcomes", []):
                                name = outcome.get("name")
                                price = float(outcome.get("price", 0))
                                if name == home_team: cuota_local = price
                                elif name == away_team: cuota_visitante = price
                                else: cuota_empate = price

                if not cuota_local or not cuota_visitante or not cuota_empate:
                    continue

                lista_partidos.append({
                    "liga": liga["nombre"],
                    "local": home_team,
                    "visitante": away_team,
                    "fechaHora": commence_time,
                    "cuotaLocal": cuota_local,
                    "cuotaEmpate": cuota_empate,
                    "cuotaVisitante": cuota_visitante
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"Error conectando con The Odds API para {liga['nombre']}:", e)

    return lista_partidos

# --- 3. MOTOR ESTOCÁSTICO POISSON / MONTE CARLO ---
def simular_monte_carlo(cuota_loc, cuota_vis, num_sim=10000):
    try:
        prob_loc_impl = 1.0 / cuota_loc
        prob_vis_impl = 1.0 / cuota_vis
    except ZeroDivisionError:
        return None

    lambda_loc = prob_loc_impl * 2.7
    lambda_vis = prob_vis_impl * 2.3

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

# --- 4. INTEGRACIÓN DE MODELOS DE IA ---
def generar_analisis_btts(partido, sim_data):
    if not GROQ_API_KEY:
        return None

    url_api = "https://api.groq.com/openai/v1/chat/completions"
    
    prompt_text = f"""Eres un analista cuantitativo deportivo. Evalúa objetivamente si el mercado "Ambos Anotan" o "Over 2.5" tiene alto valor estadístico.
DATOS:
- Liga: {partido['liga']} | Partido: {partido['local']} vs {partido['visitante']}
- Cuotas 1X2: L ({partido['cuotaLocal']}) | E ({partido['cuotaEmpate']}) | V ({partido['cuotaVisitante']})
- Monte Carlo: BTTS ({sim_data['prob_btts']}%), Over 2.5 ({sim_data['prob_over25']}%)

RESPONDE ÚNICAMENTE EN JSON SINTÁCTICAMENTE VÁLIDO:
{{
  "ambos_marcan_pronostico": "SÍ o NO",
  "stake": "Stake sugerido (ej. 4/5)",
  "probabilidad_estimada": "Porcentaje estimado",
  "cobertura_goles": "Línea alternativa recomendada"
}}"""

    headers = { "Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json" }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt_text}],
        "response_format": {"type": "json_object"}
    }

    try:
        response = requests.post(url_api, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        else:
            print(f"Groq respondió con error HTTP {response.status_code}")
    except Exception as e:
        print("Error en Groq API:", e)
    
    return None

def analisis_tactico_gemini_vip(partido, sim_data):
    if not client_gemini:
        return "Análisis de alta probabilidad apoyado en intensidad anotadora proyectada por Poisson."
    
    prompt = (
        f"Analiza tácticamente el partido {partido['local']} vs {partido['visitante']} ({partido['liga']}). "
        f"Métricas cuantitativas de alta certeza: BTTS {sim_data['prob_btts']}%, Over 2.5 {sim_data['prob_over25']}%. "
        f"Redacta un análisis técnico directo de exactamente 2 oraciones en español. Sin saludos."
    )
    
    try:
        res = client_gemini.models.generate_content(model=MODELO_GEMINI, contents=prompt)
        if res and res.text:
            return res.text.strip()
    except Exception as e:
        print("Error en Gemini API:", e)
            
    return "Proyección fundamentada en dominancia de áreas y alto volumen ofensivo esperable."

# --- 5. ORQUESTADOR PRINCIPAL ---
def ejecutar_analisis_principal():
    fecha_hoy_str = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d %I:%M %p")
    print(f"Iniciando escaneo de corto plazo (Próximas 48h): {fecha_hoy_str}")
    
    partidos = obtener_partidos_odds_api()

    if not partidos:
        aviso_vacio = (
            f"<b>REPORTE DE JORNADA INMEDIATA</b>\n\n"
            f"<i>No hay partidos agendados en las próximas 48 horas con cuotas completas en las ligas monitoreadas.</i>"
        )
        enviar_mensaje_telegram(aviso_vacio)
        return

    enviar_mensaje_telegram(f"<b>ANALIZADOR VIP (CORTO PLAZO 48H | CERTEZA 70%+)</b>\n📅 Escaneo activo: <b>{fecha_hoy_str}</b>")
    partidos_enviados = 0

    for i, partido in enumerate(partidos):
        sim = simular_monte_carlo(partido['cuotaLocal'], partido['cuotaVisitante'], NUM_SIMULACIONES)
        if not sim:
            continue

        if sim['prob_btts'] < 70.0 and sim['prob_over25'] < 70.0:
            continue

        base_ia = generar_analisis_btts(partido, sim)
        
        if i == 0 and client_gemini:
            justificacion = analisis_tactico_gemini_vip(partido, sim)
            etiqueta_ia = "<i>[Análisis VIP Gemini]</i> " + justificacion
        else:
            etiqueta_ia = f"<i>[Métrica Cuantitativa]</i> Alta certeza matemática respaldada por la simulación."

        pronostico_btts = base_ia.get('ambos_marcan_pronostico', 'SÍ') if base_ia else 'SÍ'
        stake_val = base_ia.get('stake', '4/5') if base_ia else '4/5'
        prob_est = base_ia.get('probabilidad_estimada', f"{max(sim['prob_btts'], sim['prob_over25'])}%") if base_ia else f"{max(sim['prob_btts'], sim['prob_over25'])}%"
        cobertura = base_ia.get('cobertura_goles', 'Over 2.5 Goles') if base_ia else 'Over 2.5 Goles'

        mensaje = (
            f"🏆 <b>{partido['liga']}</b>\n"
            f"⚽ <b>{partido['local']} vs {partido['visitante']}</b>\n"
            f"⏰ <b>Fecha:</b> <code>{partido['fechaHora']}</code>\n\n"
            f"📊 <b>Cuotas Mercado:</b> L: <code>{partido['cuotaLocal']}</code> | E: <code>{partido['cuotaEmpate']}</code> | V: <code>{partido['cuotaVisitante']}</code>\n"
            f"🎲 <b>Monte Carlo ({NUM_SIMULACIONES} sim):</b> BTTS: <code>{sim['prob_btts']}%</code> | Over 2.5: <code>{sim['prob_over25']}%</code>\n\n"
            f"🔥 <b>EVALUACIÓN DE ALTA CERTEZA:</b>\n"
            f"🎯 <b>Ambos Equipos Anotan:</b> <b>{pronostico_btts}</b>\n"
            f"📈 <b>Stake Recomendado:</b> <code>{stake_val}</code>\n"
            f"🎲 <b>Probabilidad Estimada:</b> <code>{prob_est}</code>\n"
            f"💡 {etiqueta_ia}\n\n"
            f"🛡️ <b>MERCADO ALTERNATIVO:</b>\n"
            f"🎯 <b>Línea Sostenible:</b> {cobertura}"
        )
        
        enviar_mensaje_telegram(mensaje)
        partidos_enviados += 1
        time.sleep(2)

    enviar_mensaje_telegram(f"<b>Escaneo completado.</b> Pronósticos inmediatos de alta certeza (70%+): {partidos_enviados}")
    print(f"Proceso completado exitosamente. Enviados: {partidos_enviados}")

if __name__ == "__main__":
    ejecutar_analisis_principal()
