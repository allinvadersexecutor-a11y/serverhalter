import json
import math
import os
import sys
import threading
import time

os.environ.setdefault("CHEM_BOOT", "0")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chem_mcp as m


def out(tag, data):
    print("CHEMTEST", tag, json.dumps(data, ensure_ascii=False, default=str)[:3500], flush=True)


def step(tag, fn):
    try:
        r = fn()
        out(tag, r)
        return r
    except Exception as e:
        out(tag, {"error": "%s: %s" % (type(e).__name__, str(e)[:900])})
        return None


def mem():
    r = {}
    for k, p in (("max", "/sys/fs/cgroup/memory.max"), ("cur", "/sys/fs/cgroup/memory.current"), ("events", "/sys/fs/cgroup/memory.events")):
        try:
            r[k] = open(p).read().replace("\n", " ").strip()
        except OSError:
            r[k] = None
    return r


def tail(path, n=1500):
    try:
        return open(path, "rb").read().decode("utf-8", "replace")[-n:]
    except OSError:
        return None


def rc(cmd):
    return m.rcon([cmd])[0]["out"]


def bot(op, **a):
    return m.bot_rpc(op, a)


def inv():
    items = bot("inventory")["resultado"]
    return [[i["name"], i["count"], i.get("display")] for i in items]


def held():
    h = bot("state")["resultado"]["held"]
    return None if not h else [h["name"], h["count"]]


def run():
    step("mem_inicio", mem)
    wz = os.environ.get("CHEM_WORLD_ZIP")
    step("world_zip", lambda: {"existe": bool(wz and os.path.exists(wz))})
    jar = step("descarga_jar", lambda: m.fetch_jar(os.environ.get("CHEM_MC_VERSION", "1.21.6")))
    if not jar:
        return
    step("setup", lambda: m.t_setup({"server_jar": jar, "world_zip": wz if wz and os.path.exists(wz) else None, "properties": {"view-distance": 2, "simulation-distance": 2}}))
    step("start", lambda: m.t_start({"timeout": 400}))
    step("mem_tras_start", mem)
    if not m.running():
        out("servidor_muerto", {"stdout": tail(os.path.join(m.ROOT, "stdout.txt"))})
        return
    step("status", lambda: m.t_status({}))
    step("datapacks", lambda: rc("datapack list"))
    step("reload", lambda: m.t_reload({"timeout": 120}))
    step("bot_connect", lambda: m.t_bot_connect({}))
    if not m.bot_alive():
        out("bot_muerto", {"log": tail(os.path.join(m.ROOT, "bot.log"))})
        return
    step("mem_con_bot", mem)
    step("survival", lambda: rc("gamemode survival ChemBot"))
    step("give_h2", lambda: rc("execute as ChemBot run function chem:give/c/h2 {n:2}"))
    step("give_o2", lambda: rc("execute as ChemBot run function chem:give/c/o2 {n:1}"))
    step("inventario_1", inv)
    step("trigger_999", lambda: bot("chat", text="/trigger chem_react set 999"))
    step("give_reactor", lambda: rc("execute as ChemBot run function chem:give_est/reactor"))
    st = step("estado", lambda: bot("state")["resultado"])
    step("mano_reactor", lambda: bot("hotbar", name="ochre_froglight")["resultado"]["name"])
    if st:
        p = st["position"]
        x, y, z = math.floor(p["x"]) + 1, math.floor(p["y"]) - 1, math.floor(p["z"])
        step("colocar_reactor", lambda: bot("place", x=x, y=y, z=z))
    step("entidades", lambda: bot("entities", max=6)["resultado"])
    step("mano_h2", lambda: bot("hotbar", match='"h2"')["resultado"]["name"])
    step("clic_estacion", lambda: bot("use_entity", type="interaction", wait=20))
    step("inventario_2", inv)
    step("mano_h2_otra_vez", lambda: bot("hotbar", match='"h2"')["resultado"]["name"])
    cuentas = []
    for i in range(10):
        try:
            bot("use_item", wait=8)
            cuentas.append(held())
        except Exception as e:
            cuentas.append(str(e)[:120])
    out("clic_aire_x10", cuentas)
    step("mensajes", lambda: bot("messages", since=0)["resultado"]["messages"][-25:])
    step("problemas_log", lambda: m.bad_lines(m.log_from(0), 40))
    step("mem_final", mem)
    out("FIN", {"segundos": round(time.time() - T0)})


T0 = time.time()

if __name__ == "__main__":
    threading.Thread(target=run, daemon=True).start()
    m.serve()
