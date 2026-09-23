import math
import time
import os
from telebot import TeleBot

# ==============================================================================
# CONFIGURACIÓN Y CREDENCIALES (Variables de Entorno o Directas)
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8650458483:AAFcREwoHQwVvm293oc2jDxKHe1H5VdsNyg")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8707489920")

bot = TeleBot(TELEGRAM_BOT_TOKEN)

# Umbral dinámico flexible (Matemática Poisson + Ajuste IA)
UMBRAL_MINIMO_CONFIANZA = 70.0  

# ==============================================================================
# MOTOR MATEMÁTICO: POISSON & xG (LIGAS PRINCIPALES DE FÚTBOL)
# ==============================================================================

def calcular_poisson(k, lambda_param):
    return (math.pow(lambda_param, k) * math.exp(-lambda_param)) / math.factorial(k)

def analizar_partido(equipo_local, equipo_visita, xg_local, xg_visita, ajuste_ia=0.0, nota_ia=""):
    prob_mas_1_5 = 0.0
    prob_mas_2_5 = 0.0
    
    # Matriz de probabilidad de Poisson hasta 5 goles por equipo
    for goles_l in range(6):
        prob_l = calcular_poisson(goles_l, xg_local)
        for goles_v in range(6):
            prob_v = calcular_poisson(goles_v, xg_visita)
            prob_resultado = prob_l * prob_v
            
            total_goles = goles_l + goles_v
            if total_goles > 1:
                prob_mas_1_5 += prob_resultado
            if total_goles > 2:
                prob_mas_2_5 += prob_resultado

    prob_base = round(prob_mas_2_5 * 100, 1)
    prob_final = round(prob_base + ajuste_ia, 1)

    return {
        "equipo_local": equipo_local,
        "equipo_visita": equipo_visita,
        "xg_local": xg_local,
        "xg_visita": xg_visita,
        "prob_base": prob_base,
        "ajuste_ia": ajuste_ia,
        "prob_final": prob_final,
        "nota_ia": nota_ia
    }

# ==============================================================================
# GENERACIÓN Y FORMATO DEL REPORTE A TELEGRAM
# ==============================================================================

def generar_reporte_prepartido(analisis_partidos):
    fecha_actual = time.strftime("%Y-%m-%d")
    
    mensaje = f"⚽ <b>INFORME CUANTITATIVO PRE-PARTIDO (MODELO HÍBRIDO)</b>\n"
    mensaje += f"📅 <b>Fecha:</b> {fecha_actual}\n"
    mensaje += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # Filtro flexible: Selecciona partidos con confianza combinada >= 70%
    partidos_validos = [p for p in analisis_partidos if p["prob_final"] >= UMBRAL_MINIMO_CONFIANZA]

    if not partidos_validos:
        mensaje += f"⚠️ <b>ANÁLISIS DE JORNADA COMPLETADO</b>\n"
        mensaje += f"Hoy se evaluaron las ligas principales, pero <b>ningún partido alcanzó el umbral del {UMBRAL_MINIMO_CONFIANZA}%</b> de confianza combinada (Matemática + IA).\n\n"
        mensaje += f"🛡️ <i>Recomendación del sistema: No operar el día de hoy para proteger capital.</i>\n"
    else:
        for partido in partidos_validos:
            etiqueta = "🟢 *(Alta Confianza)*" if partido["prob_final"] >= 80.0 else "🟡 *(Oportunidad Moderada)*"
            signo_ia = "+" if partido["ajuste_ia"] >= 0 else ""
            
            mensaje += f"🏟️ <b>{partido['equipo_local']} vs. {partido['equipo_visita']}</b>\n"
            mensaje += f" ├ 📈 Goles Esperados (xG): Local {partido['xg_local']} | Visita {partido['xg_visita']}\n"
            mensaje += f" ├ 🧮 Prob. Matemática Base: {partido['prob_base']}%\n"
            mensaje += f" ├ 🧠 Ajuste Contextual IA: {signo_ia}{partido['ajuste_ia']}% ({partido['nota_ia']})\n"
            mensaje += f" └ 🎯 <b>PUNTUACIÓN FINAL COMBINADA: {partido['prob_final']}%</b> {etiqueta}\n\n"

    mensaje += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    mensaje += f"💡 <i>Análisis generado mediante modelo estocástico en Python + validación cualitativa de IA.</i>"

    return mensaje

def ejecutar_analisis_diario():
    # Ingesta/Simulación de partidos de Ligas Principales
    partidos_jornada = [
        {"local": "Real Madrid", "visita": "Barcelona", "xg_l": 1.85, "xg_v": 1.45, "ajuste": 5.0, "nota": "Titulares confirmados"},
        {"local": "Arsenal", "visita": "Chelsea", "xg_l": 1.60, "xg_v": 1.10, "ajuste": -3.0, "nota": "Lluvia intensa prevista"},
        {"local": "Bayern Múnich", "visita": "Dortmund", "xg_l": 2.20, "xg_v": 1.35, "ajuste": 4.5, "nota": "Ritmo ofensivo alto"}
    ]

    resultados = []
    for p in partidos_jornada:
        res = analizar_partido(p["local"], p["visita"], p["xg_l"], p["xg_v"], p["ajuste"], p["nota"])
        resultados.append(res)

    texto_reporte = generar_reporte_prepartido(resultados)

    try:
        bot.send_message(TELEGRAM_CHAT_ID, texto_reporte, parse_mode="HTML")
        print("✅ Reporte pre-partido despachado con éxito a Telegram.")
    except Exception as e:
        print(f"❌ Error al enviar reporte a Telegram: {e}")

if __name__ == "__main__":
    ejecutar_analisis_diario()