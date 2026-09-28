def obtener_partidos_vigentes():
    lista_partidos_validados = []
    hoy_dt = datetime.now(ZONA_HORARIA_COLOMBIA)
    
    # Vamos a escanear desde hoy y los próximos 3 días consultando fecha por fecha para garantizar precisión
    print("🔍 Consultando partidos vigentes en API-Football...")

    if not APISPORTS_KEY:
        print("⚠️ Aviso: APISPORTS_KEY no está configurada en los secretos de GitHub.")
        return []

    url_api = "https://v3.football.api-sports.io/fixtures"
    headers_api = {
        "x-apisports-key": APISPORTS_KEY
    }

    # Revisamos el día de hoy y los 3 siguientes de forma individual para evitar fallos de temporada
    for i in range(4):
        dia_consulta = hoy_dt + timedelta(days=i)
        fecha_str = dia_consulta.strftime("%Y-%m-%d")
        
        for liga in LIGAS_CONFIGURADAS:
            params = {
                "league": liga["id_liga"],
                "season": liga["temporada"],
                "date": fecha_str
            }
            try:
                response = requests.get(url_api, headers=headers_api, params=params, timeout=10)
                if response.status_code != 200:
                    continue
                
                data = response.json()
                fixtures = data.get("response", [])
                
                for fixture in fixtures:
                    teams = fixture.get("teams", {})
                    home = teams.get("home", {}).get("name", "Local")
                    away = teams.get("away", {}).get("name", "Visitante")
                    
                    fixture_date = fixture.get("fixture", {}).get("date", "")
                    fecha_formateada = fixture_date.replace("T", " ")[:16] if fixture_date else fecha_str

                    # Evitar duplicados si ya se agregó
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
            except Exception as e:
                print(f"Aviso consultando API para {liga['nombre']}:", e)

    return lista_partidos_validados
