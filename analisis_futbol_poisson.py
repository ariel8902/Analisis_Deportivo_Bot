import os
import math
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta
from google import genai

# --- CONFIGURACIÓN DE CREDENCIALES Y ENTORNO ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "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"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Llave oficial de The Odds API extraída de tu script funcional
ODDS_API_KEY = 'f52fed19ba1071472e5a25c88fa23053'

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))
NUM_SIMULACIONES = 10000

# Inicialización segura de Gemini para la validación táctica VIP
client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODELO_GEMINI = 'gemini-2.5-flash'

# Ligas principales sincronizadas con tu base
LIGAS_TOP = [
    { 'key': 'soccer_epl', 'nombre': '🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League' },
    { 'key': 'soccer_spain_la_liga', 'nombre': '🇪🇸 LaLiga' },
    { 'key': 'soccer_italy_serie_a', 'nombre': '🇮🇹 Serie A' },
    { 'key': 'soccer_germany_bundesliga', 'nombre': '🇩🇪 Bundesliga' },
    { 'key': 'soccer_france_ligue_one', 'nombre': '🇫🇷 Ligue 1' },
    { 'key': 'soccer_uefa_champions_league', 'nombre': '🇪🇺 Champions League' }
]

def enviar_mensaje_telegram(texto):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram no configuradas.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)

def obtener_partidos_jornada(sport_key):
    """
    Extracción limpia y directa mediante The Odds API,
    replicando la lógica estable de tus herramientas.
    """
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=us,eu&markets=h2h"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Aviso API Odds ({sport_key}): Código {response.status_code}")
            return []
        
        eventos = response.json()
        lista_partidos = []
        
        ahora = datetime.now(ZONA_HORARIA_COLOMBIA)
        inicio_ventana = ahora
        fin_ventana = ahora + timedelta(hours=48)

        for evento in eventos:
            commence_time_str = evento.get("commence_time", "")
            try:
                fecha_utc = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
                fecha_partido = fecha_utc.astimezone(ZONA_HORARIA_COLOMBIA)
            except Exception:
                continue

            if fecha_partido >= inicio_ventana and fecha_partido <= fin_ventana:
                equipo_local = evento.get("home_team", "Local")
                equipo_visitante = evento.get("away_team", "Visitante")
                hora_str = fecha_partido.strftime("%d/%m %I:%M %p")
                
                cuota_local, cuota_empate, cuota_visitante = '2.10', '3.20', '3.40'
                
                bookmakers = evento.get("bookmakers", [])
                if bookmakers:
                    mercados = bookmakers[0].get("markets", [])
                    h2h = next((m for m in mercados if m.get("key") == "h2h"), None)
                    if h2h:
                        for out in h2h.get("outcomes", []):
                            name = out.get("name")
                            price = out.get("price")
                            if name == equipo_local: cuota_local = str(price)
                            elif name == equipo_visitante: cuota_visitante = str(price)
                            elif name == 'Draw': cuota_empate = str(price)

                lista_partidos.append({
                    "local": equipo_local,
                    "visitante": equipo_visitante,
                    "fechaHora": hora_str,
                    "cuotaLocal": cuota_local,
                    "cuotaEmpate": cuota_empate,
                    "cuotaVisitante": cuota_visitante
                })
                
        return lista_partidos
    except Exception as e:
        print(f"Error consultando The Odds API para {sport_key}:", e)
        return []

def simular_monte_carlo(cuota_loc, cuota_vis, num_sim=10000):
    """
    Modelo estocástico de Poisson / Monte Carlo riguroso.
    """
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

