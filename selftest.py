import glob
import json
import math
import os
import sys
import threading
import time
import zipfile

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
    last = None
    for _ in range(4):
        try:
            return m.rcon([cmd])[0]["out"]
        except Exception as e:
            last = e
            time.sleep(3)
    raise last


def bot(op, **a):
    return m.bot_rpc(op, a)


def inv():
    items = bot("inventory")["resultado"]
    return [[i["name"], i["count"], i.get("display")] for i in items]


def held():
    h = bot("state")["resultado"]["held"]
    return None if not h else [h["name"], h["count"]]


def find_world():
    best = None
    for zp in sorted(glob.glob("/app/zips/*.zip")):
        try:
            names = zipfile.ZipFile(zp).namelist()
        except Exception:
            continue
        lv = sorted((n for n in names if n.endswith("level.dat")), key=len)
        if lv and best is None:
            best = (zp, lv[0][:-len("level.dat")], names)
    return best


def inspect_world():
    zips = {}
    for zp in sorted(glob.glob("/app/zips/*.zip")):
        try:
            names = zipfile.ZipFile(zp).namelist()
            zips[os.path.basename(zp)] = {"entradas": len(names), "primeras": names[:8], "level_dat": [n for n in names if n.endswith("level.dat")][:3], "datapacks": sorted({n[: n.index("datapacks/") + 10] + n[n.index("datapacks/") + 10 :].split("/")[0] for n in names if "datapacks/" in n})[:12]}
        except Exception as e:
            zips[os.path.basename(zp)] = str(e)
    return zips


def extract_world(best):
    zp, prefix, _ = best
    world = os.path.join(m.ROOT, "world")
    n = 0
    with zipfile.ZipFile(zp) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            dest = os.path.join(world, info.filename[len(prefix):])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(z.read(info))
            n += 1
    return {"zip": os.path.basename(zp), "prefijo": prefix, "archivos": n, "datapacks": sorted(os.listdir(os.path.join(world, "datapacks"))) if os.path.isdir(os.path.join(world, "datapacks")) else []}


def run():
    step("mem_inicio", mem)
    step("zips", inspect_world)
    best = find_world()
    jar = step("descarga_jar", lambda: m.fetch_jar(os.environ.get("CHEM_MC_VERSION", "1.21.6")))
    if not jar:
        return
    step("setup", lambda: m.t_setup({"server_jar": jar, "properties": {"view-distance": 2, "simulation-distance": 2}}))
    if best:
        step("extraer_mundo", lambda: extract_world(best))
    step("start", lambda: m.t_start({"timeout": 400}))
    step("mem_tras_start", mem)
    if not m.running():
        out("servidor_muerto", {"stdout": tail(os.path.join(m.ROOT, "stdout.txt"))})
        return
    step("status", lambda: m.t_status({}))
    step("datapacks", lambda: rc("datapack list"))
    step("reload", lambda: rc("reload"))
    time.sleep(20)
    step("datapacks_tras_reload", lambda: rc("datapack list"))
    step("bot_connect", lambda: m.t_bot_connect({}))
    if not m.bot_alive():
        out("bot_muerto", {"log": tail(os.path.join(m.ROOT, "bot.log"))})
        return
    step("asentar", lambda: bot("wait", ticks=300))
    step("mem_con_bot", mem)
    step("survival", lambda: rc("gamemode survival ChemBot"))
    step("give_h2", lambda: rc("execute as ChemBot run function chem:give/c/h2 {n:5}"))
    step("give_o2", lambda: rc("execute as ChemBot run function chem:give/c/o2 {n:3}"))
    step("give_reactor", lambda: rc("execute as ChemBot run function chem:give_est/reactor"))
    step("esperar_give", lambda: bot("wait", ticks=100))
    step("inventario_1", inv)
    st = step("estado", lambda: bot("state")["resultado"])
    step("mano_reactor", lambda: bot("hotbar", name="ochre_froglight")["resultado"]["name"])
    if st:
        p = st["position"]
        x, y, z = math.floor(p["x"]) + 1, math.floor(p["y"]) - 1, math.floor(p["z"])
        step("colocar_reactor", lambda: bot("place", x=x, y=y, z=z))
    step("esperar_colocacion", lambda: bot("wait", ticks=300))
    step("inventario_tras_colocar", inv)
    step("entidades", lambda: [e for e in bot("entities", max=40)["resultado"] if e["distance"] < 12])
    step("mano_h2", lambda: bot("hotbar", match='"H2"')["resultado"])
    step("clic_estacion", lambda: bot("use_entity", type="interaction", wait=100))
    step("inventario_tras_estacion", inv)
    step("mano_h2_otra_vez", lambda: bot("hotbar", match='"H2"')["resultado"]["name"])
    step("antes_clic_aire", held)
    cuentas = []
    for i in range(6):
        try:
            bot("use_item", wait=100)
            cuentas.append(held())
        except Exception as e:
            cuentas.append(str(e)[:120])
    out("clic_aire_x6", cuentas)
    step("inventario_final", inv)
    step("trigger_999_final", lambda: bot("chat", text="/trigger chem_react set 999", wait=100))
    step("mensajes", lambda: bot("messages", since=0)["resultado"]["messages"][-30:])
    step("problemas_log", lambda: m.bad_lines(m.log_from(0), 40))
    step("mem_final", mem)
    out("FIN", {"segundos": round(time.time() - T0)})


T0 = time.time()

if __name__ == "__main__":
    threading.Thread(target=run, daemon=True).start()
    m.serve()
