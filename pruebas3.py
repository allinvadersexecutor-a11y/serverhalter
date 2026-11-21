import os
import sys
import threading
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selftest as s
import chem_mcp as m
import mejoras as mj
import mejoras2 as mj2
import pruebas2 as p2


def mejorar_world3():
    d = os.path.join(m.ROOT, "world", "datapacks")
    res = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".zip") and f.startswith("chem"):
            src = os.path.join(d, f)
            t1 = src + ".1"
            t2 = src + ".2"
            a = mj.mejorar(src, t1)
            b = mj2.mejorar2(t1, t2)
            os.replace(t2, src)
            os.remove(t1)
            with zipfile.ZipFile(src, "a") as z:
                z.writestr("data/chem/function/zz_test_gas.mcfunction", "summon marker ~ ~ ~ {Tags:[\"chemx9a41_gas\",\"chemx9a41_gas_co\"]}\nexecute as @e[type=marker,tag=chemx9a41_gas_co,distance=..1] run scoreboard players set @s chem_gt 900\n")
            res.append([f, a, b])
    return res


def rcs(cmds):
    last = None
    for _ in range(4):
        try:
            return m.rcon(cmds)
        except Exception as e:
            last = e
            time.sleep(3)
    raise last


def dar(stem, ident):
    s.rc("clear ChemBot")
    s.rc("execute as ChemBot run function chem:give/c/%s {n:1}" % stem)
    s.bot("wait", ticks=80)
    s.bot("hotbar", match='"%s"' % ident)
    return s.bot("chat", text="/trigger chem_react set 912", wait=120)["mensajes_nuevos"]


def gas(casco):
    s.rc("clear ChemBot")
    s.rc("effect clear ChemBot")
    s.rc("item replace entity ChemBot armor.head with %s" % ("minecraft:leather_helmet" if casco else "minecraft:air"))
    s.rc("execute at ChemBot run function chem:zz_test_gas")
    s.bot("wait", ticks=240)
    d = {}
    d["marcadores"] = s.rc("execute if entity @e[type=marker,tag=chemx9a41_gas_co]")
    d["gt"] = s.rc("execute as @e[type=marker,tag=chemx9a41_gas_co] run scoreboard players get @s chem_gt")
    d["efectos"] = s.rc("data get entity ChemBot active_effects")
    d["casco"] = s.rc("data get entity ChemBot equipment.head")
    s.rc("kill @e[type=marker,tag=chemx9a41_gas]")
    return d


def quemadura(bata):
    s.rc("effect give ChemBot minecraft:instant_health 1 20")
    s.rc("item replace entity ChemBot armor.chest with %s" % ("minecraft:leather_chestplate" if bata else "minecraft:air"))
    s.bot("wait", ticks=120)
    s.rc("scoreboard players set ChemBot chem_e 3500")
    s.rc("execute as ChemBot run function chem:calor")
    return s.rc("scoreboard players get ChemBot chem_t")


def run3():
    st = s.step
    st("mem_inicio", s.mem)
    best = s.find_world()
    jar = st("descarga_jar", lambda: m.fetch_jar("1.21.6"))
    if not jar:
        return
    st("setup", lambda: m.t_setup({"server_jar": jar, "properties": {"view-distance": 2, "simulation-distance": 2}}))
    if best:
        st("extraer_mundo", lambda: s.extract_world(best))
    st("rebase", s.rebase_world)
    st("mejoras", mejorar_world3)
    st("start", lambda: m.t_start({"timeout": 400}))
    if not m.running():
        s.out("servidor_muerto", {"stdout": s.tail(os.path.join(m.ROOT, "stdout.txt"))})
        return
    st("errores_de_carga", p2.errores)
    st("datapacks", lambda: s.rc("datapack list"))
    st("bot_connect", lambda: m.t_bot_connect({}))
    if not m.bot_alive():
        s.out("bot_muerto", {"log": s.tail(os.path.join(m.ROOT, "bot.log"))})
        return
    st("asentar", lambda: s.bot("wait", ticks=300))
    st("survival", lambda: s.rc("gamemode survival ChemBot"))
    st("entorno_seguro", lambda: [s.rc("difficulty peaceful"), s.rc("time set day"), s.rc("kill @e[type=zombie]")])
    for stem, ident in (("naoh", "NaOH"), ("ch3cooh", "CH3COOH"), ("nh3", "NH3"), ("so2", "SO2")):
        st("ph_" + stem, lambda stem=stem, ident=ident: dar(stem, ident))
    st("ph_sin_nada", lambda: (s.rc("clear ChemBot"), s.bot("wait", ticks=60), s.bot("chat", text="/trigger chem_react set 912", wait=120)["mensajes_nuevos"])[2])
    st("gas_sin_casco_efecto", lambda: gas(False))
    st("gas_con_casco_efecto", lambda: gas(True))
    st("quemadura_sin_bata", lambda: quemadura(False))
    st("quemadura_con_bata", lambda: quemadura(True))
    st("errores_finales", p2.errores)
    st("mem_final", s.mem)
    st("parar", lambda: m.t_stop({}))
    s.out("FIN3", {"ok": True})


if __name__ == "__main__":
    if os.environ.get("CHEM_TEST") == "1":
        threading.Thread(target=run3, daemon=True).start()
    m.serve()