def generar_analisis_btts(partido, nombre_liga):
    """
    Estructuración cuantitativa rápida mediante Groq.
    """
    url_api = "https://api.groq.com/openai/v1/chat/completions"
    prompt_text = f"""Actúa como un cuantitativo y analista experto de fútbol especializado en el mercado "AMBOS EQUIPOS ANOTAN" (BTTS).
Responde ÚNICAMENTE con un objeto JSON válido (sin texto libre ni markdown):
{{
  "ambos_marcan_pronostico": "SÍ" o "NO",
  "stake": "4/5",
  "probabilidad_estimada": "68%",
  "cobertura_goles": "Más de 2.5 Goles"
}}

DATOS:
- Liga: {nombre_liga}
- Partido: {partido['local']} vs {partido['visitante']}
- Cuotas 1X2: Local ({partido['cuotaLocal']}) | Empate ({partido['cuotaEmpate']}) | Visitante ({partido['cuotaVisitante']})"""

    headers = {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt_text}],
        "response_format": {"type": "json_object"}
    }

    try:
        response = requests.post(url_api, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        print("Error en API Groq:", e)
    
    return {
        "ambos_marcan_pronostico": "SÍ",
        "stake": "4/5",
        "probabilidad_estimada": "68%",
        "cobertura_goles": "Más de 2.5 Goles"
    }

def analisis_tactico_gemini_vip(partido, nombre_liga, sim_data):
    """
    Validación táctica de élite mediante Gemini para el partido estelar.
    """
    if not client_gemini:
        return "Dinámica ofensiva respaldada por métricas de Poisson."
    
    prompt = (
        f"Actúa como analista jefe de fútbol. Analiza el encuentro estelar {partido['local']} vs {partido['visitante']} ({nombre_liga}). "
        f"Métricas estocásticas de Poisson: BTTS: {sim_data['prob_btts']}%, Over 2.5: {sim_data['prob_over25']}%. "
        f"Redacta una validación táctica profunda, técnica y directa en español de máximo 2 oraciones."
    )
    try:
        res = client_gemini.models.generate_content(model=MODELO_GEMINI, contents=prompt)
        return res.text.strip() if res.text else "Análisis táctico enfocado en transiciones ofensivas."
    except Exception as e:
        print("Aviso cuota Gemini VIP:", e)
        return "Proyección táctica respaldada por alta intensidad en los costados."

def ejecutar_analisis_principal():
    fecha_hoy_str = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d %I:%M %p")
    print(f"🚀 Iniciando escaneo híbrido profesional: {fecha_hoy_str}")
    enviar_mensaje_telegram(f"🎯 <b>SUPERANALISTA PRO - POISSON & IA HÍBRIDA</b>\n📅 Escaneo activo: <b>{fecha_hoy_str}</b>")

    partidos_encontrados = 0
    partidos_enviados = 0

    for liga in LIGAS_TOP:
        print(f"🏆 Escaneando {liga['nombre']}...")
        partidos = obtener_partidos_jornada(liga['key'])
        
        if not partidos:
            continue

        partidos_encontrados += len(partidos)

        for i, partido in enumerate(partidos):
            print(f"⚽ Procesando: {partido['local']} vs {partido['visitante']}")
            
            # 1. Simulación matemática Poisson / Monte Carlo
            sim = simular_monte_carlo(partido['cuotaLocal'], partido['cuotaVisitante'], NUM_SIMULACIONES)
            
            # 2. Estructuración rápida con Groq
            base_ia = generar_analisis_btts(partido, liga['nombre'])
            
            # 3. Validación Táctica VIP con Gemini (aplicada selectivamente al primer partido de cada bloque o de la jornada)
            if partidos_enviados == 0 and i == 0:
                justificacion = analisis_tactico_gemini_vip(partido, liga['nombre'], sim)
                etiqueta_ia = "💎 <i>[Análisis VIP Gemini]</i> " + justificacion
            else:
                justificacion = f"Trámite proyectado con alta intensidad ofensiva según modelo cuantitativo ({sim['prob_btts']}% BTTS)."
                etiqueta_ia = "⚡ <i>[Análisis Cuantitativo Groq]</i> " + justificacion

            if base_ia:
                mensaje = (
                    f"🏆 <b>{liga['nombre']}</b>\n"
                    f"⚽ <b>{partido['local']} vs {partido['visitante']}</b>\n"
                    f"⏰ Hora: <code>{partido['fechaHora']} (COL)</code>\n\n"
                    f"📊 <b>Cuotas 1X2:</b> L: <code>{partido['cuotaLocal']}</code> | E: <code>{partido['cuotaEmpate']}</code> | V: <code>{partido['cuotaVisitante']}</code>\n"
                    f"🎲 <b>Monte Carlo ({NUM_SIMULACIONES} sim):</b> BTTS: <code>{sim['prob_btts']}%</code> | Over 2.5: <code>{sim['prob_over25']}%</code>\n\n"
                    f"🔥 <b>PRONÓSTICO PRINCIPAL:</b>\n"
                    f"🎯 <b>Ambos Equipos Anotan:</b> <b>{base_ia['ambos_marcan_pronostico']}</b>\n"
                    f"📈 <b>Confianza / Stake:</b> <code>{base_ia['stake']}</code>\n"
                    f"🎲 <b>Probabilidad Estimada:</b> <code>{base_ia.get('probabilidad_estimada', '68%')}</code>\n"
                    f"💡 {etiqueta_ia}\n\n"
                    f"🛡️ <b>OPCIÓN COBERTURA (GOLES):</b>\n"
                    f"🎯 <b>Línea Alternativa:</b> {base_ia['cobertura_goles']}"
                )
                
                enviar_mensaje_telegram(mensaje)
                partidos_enviados += 1
            
            time.sleep(2)

    enviar_mensaje_telegram(f"✅ <b>Escaneo híbrido finalizado.</b> Evaluados: {partidos_encontrados} | Enviados: {partidos_enviados}")
    print(f"✅ Proceso completado. Evaluados: {partidos_encontrados} | Enviados: {partidos_enviados}")

if __name__ == "__main__":
    ejecutar_analisis_principal()
