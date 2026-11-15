import math
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selftest as s
import chem_mcp as m
import mejoras as mj

ERR = re.compile(r"ERROR|Failed|Couldn't|Invalid|Exception")


def mejorar_world():
    d = os.path.join(m.ROOT, "world", "datapacks")
    res = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".zip") and f.startswith("chem"):
            src = os.path.join(d, f)
            tmp = src + ".new"
            res.append([f, mj.mejorar(src, tmp)])
            os.replace(tmp, src)
    return res


def errores():
    return [l[:260] for l in m.log_from(0).splitlines() if ERR.search(l)][:30]


def cerca():
    return [[e["name"], e["distance"]] for e in s.bot("entities", max=80)["resultado"] if e["distance"] < 12 and e["name"] in ("interaction", "item_display", "text_display")]


def run2():
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
    st("mejoras", mejorar_world)
    st("start", lambda: m.t_start({"timeout": 400}))
    if not m.running():
        s.out("servidor_muerto", {"stdout": s.tail(os.path.join(m.ROOT, "stdout.txt"))})
        return
    st("errores_de_carga", errores)
    st("datapacks", lambda: s.rc("datapack list"))
    st("bot_connect", lambda: m.t_bot_connect({}))
    if not m.bot_alive():
        s.out("bot_muerto", {"log": s.tail(os.path.join(m.ROOT, "bot.log"))})
        return
    st("asentar", lambda: s.bot("wait", ticks=300))
    st("survival", lambda: s.rc("gamemode survival ChemBot"))
    st("give_h2", lambda: s.rc("execute as ChemBot run function chem:give/c/h2 {n:5}"))
    st("give_o2", lambda: s.rc("execute as ChemBot run function chem:give/c/o2 {n:3}"))
    st("give_reactor", lambda: s.rc("execute as ChemBot run function chem:give_est/reactor"))
    st("esperar_give", lambda: s.bot("wait", ticks=120))
    st("logro_h2_si", lambda: s.rc("execute if entity @a[advancements={chem:comp/h2=true}]"))
    st("logro_agno3_no", lambda: s.rc("execute if entity @a[advancements={chem:comp/agno3=true}]"))
    pos = st("estado", lambda: s.bot("state")["resultado"])
    st("mano_reactor", lambda: s.bot("hotbar", name="ochre_froglight")["resultado"]["name"])
    if pos:
        p = pos["position"]
        x, y, z = math.floor(p["x"]) + 1, math.floor(p["y"]) - 1, math.floor(p["z"])
        st("colocar", lambda: s.bot("place", x=x, y=y, z=z))
    st("esperar_colocacion", lambda: s.bot("wait", ticks=300))
    st("entidades_tras_colocar", cerca)
    st("trigger_906_con_reactivos", lambda: s.bot("chat", text="/trigger chem_react set 906", wait=120))
    st("vaciar_inventario", lambda: s.rc("clear ChemBot"))
    st("esperar_vaciar", lambda: s.bot("wait", ticks=60))
    st("trigger_906_sin_reactivos", lambda: s.bot("chat", text="/trigger chem_react set 906", wait=120))
    st("recoger_estacion", lambda: s.bot("attack", type="interaction", wait=120))
    st("entidades_tras_recoger", cerca)
    st("inventario_final", s.inv)
    st("errores_finales", errores)
    st("mem_final", s.mem)
    st("parar", lambda: m.t_stop({}))
    s.out("FIN2", {"ok": True})


if __name__ == "__main__":
    if os.environ.get("CHEM_TEST") == "1":
        threading.Thread(target=run2, daemon=True).start()
    m.serve()
