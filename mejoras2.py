import json
import math
import re
import sys
import zipfile

import mejoras as mj

FN = mj.FN
KW = 1e-14
ACIDOS = {"HF": 6.8e-4, "H2S": 8.9e-8, "CH3COOH": 1.8e-5, "HCOOH": 1.8e-4, "NH4Cl": KW / 1.8e-5}
BASES = {"NH3": 1.8e-5, "Na2CO3": KW / 4.7e-11}
FUERTES_ACIDOS = ["HCl", "HBr", "H2SO4"]
FUERTES_BASES = {"NaOH": 14.0, "Ca(OH)2": 12.3}
FIJOS = {"NaHCO3": (8.3, "anfótero: sal ácida"), "NH2CH2COOH": (6.0, "anfótero: aminoácido (zwitterión)"), "H2O": (7.0, "neutro"), "NaCl": (7.0, "sal neutra"), "KCl": (7.0, "sal neutra")}
OXIDOS = {"Na2O": "óxido básico: con agua forma NaOH", "CaO": "óxido básico: con agua forma Ca(OH)₂", "Li2O": "óxido básico: con agua forma LiOH", "MgO": "óxido básico poco soluble", "SO2": "óxido ácido: con agua forma H₂SO₃", "SO3": "óxido ácido: con agua forma H₂SO₄", "P4O10": "óxido ácido: con agua forma H₃PO₄", "CO2": "óxido ácido: con agua forma H₂CO₃ (ácido débil)"}


def x_debil(k):
    return (-k + math.sqrt(k * k + 4 * k)) / 2


def tabla():
    t = {}
    for i in FUERTES_ACIDOS:
        t[i] = (0.0, "ácido fuerte")
    for i, k in ACIDOS.items():
        x = x_debil(k)
        ph = -math.log10(x)
        t[i] = (round(ph, 1), "ácido débil" if i != "NH4Cl" else "sal ácida")
    for i, k in BASES.items():
        x = x_debil(k)
        t[i] = (round(14 + math.log10(x), 1), "base débil" if i == "NH3" else "sal básica")
    for i, v in FUERTES_BASES.items():
        t[i] = (v, "base fuerte" if i == "NaOH" else "base fuerte, saturada (poco soluble)")
    for i, (v, d) in FIJOS.items():
        t[i] = (v, d)
    return t


def nombres(files):
    r = {}
    for ruta, data in files.items():
        if ruta.startswith(FN + "give/c/") and ruta.endswith(".mcfunction"):
            t = data.decode("utf-8")
            i = re.search(r'custom_data=\{chem:\{(.*?)\}\}', t)
            n = re.search(r'custom_name=\{"text":"([^"]+)"', t)
            if i and n:
                m = re.search(r'id:"([^"]+)"', i.group(1))
                if m:
                    r[m.group(1)] = n.group(1)
    return r


def color(ph):
    return "red" if ph < 6.5 else ("green" if ph <= 7.5 else "aqua")


def ph_func(files):
    nom = nombres(files)
    t = tabla()
    L = ["scoreboard players set @s chem_pp 0"]
    n = 0
    for ident, (ph, desc) in t.items():
        if ident not in nom:
            continue
        sel = '*[minecraft:custom_data~{chem:{id:"%s"}}]' % ident
        msg = ["", {"text": "[Chem] ", "color": "aqua"}, {"text": nom[ident], "color": "white", "bold": True}, {"text": "  pH ≈ %s" % ph, "color": color(ph), "bold": True}, {"text": "  · %s (disolución 1 mol/L, 25 °C, idealizada)" % desc, "color": "gray"}]
        L.append("execute if items entity @s weapon.mainhand %s run scoreboard players add @s chem_pp 1" % sel)
        L.append("execute if items entity @s weapon.mainhand %s run tellraw @s %s" % (sel, mj.j(msg)))
        n += 1
    for ident, desc in OXIDOS.items():
        if ident not in nom:
            continue
        sel = '*[minecraft:custom_data~{chem:{id:"%s"}}]' % ident
        msg = ["", {"text": "[Chem] ", "color": "aqua"}, {"text": nom[ident], "color": "white", "bold": True}, {"text": "  " + desc, "color": "yellow"}]
        L.append("execute if items entity @s weapon.mainhand %s run scoreboard players add @s chem_pp 1" % sel)
        L.append("execute if items entity @s weapon.mainhand %s run tellraw @s %s" % (sel, mj.j(msg)))
        n += 1
    L.append("execute if score @s chem_pp matches 0 run tellraw @s " + mj.j(["", {"text": "[Chem] ", "color": "aqua"}, {"text": "Sostén en la mano un ácido, una base, una sal o un óxido para ver su pH.", "color": "red"}]))
    files[FN + "ph.mcfunction"] = ("\n".join(L) + "\n").encode("utf-8")
    return n


def seguridad(files):
    ruta = FN + "gas_efecto.mcfunction"
    t = files[ruta].decode("utf-8")
    viejo = " as @a[distance=..4,gamemode=!spectator] run effect"
    nuevo = " as @a[distance=..4,gamemode=!spectator] unless items entity @s armor.head minecraft:leather_helmet run effect"
    k = t.count(viejo)
    assert k > 0
    files[ruta] = t.replace(viejo, nuevo).encode("utf-8")
    ruta = FN + "calor.mcfunction"
    L = files[ruta].decode("utf-8").split("\n")
    i = max(n for n, l in enumerate(L) if l.startswith("execute if score @s chem_t matches 1.. run function chem:quemadura"))
    L.insert(i, "execute if items entity @s armor.chest minecraft:leather_chestplate run scoreboard players operation @s chem_t /= #2 chemx9a41_v")
    files[ruta] = "\n".join(L).encode("utf-8")
    return k


def mejorar2(src, dst):
    with zipfile.ZipFile(src) as z:
        orden = [i.filename for i in z.infolist() if not i.is_dir()]
        files = {n: z.read(n) for n in orden}
    r = {"entradas_ph": ph_func(files), "lineas_gas": seguridad(files)}
    mj.agregar_linea(files, FN + "dispatch.mcfunction", "scoreboard players set @s chem_h 0", "execute if score @s chem_react matches 912 run function chem:ph")
    mj.agregar_linea(files, FN + "help.mcfunction", None, "tellraw @s " + mj.j(["", {"text": "pH: /trigger chem_react set 912 con un ácido, base, sal u óxido en la mano. Seguridad: casco de cuero (gafas) anula los gases tóxicos; pechera de cuero (bata) reduce a la mitad las quemaduras por exceso de energía.", "color": "green"}]))
    nuevos = [n for n in files if n not in orden]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in orden + sorted(nuevos):
            zo.writestr(n, files[n])
    r["archivos_nuevos"] = len(nuevos)
    return r


if __name__ == "__main__":
    print(json.dumps(tabla(), ensure_ascii=False))
    print(mejorar2(sys.argv[1], sys.argv[2]))
