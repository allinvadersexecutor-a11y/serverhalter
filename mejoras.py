import json
import re
import sys
import zipfile

FN = "data/chem/function/"
ADV = "data/chem/advancement/"
ESTACIONES = {1: "Horno de alta temperatura", 2: "Reactor químico", 3: "Electrolizador", 4: "Mesa de purificación", 5: "Mesa de síntesis", 6: "Celda galvánica"}
VAL = re.compile(r'(\w+):("[^"]*"|-?\d+)')


def j(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def info_reaccion(texto):
    for linea in texto.split("\n"):
        if "chem_n matches 1 run tellraw @s" in linea:
            arr = json.loads(linea.split("run tellraw @s ", 1)[1])
            if len(arr) >= 4 and "→" in arr[3].get("text", ""):
                return arr[2]["text"].rstrip(": "), arr[3]["text"]
    raise ValueError("sin título de reacción")


def que_puedo(files):
    lineas = [
        "scoreboard players set @s chem_pp 0",
        "scoreboard players set @s chem_h 0",
        "tellraw @s " + j(["", {"text": "[Chem] ", "color": "aqua"}, {"text": "Reacciones posibles aquí y ahora (clic para ejecutar):", "color": "yellow"}]),
    ]
    n = 0
    while True:
        n += 1
        k = "%03d" % n
        ruta = FN + "r/%s.mcfunction" % k
        if ruta not in files:
            break
        nombre, ecuacion = info_reaccion(files[ruta].decode("utf-8"))
        txt = [
            {"text": "  • ", "color": "gray"},
            {"text": nombre, "color": "green", "bold": True,
             "click_event": {"action": "run_command", "command": "/trigger chem_react set %d" % n},
             "hover_event": {"action": "show_text", "value": {"text": "Reacción %d: clic para ejecutar" % n}}},
            {"text": "  " + ecuacion, "color": "white"},
            {"text": "  [%d]" % n, "color": "gray"},
        ]
        lineas.append("execute store result score @s chem_pk run function chem:c/%s" % k)
        lineas.append("execute if score @s chem_pk matches 1 run scoreboard players add @s chem_pp 1")
        lineas.append("execute if score @s chem_pk matches 1 run tellraw @s " + j(txt))
    lineas.append("execute if score @s chem_pp matches 0 run tellraw @s " + j(["", {"text": "[Chem] ", "color": "aqua"}, {"text": "Nada posible ahora: acércate a una estación (menos de 6 bloques) y lleva los reactivos en el inventario.", "color": "red"}]))
    files[FN + "que_puedo.mcfunction"] = ("\n".join(lineas) + "\n").encode("utf-8")
    return n - 1


def agregar_linea(files, ruta, despues, nueva):
    L = files[ruta].decode("utf-8").split("\n")
    i = L.index(despues) + 1 if despues else len(L)
    if not despues and L and L[-1] == "":
        i = len(L) - 1
    L.insert(i, nueva)
    files[ruta] = "\n".join(L).encode("utf-8")


def enganches(files):
    agregar_linea(files, FN + "dispatch.mcfunction", "scoreboard players set @s chem_h 0", "execute if score @s chem_react matches 906 run function chem:que_puedo")
    agregar_linea(files, FN + "load.mcfunction", None, "scoreboard objectives add chem_pp dummy")
    agregar_linea(files, FN + "load.mcfunction", None, "scoreboard objectives add chem_pk dummy")
    agregar_linea(files, FN + "help.mcfunction", None, "tellraw @s " + j(["", {"text": "¿Qué puedo hacer?: /trigger chem_react set 906 lista las reacciones posibles con lo que llevas y la estación cercana; clic en una para ejecutarla.", "color": "green"}]))


def carteles(files):
    for k, nombre in ESTACIONES.items():
        linea = 'execute if score @s chem_t matches %d run summon text_display ~ ~1.3 ~ {text:{text:"%s",color:"gold",bold:true},billboard:"center",Tags:["chemx9a41_lbl"]}' % (k, nombre)
        agregar_linea(files, FN + "estacion/spawn.mcfunction", None, linea)
    agregar_linea(files, FN + "estacion/destruir.mcfunction", None, "execute positioned ~ ~1.3 ~ run kill @e[type=text_display,tag=chemx9a41_lbl,distance=..0.3]")


def logros(files):
    comp = []
    for ruta in sorted(files):
        if ruta.startswith(FN + "give/c/") and ruta.endswith(".mcfunction"):
            t = files[ruta].decode("utf-8")
            cd = re.search(r"custom_data=\{chem:\{(.*?)\}\}", t)
            nombre = re.search(r'custom_name=\{"text":"([^"]+)"', t)
            formula = re.search(r'"text":"Fórmula: ([^"]+)"', t)
            modelo = re.search(r'item_model="chem:(\w+)"', t)
            if not (cd and nombre and modelo):
                continue
            datos = {}
            for k, v in VAL.findall(cd.group(1)):
                datos[k] = json.loads(v)
            comp.append((ruta[len(FN + "give/c/"):-len(".mcfunction")], nombre.group(1), formula.group(1) if formula else nombre.group(1), modelo.group(1), datos))
    icono = lambda m: {"id": "minecraft:disc_fragment_5", "components": {"minecraft:item_model": "chem:" + m}}
    files[ADV + "comp/raiz.json"] = j({
        "display": {"icon": icono(comp[0][3]), "title": {"text": "Chem · Compuestos"}, "description": {"text": "Sintetiza cada compuesto del catálogo."}, "show_toast": False, "announce_to_chat": False},
        "criteria": {"t": {"trigger": "minecraft:tick"}},
    }).encode("utf-8")
    for stem, nombre, formula, modelo, datos in comp:
        files[ADV + "comp/%s.json" % stem] = j({
            "parent": "chem:comp/raiz",
            "display": {"icon": icono(modelo), "title": {"text": nombre}, "description": {"text": "Consigue 1 mol de %s" % formula}, "frame": "task", "show_toast": True, "announce_to_chat": False},
            "criteria": {"t": {"trigger": "minecraft:inventory_changed", "conditions": {"items": [{"items": "minecraft:disc_fragment_5", "components": {"minecraft:custom_data": {"chem": datos}}}]}}},
        }).encode("utf-8")
    return len(comp)


def mejorar(src, dst):
    with zipfile.ZipFile(src) as z:
        orden = [i.filename for i in z.infolist() if not i.is_dir()]
        files = {n: z.read(n) for n in orden}
    r = {"reacciones": que_puedo(files)}
    enganches(files)
    carteles(files)
    r["logros"] = logros(files)
    nuevos = [n for n in files if n not in orden]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in orden + sorted(nuevos):
            zo.writestr(n, files[n])
    r["archivos_nuevos"] = len(nuevos)
    return r


if __name__ == "__main__":
    print(mejorar(sys.argv[1], sys.argv[2]))
