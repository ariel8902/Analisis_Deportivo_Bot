# --- 2. INGESTA DESDE API-FOOTBALL OFICIAL ---
def obtener_partidos_vigentes():
    lista_partidos_validados = []
    hoy_dt = datetime.now(ZONA_HORARIA_COLOMBIA)
    hoy_str = hoy_dt.strftime("%Y-%m-%d")
    limite_dt = hoy_dt + timedelta(days=7)
    limite_str = limite_dt.strftime("%Y-%m-%d")

    print(f"🔍 Consultando API-Football Oficial para partidos vigentes entre {hoy_str} y {limite_str}...")

    if not APISPORTS_KEY:
        print("⚠️ Aviso: APISPORTS_KEY no está configurada en los secretos de GitHub.")
        return []

    url_api = "https://v3.football.api-sports.io/fixtures"
    headers_api = {
        "x-apisports-key": APISPORTS_KEY
    }

    for liga in LIGAS_CONFIGURADAS:
        # Quitamos el parámetro 'season' restrictivo y usamos el rango de fechas directo para evitar vacíos
        params = {
            "league": liga["id_liga"],
            "from": hoy_str,
            "to": limite_str
        }
        try:
            response = requests.get(url_api, headers=headers_api, params=params, timeout=10)
            if response.status_code != 200:
                print(f"Error HTTP {response.status_code} para {liga['nombre']}")
                continue
            
            data = response.json()
            fixtures = data.get("response", [])
            
            for fixture in fixtures:
                teams = fixture.get("teams", {})
                home = teams.get("home", {}).get("name", "Local")
                away = teams.get("away", {}).get("name", "Visitante")
                
                fixture_date = fixture.get("fixture", {}).get("date", "")
                fecha_formateada = fixture_date.replace("T", " ")[:16] if fixture_date else "Próximamente"

                partido_dict = {
                    "liga": liga["nombre"],
                    "local": home,
                    "visitante": away,
                    "fechaHora": f"{fecha_formateada} (Vigente)",
                    "cuotaLocal": "2.10",
                    "cuotaEmpate": "3.40",
                    "cuotaVisitante": "3.20"
                }
                if partido_dict not in lista_partidos_validados:
                    lista_partidos_validados.append(partido_dict)
            time.sleep(1)
        except Exception as e:
            print(f"Aviso consultando API para {liga['nombre']}:", e)

    return lista_partidos_validados
