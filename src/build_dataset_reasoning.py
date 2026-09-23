import json
import os
import re
import sys
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def create_reasoning_dataset():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(base_dir, "..")) if os.path.basename(base_dir) == "src" else base_dir
    csv_candidates = [
        os.path.join(project_root, "data", "dataset_perfumeria.csv"),
        os.path.join(base_dir, "dataset_perfumeria.csv")
    ]
    csv_path = next((p for p in csv_candidates if os.path.exists(p)), csv_candidates[0])
    df = pd.read_csv(csv_path)

    dataset = []

    system_prompt = (
        "Eres un maestro perfumista y químico de fragancias de alta gama. "
        "Posees un conocimiento enciclopédico de perfumes comerciales, pirámides olfativas, "
        "química de fijadores y formulación artesanal en laboratorio. "
        "Respondes siempre en español con precisión técnica, claridad, elegancia y rigor profesional."
    )

    # =========================================================================
    # 1. BLOQUE DE QUÍMICA, FORMULACIÓN Y MATEMÁTICAS DE LABORATORIO
    # =========================================================================
    technical_examples = [
        {
            "q": "¿Cómo se realiza el proceso de maceración de un perfume y para qué sirve?",
            "a": "La maceración es el proceso físico-químico mediante el cual los aceites esenciales, sintéticos y fijadores se disuelven y enlazan íntimamente con el alcohol etílico y el agua desmineralizada.\n\n### Fases del proceso:\n1. **Mezcla inicial**: Se combina el concentrado aromático (15-20% para un EDP) con alcohol etílico desodorizado de 96° y agua desmineralizada.\n2. **Maduración y Enlace**: Se guarda la mezcla en botellas de vidrio ámbar, herméticamente selladas, en un lugar oscuro y a temperatura controlada (15°C a 18°C).\n3. **Tiempo de reposo**: El tiempo mínimo recomendado es de **3 a 6 semanas**. Durante este periodo ocurren reacciones de esterificación y equilibrio molecular que eliminan las notas punzantes del alcohol y redondean los acordes olfativos.\n4. **Maceración en frío (opcional)**: Para formulaciones que contienen aceites naturales ricos en ceras, se somete a 0°C - 4°C durante 48 horas para precipitar ceras insolubles y filtrar con papel filtro cuantitativo, evitando que el perfume se enturbie con el tiempo."
        },
        {
            "q": "¿Qué cálculos matemáticos y proporciones se usan para formular 100 ml de Eau de Parfum (EDP) al 18%?",
            "a": "Para preparar 100 ml de Eau de Parfum al 18% de concentración con alcohol de 96° y agua desmineralizada, los cálculos estándar son los siguientes:\n\n### 1. Proporciones por volumen:\n- **Concentrado de fragancia (18%)**: 18 ml (aprox. 17.1 g, asumiendo densidad media de 0.95 g/ml).\n- **Alcohol etílico desodorizado 96° (78%)**: 78 ml.\n- **Agua desmineralizada (4%)**: 4 ml.\n\n### 2. Procedimiento de laboratorio:\n1. Pesar y disolver los 18 ml de fragancia junto a los fijadores (ej. 0.5% - 1% de Ambroxan o Iso E Super si no están ya en la fórmula).\n2. Agregar lentamente los 78 ml de alcohol mientras se agita suavemente con varilla de vidrio hasta homogeneidad total.\n3. Añadir los 4 ml de agua gota a gota al final. Si la solución muestra ligero enturbiamiento (*efecto Ouzo/louching*), dejar reposar 48 horas antes de decidir si requiere solubilizante o filtración en frío.\n4. Sellar y dejar macerar de 3 a 4 semanas antes del embotellado final."
        },
        {
            "q": "¿Cuáles son las diferencias de concentración entre Splash, EDC, EDT, EDP y Parfum?",
            "a": "La clasificación de las fragancias depende de la relación entre el concentrado de esencia aromática y el vehículo solvente (alcohol y agua):\n\n| Categoría | Concentración de Esencia | Longevidad Típica | Uso Recomendado |\n| :--- | :---: | :---: | :--- |\n| **Body Splash / Eau Fraîche** | 1% a 3% | 1 a 2 horas | Post-ducha, verano, refrescante |\n| **Eau de Cologne (EDC)** | 3% a 5% | 2 a 3 horas | Salida cítrica clásica, uso diario |\n| **Eau de Toilette (EDT)** | 8% a 12% | 4 a 6 horas | Proyección vibrante, versátil |\n| **Eau de Parfum (EDP)** | 15% a 20% | 7 a 10 horas | Gran fijación, estela moderada-fuerte |\n| **Extrait de Parfum (Parfum)** | 20% a 30% | 12+ horas | Máxima riqueza y fijación sobre piel |\n\n> A mayor concentración, la fragancia proyecta menos hacia el ambiente pero dura mucho más tiempo sobre la piel debido a la menor tasa de evaporación del solvente."
        },
        {
            "q": "¿Qué función cumplen los fijadores en perfumería y cuáles son los más usados?",
            "a": "Los fijadores son sustancias con alto peso molecular y baja presión de vapor que ralentizan la velocidad de evaporación de las notas más volátiles (cítricos y flores ligeras), aumentando la longevidad y redondeando la fragancia.\n\n### Fijadores sintéticos clave:\n1. **Ambroxan**: Aporta un fondo amaderado-ambarado cálido, seco y altamente difusivo. Muy usado en fragancias modernas como *Dior Sauvage*.\n2. **Iso E Super**: Aporta un aura amaderada aterciopelada y transparente con efecto envolvente (*cedro-ámbar*). Protagonista en *Molecule 01* y base de *Terre d'Hermès*.\n3. **Hedione (Dihidrojasmonato de metilo)**: Proporciona luminosidad, radiación y abre los acordes florales sin pesadez.\n4. **Galaxolide / Habanolide / Ethylene Brassylate**: Almizcles policíclicos y macrocíclicos de alta tenacidad que aportan la sensación de 'limpieza', suavidad y fijación prolongada (+24h).\n\n### Fijadores naturales y resinas:\n- **Ládano, Benjuí y Mirra**: Resinas ricas en ácido benzoico y cinámico con aromas dulces balsámicos.\n- **Musgo de roble y Pachulí**: Notas terrosas pesadas que anclan la base de los acordes Chipre y Fougère."
        },
        {
            "q": "¿Por qué mi perfume casero se enturbió al agregarle agua y cómo lo soluciono?",
            "a": "El enturbiamiento (conocido químicamente como **efecto Ouzo o louching**) ocurre cuando los aceites esenciales o moléculas hidrófobas pierden solubilidad al aumentar el porcentaje de agua en la mezcla hidroalcohólica.\n\n### Causas comunes:\n1. **Exceso de agua**: Agregar más del 5% o 8% de agua en un EDP sin solubilizante.\n2. **Presencia de aceites naturales densos**: Esencias como lavanda, naranja, pachulí o resinas contienen terpenos y ceras insolubles en agua.\n\n### Solución técnica:\n1. **Ajuste de alcohol**: Eleva el grado alcohólico agregando alcohol de 96° hasta que la mezcla vuelva a ser transparente.\n2. **Maceración y filtración en frío**: Guarda el frasco a 0°C a 4°C en el refrigerador durante 48 a 72 horas. Las ceras insolubles se congelarán y formarán precipitados sólidos. Pasa el perfume inmediatamente por papel de filtro fino (1 a 5 micras). El líquido resultante permanecerá cristalino a temperatura ambiente."
        },
        {
            "q": "¿Cómo se compone la pirámide olfativa y qué velocidad de evaporación tiene cada fase?",
            "a": "La pirámide olfativa describe la evolución sensorial de un perfume a lo largo del tiempo según la volatilidad molecular de sus componentes:\n\n1. **Notas de Salida (Top Notes)**:\n   - *Duración*: Primeros 15 a 30 minutos.\n   - *Moléculas*: De bajo peso molecular y alta presión de vapor (terpenos como limoneno, bergamota, cítricos, menta, aldehídos).\n   - *Propósito*: Primera impresión e impacto inicial.\n2. **Notas de Corazón (Heart / Middle Notes)**:\n   - *Duración*: De 2 a 4 horas.\n   - *Moléculas*: Peso molecular medio (flores como jazmín, rosa, geranio; especias como cardamomo, canela, pimienta; notas verdes).\n   - *Propósito*: El núcleo y la identidad temática del perfume.\n3. **Notas de Fondo (Base Notes)**:\n   - *Duración*: De 6 a 24+ horas.\n   - *Moléculas*: Alto peso molecular y baja volatilidad (maderas como sándalo y cedro, resinas, vainilla, ámbar, ambroxan, almizcles).\n   - *Propósito*: Fijación, estela profunda y persistencia sobre la piel y ropa."
        }
    ]

    for item in technical_examples:
        dataset.append({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": item["q"]},
                {"role": "assistant", "content": item["a"]}
            ]
        })

    # =========================================================================
    # 2. BLOQUE DE CONSULTAS DE CATÁLOGO (DEL CSV CON DIVERSIDAD DE PROMPTS)
    # =========================================================================
    for _, row in df.iterrows():
        nombre = row["nombre"]
        marca = row["marca"]
        anio = row["anio_lanzamiento"]
        perfumista = row["perfumista"]
        genero = row["genero"]
        familia = row["familia_olfativa"]
        salida = row["notas_salida"]
        corazon = row["notas_corazon"]
        fondo = row["notas_fondo"]
        duracion = row["duracion"]
        estela = row["estela"]

        # Diálogo Tipo A: Consulta técnica completa formal
        dataset.append({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"¿Cuáles son las notas y características del perfume {nombre}?"},
                {"role": "assistant", "content": (
                    f"**{nombre}** ({marca}, {anio})\n"
                    f"- **Perfumista:** {perfumista}\n"
                    f"- **Género:** {genero} | **Familia olfativa:** {familia}\n"
                    f"- **Pirámide olfativa:**\n"
                    f"  - *Notas de salida:* {salida}\n"
                    f"  - *Notas de corazón:* {corazon}\n"
                    f"  - *Notas de fondo:* {fondo}\n"
                    f"- **Rendimiento:** Duración {duracion.lower()} y estela {estela.lower()}."
                )}
            ]
        })

        # Diálogo Tipo B: Consulta directa por nombre corto o informal
        # Ej: "santal 33", "sauvage", "aventus"
        nombre_corto = re.sub(r'^(Chanel|Dior|Tom Ford|Yves Saint Laurent|YSL|Armani|Versace|Paco Rabanne|Jean Paul Gaultier|Carolina Herrera|Prada|Burberry|Gucci|Dolce & Gabbana|Hugo Boss|Calvin Klein|Lancôme|Guerlain|Narciso Rodriguez|Viktor & Rolf|Thierry Mugler|Mugler|Le Labo|Creed)\s+', '', nombre, flags=re.IGNORECASE).strip()
        
        if len(nombre_corto) >= 3 and nombre_corto.lower() != nombre.lower():
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": nombre_corto},
                    {"role": "assistant", "content": (
                        f"**{nombre}** es una emblemática creación de la casa **{marca}** (lanzada en {anio} por el perfumista {perfumista}).\n\n"
                        f"- **Familia:** {familia} ({genero})\n"
                        f"- **Salida:** {salida}\n"
                        f"- **Corazón:** {corazon}\n"
                        f"- **Fondo:** {fondo}\n"
                        f"- **Rendimiento:** Ofrece una duración {duracion.lower()} con estela {estela.lower()}."
                    )}
                ]
            })

    # =========================================================================
    # 3. BLOQUE DE CONSULTAS POR MARCA Y FAMILIA OLFATIVA
    # =========================================================================
    for brand, group in df.groupby("marca"):
        if len(group) >= 2:
            perfumes_list = "\n".join([f"- **{r.nombre}** ({r.anio_lanzamiento}): {r.familia_olfativa} ({r.genero})" for _, r in group.iterrows()])
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"¿Qué referencias de {brand} conoces en tu catálogo?"},
                    {"role": "assistant", "content": f"En el catálogo de **{brand}** destacan las siguientes referencias:\n\n{perfumes_list}\n\nCada una posee una pirámide olfativa y perfil distintivo. ¿Te gustaría conocer la ficha técnica o notas de alguna en particular?"}
                ]
            })
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"de {brand.lower()}"},
                    {"role": "assistant", "content": f"De la casa **{brand}** disponemos de las siguientes referencias:\n\n{perfumes_list}"}
                ]
            })

    # Consultas por familias aromáticas
    familias_clave = ["Amaderado aromático", "Oriental floral", "Cítrico aromático", "Floral frutal", "Amaderado especiado"]
    for fam in familias_clave:
        sub = df[df["familia_olfativa"].str.contains(fam, case=False, na=False)]
        if len(sub) > 0:
            sample_list = "\n".join([f"- **{r.nombre}** ({r.marca}): salida de {r.notas_salida}, duración {r.duracion.lower()}." for _, r in sub.head(4).iterrows()])
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Recomiéndame perfumes de la familia {fam.lower()}."},
                    {"role": "assistant", "content": f"Para la familia **{fam}**, algunas de las mejores opciones del catálogo son:\n\n{sample_list}\n\n¿Buscas una opción para uso diario, formal o alguna nota en particular?"}
                ]
            })

    # =========================================================================
    # 4. BLOQUE DEL CATÁLOGO WEB DE ALTA DENSIDAD (PRODUCTOS, PRECIOS, ENVASES)
    # =========================================================================
    web_catalog_path = os.path.join(project_root, "data", "catalogo_web_completo.json")
    if os.path.exists(web_catalog_path):
        with open(web_catalog_path, "r", encoding="utf-8") as f:
            web_data = json.load(f)

        web_productos = web_data.get("productos", [])
        web_envases = web_data.get("envases", [])
        web_kits = web_data.get("kits", [])
        web_top10 = web_data.get("top10", [])

        # 4.1 Fichas detalladas y diversificadas de cada producto del catálogo web
        OPENERS = [
            "¡Una magnífica elección! **{nombre}** destaca en nuestra colección **{categoria}** ({genero}):",
            "Para quienes buscan distinción y presencia, **{nombre}** es una propuesta sobresaliente de la línea **{categoria}**:",
            "**{nombre}** es una fragancia con gran carácter dentro de la categoría **{categoria}** ({genero}):",
            "Dentro de nuestra perfumería **{categoria}**, **{nombre}** es un referente indiscutible de elegancia:",
            "Si te atraen las composiciones con alta fijación, **{nombre}** ({genero}) te va a fascinar:",
            "Con un equilibrio impecable entre proyección y sutileza, **{nombre}** cautiva desde el primer segundo:",
            "**{nombre}** ({categoria}) ofrece una experiencia olfativa envolvente y memorable:",
            "Diseñada para destacar, **{nombre}** combina materias primas nobles con un rendimiento excepcional:"
        ]

        CLOSERS = [
            "¿La imaginas más para el uso diario en oficina o para una ocasión especial nocturna?",
            "¿Prefieres aromas de evolución fresca o te llaman la atención los acordes amaderados y dulces?",
            "Tiene una fijación real en piel de 8 a 10 horas. Se recomiendan de 5 a 6 atomizaciones en puntos de pulso.",
            "¿Te gustaría conocer qué otras fragancias de perfil similar tenemos disponibles?",
            "¿Buscas esta fragancia para tu colección personal o es para regalar?",
            "¿En qué clima o temporada planeas lucirla principalmente?",
            "¿Deseas conocer las opciones de envases de vidrio disponibles para esta referencia?",
            "Su estela proyecta con gran elegancia durante las primeras horas de aplicación."
        ]

        for i, p in enumerate(web_productos):
            nombre = p.get("nombre", "").strip()
            categoria = p.get("categoria", "Alta Perfumería")
            genero = p.get("genero", "Unisex")
            precio = p.get("precio", 0)
            precio_fmt = f"${precio:,.0f} COP".replace(",", ".")
            desc = p.get("descripcion", "").strip()
            tallas_str = ", ".join(p.get("tallas", [])) if p.get("tallas") else "100ml"
            envases_str = ", ".join(p.get("tipos_envase", [])) if p.get("tipos_envase") else "Vidrio"

            opener = OPENERS[i % len(OPENERS)].format(nombre=nombre, categoria=categoria, genero=genero)
            closer = CLOSERS[i % len(CLOSERS)]

            # Diálogo W1: Ficha completa con variedad léxica
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"¿Cuáles son las características y el perfil de {nombre}?"},
                    {"role": "assistant", "content": (
                        f"{opener}\n\n"
                        f"- **Perfil Olfativo:** {desc}\n"
                        f"- **Presentación Oficial:** {tallas_str} (Envase de {envases_str})\n"
                        f"- **Precio Oficial:** {precio_fmt}\n"
                        f"- **Duración Real:** 8 a 10 horas en piel.\n\n"
                        f"{closer}"
                    )}
                ]
            })

            # Diálogo W2: Consulta comercial directa
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"cuánto vale {nombre.lower()} y qué envase tiene?"},
                    {"role": "assistant", "content": (
                        f"El perfume **{nombre}** ({categoria} - {genero}) tiene un valor oficial de **{precio_fmt}** en presentación de **{tallas_str}**.\n"
                        f"Viene en envase de **{envases_str}** con válvula atomizadora de alta densidad. Su fijación diaria es de 8 a 10 horas sobre la piel."
                    )}
                ]
            })

        # 4.2 Recomendaciones por categoría y género
        grupos_cat_gen = {}
        for p in web_productos:
            key = (p.get("categoria"), p.get("genero"))
            grupos_cat_gen.setdefault(key, []).append(p)

        for (cat, gen), prods in grupos_cat_gen.items():
            if len(prods) >= 3:
                sample_p = prods[:5]
                items_text = "\n".join([f"- **{x['nombre']}** (${x['precio']:,.0f} COP): {x['descripcion'][:90]}..." for x in sample_p])
                dataset.append({
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Recomiéndame perfumes de categoría {cat.lower()} para {gen.lower()}."},
                        {"role": "assistant", "content": (
                            f"En nuestra colección de perfumería **{cat}** para público **{gen}**, te recomiendo especialmente:\n\n"
                            f"{items_text}\n\n"
                            f"Todas nuestras formulaciones cuentan con alta densidad de concentración para garantizar máxima fijación y estela."
                        )}
                    ]
                })

        # 4.3 Consultas de Top 10 más vendidos
        if web_top10:
            top_lines = "\n".join([f"{t['posicion']}. **{t['nombre']}** ({t.get('categoria', 'Perfume')} - {t.get('genero', 'Unisex')}): ${t.get('precio', 0):,.0f} COP" for t in web_top10])
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "¿Cuáles son los perfumes más vendidos o el Top 10 de la tienda?"},
                    {"role": "assistant", "content": (
                        f"El **Top 10 de fragancias más vendidas y aclamadas** en Alta Densidad es el siguiente:\n\n"
                        f"{top_lines}\n\n"
                        f"Cada uno de estos perfumes destaca por su sobresaliente estela, fijación prolongada y alta satisfacción de nuestros clientes."
                    )}
                ]
            })
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "top 10 perfumes"},
                    {"role": "assistant", "content": f"Aquí tienes nuestro ranking oficial del Top 10:\n\n{top_lines}"}
                ]
            })

        # 4.4 Consultas sobre Envases
        if web_envases:
            envases_sample = web_envases[:6]
            env_lines = "\n".join([f"- **{e['nombre']}** ({e.get('material', 'Vidrio')}): {e.get('descripcion', '')[:80]}..." for e in envases_sample])
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "¿Qué tipos de envases tienen disponibles para los perfumes?"},
                    {"role": "assistant", "content": (
                        f"En Alta Densidad disponemos de una cuidada selección de envases de alta calidad para personalizar tu fragancia:\n\n"
                        f"{env_lines}\n\n"
                        f"Nuestros envases de vidrio grueso protegen la formulación de la luz directa y garantizan una atomización fina y homogénea."
                    )}
                ]
            })

        # 4.5 Consultas sobre Kits
        if web_kits:
            kit_lines = "\n".join([f"- **{k['nombre']}** (${k.get('precio', 0):,.0f} COP): {k.get('descripcion', '')}" for k in web_kits[:5]])
            dataset.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "¿Qué kits o promociones tienen disponibles?"},
                    {"role": "assistant", "content": (
                        f"Disponemos de kits especiales ideales para obsequio o colección personal:\n\n"
                        f"{kit_lines}\n\n"
                        f"¿Te gustaría información sobre algún kit en particular?"
                    )}
                ]
            })

    # =========================================================================
    # 5. BLOQUE CONVERSACIONAL NATURAL Y ASESORÍA HUMANA DE MOSTRADOR
    # =========================================================================
    try:
        from conversational_data import get_conversational_dialogues
    except ImportError:
        from src.conversational_data import get_conversational_dialogues

    conv_dialogues = get_conversational_dialogues(system_prompt)
    dataset.extend(conv_dialogues)
    print(f"Incorporados {len(conv_dialogues)} diálogos conversacionales y de asesoría de mostrador.")

    # Guardar archivo en data/
    out_dir = os.path.join(project_root, "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dataset_reasoning.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)


    print(f"Dataset de razonamiento creado exitosamente con {len(dataset)} diálogos estructurados en: {out_path}")

if __name__ == "__main__":
    create_reasoning_dataset()

