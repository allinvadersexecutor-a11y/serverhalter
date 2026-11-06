import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.environ.get("CHEM_MC_DIR", os.path.abspath("mcserver"))
RCON_PORT = int(os.environ.get("CHEM_RCON_PORT", "25575"))
RCON_PASS = os.environ.get("CHEM_RCON_PASS", "chemtest")
JAVA = os.environ.get("CHEM_JAVA", "java")
HEAP = os.environ.get("CHEM_HEAP", "2G")

proc = None
botproc = None
BOOT_ERROR = None
BOT_PORT = int(os.environ.get("CHEM_BOT_PORT", "9001"))
BOT_JS = os.environ.get("CHEM_BOT_JS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.js"))
TOKEN = os.environ.get("MCP_TOKEN", "")


def load_pack(path):
    files = {}
    if os.path.isdir(path):
        for base, _, names in os.walk(path):
            for n in names:
                full = os.path.join(base, n)
                files[os.path.relpath(full, path).replace(os.sep, "/")] = open(full, "rb").read()
    else:
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if not i.is_dir():
                    files[i.filename] = z.read(i)
    return files


def namespaces(files):
    out = set()
    for k in files:
        p = k.split("/")
        if len(p) > 2 and p[0] == "data":
            out.add(p[1])
    return out


def lint(path, limit=40):
    files = load_pack(path)
    issues = []
    if "pack.mcmeta" not in files:
        issues.append("falta pack.mcmeta en la raíz")
        return {"errors": issues, "stats": {}}
    try:
        meta = json.loads(files["pack.mcmeta"])
        fmt = meta["pack"].get("pack_format", meta["pack"].get("min_format"))
    except Exception as e:
        issues.append("pack.mcmeta inválido: %s" % e)
        fmt = None
    funcs = set()
    for k in files:
        m = re.match(r"data/([^/]+)/function/(.+)\.mcfunction$", k)
        if m:
            funcs.add("%s:%s" % (m.group(1), m.group(2)))
    ftags = {}
    json_ok = 0
    for k, v in files.items():
        if k.endswith(".json") or k.endswith(".mcmeta"):
            try:
                d = json.loads(v)
                json_ok += 1
                m = re.match(r"data/([^/]+)/tags/function/(.+)\.json$", k)
                if m:
                    ftags["%s:%s" % (m.group(1), m.group(2))] = d
            except Exception as e:
                issues.append("JSON inválido %s: %s" % (k, e))
    for tag, d in ftags.items():
        for val in d.get("values", []):
            ref = val if isinstance(val, str) else val.get("id", "")
            if ref.startswith("#"):
                if ref[1:] not in ftags:
                    issues.append("etiqueta %s referencia %s inexistente" % (tag, ref))
            elif ref not in funcs and not ref.startswith("minecraft:"):
                if not (isinstance(val, dict) and val.get("required") is False):
                    issues.append("etiqueta %s referencia función %s inexistente" % (tag, ref))
    call = re.compile(r"(?:^|\s)function\s+((?:#)?[a-z0-9_.\-]+:[a-z0-9_./\-]+)")
    objs_def = set()
    objs_use = {}
    add_re = re.compile(r"scoreboard objectives add\s+(\S+)")
    use_re = re.compile(r"scoreboard players (?:set|add|remove|get|reset|enable)\s+\S+\s+([A-Za-z0-9_.\-+]+)")
    cond_re = re.compile(r"\b(?:if|unless)\s+score\s+\S+\s+([A-Za-z0-9_.\-+]+)")
    nfunc = 0
    for k, v in files.items():
        if not k.endswith(".mcfunction"):
            continue
        nfunc += 1
        for n, line in enumerate(v.decode("utf-8", "replace").splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            for r in add_re.findall(s):
                objs_def.add(r)
            for r in use_re.findall(s) + cond_re.findall(s):
                objs_use.setdefault(r, "%s:%d" % (k, n))
            for r in call.findall(s):
                if r.startswith("#"):
                    if r[1:] not in ftags:
                        issues.append("%s:%d etiqueta %s inexistente" % (k, n, r))
                elif r not in funcs and "{" not in r and "$(" not in s:
                    issues.append("%s:%d función %s inexistente" % (k, n, r))
            if "$(" in s and not s.startswith("$"):
                issues.append("%s:%d macro sin prefijo $" % (k, n))
    for k, v in files.items():
        if k.endswith(".json") and ("/advancement/" in k):
            try:
                d = json.loads(v)
            except Exception:
                continue
            fn = (d.get("rewards") or {}).get("function")
            if fn and fn not in funcs:
                issues.append("%s recompensa función %s inexistente" % (k, fn))
    for o, where in objs_use.items():
        if o not in objs_def and not o.startswith("%") and not o.startswith("#"):
            issues.append("objetivo %s usado sin crear (primer uso %s)" % (o, where))
    stats = {
        "pack_format": fmt,
        "namespaces": sorted(namespaces(files)),
        "funciones": nfunc,
        "json_validos": json_ok,
        "recetas": sum(1 for k in files if "/recipe/" in k),
        "logros": sum(1 for k in files if "/advancement/" in k),
        "dialogos": sum(1 for k in files if "/dialog/" in k),
        "problemas": len(issues),
    }
    return {"errors": issues[:limit], "omitidos": max(0, len(issues) - limit), "stats": stats}


def diff_packs(a, b, limit=30):
    fa, fb = load_pack(a), load_pack(b)
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    changed = sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
    return {
        "solo_en_a": len(only_a),
        "solo_en_b": len(only_b),
        "distintos": len(changed),
        "ejemplos_solo_a": only_a[:limit],
        "ejemplos_solo_b": only_b[:limit],
        "ejemplos_distintos": changed[:limit],
    }


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ConnectionError("rcon cerrado")
        buf += c
    return buf


def rcon_packet(s, pid, typ, body):
    data = struct.pack("<ii", pid, typ) + body.encode("utf-8") + b"\x00\x00"
    s.sendall(struct.pack("<i", len(data)) + data)


def rcon_read(s):
    (ln,) = struct.unpack("<i", recv_exact(s, 4))
    data = recv_exact(s, ln)
    pid, typ = struct.unpack("<ii", data[:8])
    return pid, typ, data[8:-2].decode("utf-8", "replace")


def rcon(commands, host="127.0.0.1", port=None, password=None):
    port = port or RCON_PORT
    password = password or RCON_PASS
    s = socket.create_connection((host, port), timeout=10)
    try:
        rcon_packet(s, 1, 3, password)
        pid, _, _ = rcon_read(s)
        if pid == -1:
            raise PermissionError("contraseña rcon rechazada")
        out = []
        for i, c in enumerate(commands):
            rid = 100 + i
            rcon_packet(s, rid, 2, c)
            rcon_packet(s, rid + 5000, 2, "")
            text = ""
            while True:
                p, _, body = rcon_read(s)
                if p == rid + 5000:
                    break
                text += body
            out.append({"cmd": c, "out": text})
        return out
    finally:
        s.close()


def log_path():
    return os.path.join(ROOT, "logs", "latest.log")


def log_size():
    try:
        return os.path.getsize(log_path())
    except OSError:
        return 0


def log_from(offset):
    try:
        with open(log_path(), "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


BAD = re.compile(r"ERROR|WARN|Failed|Couldn't|Unknown|Invalid|Exception|Parsing error", re.I)


def bad_lines(text, limit=60):
    out = [l for l in text.splitlines() if BAD.search(l)]
    return out[:limit]


def running():
    return proc is not None and proc.poll() is None


def t_setup(a):
    jar = a["server_jar"]
    world_zip = a.get("world_zip")
    os.makedirs(ROOT, exist_ok=True)
    shutil.copy(jar, os.path.join(ROOT, "server.jar"))
    open(os.path.join(ROOT, "eula.txt"), "w").write("eula=true\n")
    props = {
        "enable-rcon": "true",
        "rcon.port": str(RCON_PORT),
        "rcon.password": RCON_PASS,
        "online-mode": "false",
        "level-name": "world",
        "gamemode": "survival",
        "difficulty": "normal",
        "spawn-protection": "0",
        "motd": "chem-test",
        "view-distance": "4",
        "simulation-distance": "4",
        "max-players": "4",
    }
    props.update({k: str(v) for k, v in a.get("properties", {}).items()})
    open(os.path.join(ROOT, "server.properties"), "w").write("".join("%s=%s\n" % kv for kv in props.items()))
    world = os.path.join(ROOT, "world")
    if world_zip:
        os.makedirs(world, exist_ok=True)
        with zipfile.ZipFile(world_zip) as z:
            z.extractall(world)
    dp = a.get("datapack")
    if dp:
        os.makedirs(os.path.join(world, "datapacks"), exist_ok=True)
        dest = os.path.join(world, "datapacks", os.path.basename(dp))
        if os.path.isdir(dp):
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(dp, dest)
        else:
            shutil.copy(dp, dest)
    return {"dir": ROOT, "datapacks": sorted(os.listdir(os.path.join(world, "datapacks"))) if os.path.isdir(os.path.join(world, "datapacks")) else []}


def t_start(a):
    global proc
    if running():
        return {"estado": "ya en marcha", "pid": proc.pid}
    if not os.path.exists(os.path.join(ROOT, "server.jar")):
        raise RuntimeError("falta server.jar: ejecuta server_setup")
    off = log_size()
    out = open(os.path.join(ROOT, "stdout.txt"), "wb")
    proc = subprocess.Popen(
        [JAVA, "-Xmx" + HEAP, "-jar", "server.jar", "nogui"],
        cwd=ROOT,
        stdout=out,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    limit = float(a.get("timeout", 180))
    t0 = time.time()
    while time.time() - t0 < limit:
        if proc.poll() is not None:
            tail = open(os.path.join(ROOT, "stdout.txt"), "rb").read().decode("utf-8", "replace")[-1500:]
            raise RuntimeError("el servidor terminó (código %s): %s" % (proc.returncode, tail))
        txt = log_from(off)
        if re.search(r"Done \(", txt):
            break
        time.sleep(1)
    else:
        return {"estado": "arrancando", "nota": "aún cargando; consulta server_status", "segundos": round(time.time() - t0, 1)}
    return {"estado": "listo", "segundos": round(time.time() - t0, 1), "problemas_al_cargar": bad_lines(log_from(off))}


def t_stop(a):
    global proc, botproc
    if bot_alive():
        botproc.terminate()
        botproc = None
    if not running():
        proc = None
        return {"estado": "no estaba en marcha"}
    try:
        rcon(["stop"])
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    proc = None
    return {"estado": "detenido"}


def t_rcon(a):
    cmds = a["commands"]
    if isinstance(cmds, str):
        cmds = [cmds]
    off = log_size()
    res = rcon([c.lstrip("/") for c in cmds])
    time.sleep(float(a.get("settle", 0.3)))
    extra = bad_lines(log_from(off))
    return {"resultados": res, "log_problemas": extra}


def t_reload(a):
    off = log_size()
    res = rcon(["reload"])
    quiet = 0
    last = log_size()
    t0 = time.time()
    while time.time() - t0 < float(a.get("timeout", 60)):
        time.sleep(0.5)
        cur = log_size()
        if cur == last:
            quiet += 1
            if quiet >= 4:
                break
        else:
            quiet = 0
            last = cur
    txt = log_from(off)
    return {"respuesta": res[0]["out"], "problemas": bad_lines(txt, 100), "lineas_log": len(txt.splitlines())}


def t_log(a):
    n = int(a.get("lines", 50))
    flt = a.get("filter")
    try:
        lines = open(log_path(), "rb").read().decode("utf-8", "replace").splitlines()
    except OSError:
        return {"lineas": []}
    if flt:
        r = re.compile(flt, re.I)
        lines = [l for l in lines if r.search(l)]
    return {"lineas": lines[-n:]}


def t_status(a):
    st = {"en_marcha": running(), "dir": ROOT, "boot_error": BOOT_ERROR, "bot": bot_alive()}
    try:
        st["listo"] = "Done (" in open(log_path(), "rb").read().decode("utf-8", "replace")
    except OSError:
        st["listo"] = False
    if running():
        try:
            st["jugadores"] = rcon(["list"])[0]["out"]
        except Exception as e:
            st["rcon"] = str(e)
    return st


def t_pack_lint(a):
    return lint(a["path"], int(a.get("limit", 40)))


def t_pack_diff(a):
    return diff_packs(a["a"], a["b"], int(a.get("limit", 30)))


def t_pack_find(a):
    files = load_pack(a["path"])
    r = re.compile(a["pattern"])
    out = []
    for k, v in files.items():
        if not k.endswith((".mcfunction", ".json")):
            continue
        for n, line in enumerate(v.decode("utf-8", "replace").splitlines(), 1):
            if r.search(line):
                out.append("%s:%d: %s" % (k, n, line.strip()[:200]))
                if len(out) >= int(a.get("limit", 40)):
                    return {"coincidencias": out}
    return {"coincidencias": out}


def t_pack_read(a):
    files = load_pack(a["path"])
    k = a["file"]
    if k not in files:
        near = [x for x in files if a["file"] in x][:15]
        raise RuntimeError("no existe %s; parecidos: %s" % (k, near))
    return {"contenido": files[k].decode("utf-8", "replace")[:int(a.get("max_chars", 6000))]}


TOOLS = {
    "pack_lint": (t_pack_lint, "Análisis estático de un datapack (zip o carpeta): JSON, funciones y etiquetas inexistentes, objetivos sin crear, macros.", {"path": "str", "limit": "int?"}),
    "pack_diff": (t_pack_diff, "Compara dos datapacks (zip o carpeta).", {"a": "str", "b": "str", "limit": "int?"}),
    "pack_find": (t_pack_find, "Busca una expresión regular en funciones y JSON de un datapack.", {"path": "str", "pattern": "str", "limit": "int?"}),
    "pack_read": (t_pack_read, "Lee un archivo de un datapack por su ruta interna.", {"path": "str", "file": "str", "max_chars": "int?"}),
    "server_setup": (t_setup, "Prepara un servidor vanilla local: copia server.jar, eula, server.properties con rcon, descomprime world_zip en world/ y copia el datapack.", {"server_jar": "str", "world_zip": "str?", "datapack": "str?", "properties": "obj?"}),
    "server_start": (t_start, "Arranca el servidor y espera a que cargue. Devuelve errores de carga del datapack.", {"timeout": "int?"}),
    "server_stop": (t_stop, "Detiene el servidor.", {}),
    "server_status": (t_status, "Estado del servidor y jugadores conectados.", {}),
    "mc_reload": (t_reload, "Ejecuta /reload y devuelve errores y avisos nuevos del registro.", {"timeout": "int?"}),
    "mc_command": (t_rcon, "Ejecuta uno o varios comandos por RCON y devuelve la salida y los errores nuevos del registro. Los comandos con @s o triggers necesitan un jugador conectado: usa execute as <jugador> run ...", {"commands": "arr", "settle": "num?"}),
    "mc_log": (t_log, "Últimas líneas del registro, con filtro opcional (regex).", {"lines": "int?", "filter": "str?"}),
}

def bot_url(path):
    return "http://127.0.0.1:%d%s" % (BOT_PORT, path)


def bot_alive():
    return botproc is not None and botproc.poll() is None


def bot_rpc(op, args=None):
    if not bot_alive():
        raise RuntimeError("el bot no está en marcha: usa bot_connect")
    req = urllib.request.Request(bot_url("/rpc"), data=json.dumps({"op": op, "args": args or {}}).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=120))
    if not r.get("ok"):
        raise RuntimeError("%s | mensajes: %s" % (r.get("error"), r.get("messages")))
    return {"resultado": r["result"], "mensajes_nuevos": r.get("messages", [])}


def t_bot_connect(a):
    global botproc
    if not bot_alive():
        os.makedirs(ROOT, exist_ok=True)
        env = dict(os.environ, BOT_PORT=str(BOT_PORT))
        botproc = subprocess.Popen(["node", BOT_JS], cwd=os.path.dirname(BOT_JS), env=env, stdout=open(os.path.join(ROOT, "bot.log"), "ab"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < 15:
            if botproc.poll() is not None:
                tail = open(os.path.join(ROOT, "bot.log"), "rb").read().decode("utf-8", "replace")[-1200:]
                raise RuntimeError("el bot terminó: %s" % tail)
            try:
                urllib.request.urlopen(bot_url("/health"), timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("el bot no abrió su puerto")
    return bot_rpc("connect", {"username": a.get("username", "ChemBot"), "version": a.get("version", "1.21.6")})


def t_bot_disconnect(a):
    global botproc
    r = bot_rpc("disconnect")
    botproc.terminate()
    botproc = None
    return r


def bot_tool(op):
    return lambda a: bot_rpc(op, a)


XYZ = {"x": "num", "y": "num", "z": "num"}
TOOLS.update({
    "bot_connect": (t_bot_connect, "Lanza el bot de Mineflayer y lo conecta como jugador al servidor local (survival, sin op).", {"username": "str?", "version": "str?"}),
    "bot_state": (bot_tool("state"), "Posición, vida, modo, objeto en la mano.", {}),
    "bot_inventory": (bot_tool("inventory"), "Inventario del bot con los componentes de cada ítem (custom_data.chem).", {}),
    "bot_chat": (bot_tool("chat"), "El bot escribe en el chat o ejecuta un comando si empieza por /. Devuelve los mensajes que el juego le envió.", {"text": "str", "wait": "int?"}),
    "bot_hotbar": (bot_tool("hotbar"), "Pone un ítem en la mano: por slot 0-8, por nombre, o por texto contenido en sus componentes (match).", {"slot": "int?", "name": "str?", "match": "str?"}),
    "bot_use_item": (bot_tool("use_item"), "Clic derecho con el ítem de la mano en el aire.", {"ticks": "int?", "sneak": "bool?", "offhand": "bool?", "wait": "int?"}),
    "bot_use_block": (bot_tool("use_block"), "Clic derecho sobre un bloque.", dict(XYZ, sneak="bool?", wait="int?")),
    "bot_use_entity": (bot_tool("use_entity"), "Clic derecho sobre una entidad (la más cercana del tipo dado, p. ej. interaction, o por id).", {"type": "str?", "id": "int?", "sneak": "bool?", "wait": "int?"}),
    "bot_attack": (bot_tool("attack"), "Clic izquierdo sobre una entidad.", {"type": "str?", "id": "int?", "wait": "int?"}),
    "bot_entities": (bot_tool("entities"), "Entidades más cercanas con id, tipo y distancia.", {"max": "int?"}),
    "bot_place": (bot_tool("place"), "Coloca el ítem de la mano sobre la cara fx,fy,fz del bloque x,y,z (por defecto la de arriba).", dict(XYZ, fx="int?", fy="int?", fz="int?", wait="int?")),
    "bot_dig": (bot_tool("dig"), "Rompe un bloque.", XYZ),
    "bot_look": (bot_tool("look"), "Mira hacia un punto.", XYZ),
    "bot_messages": (bot_tool("messages"), "Mensajes recibidos (chat, sistema, barra de acción) desde un número de secuencia.", {"since": "int?"}),
    "bot_wait": (bot_tool("wait"), "Espera ticks de juego.", {"ticks": "int"}),
    "bot_disconnect": (t_bot_disconnect, "Desconecta el bot y detiene su proceso.", {}),
})

TYPES = {"str": "string", "int": "integer", "num": "number", "arr": "array", "obj": "object", "bool": "boolean"}


def schema(spec):
    props, req = {}, []
    for k, t in spec.items():
        opt = t.endswith("?")
        t = t.rstrip("?")
        props[k] = {"type": TYPES[t]}
        if t == "arr":
            props[k]["items"] = {"type": "string"}
        if not opt:
            req.append(k)
    return {"type": "object", "properties": props, "required": req}


def tool_list():
    return [{"name": n, "description": d, "inputSchema": schema(s)} for n, (_, d, s) in TOOLS.items()]


def handle(msg):
    m = msg.get("method")
    i = msg.get("id")
    if m == "initialize":
        return {"jsonrpc": "2.0", "id": i, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "chem-mc", "version": "1.0"}}}
    if m == "ping":
        return {"jsonrpc": "2.0", "id": i, "result": {}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": i, "result": {"tools": tool_list()}}
    if m == "tools/call":
        p = msg["params"]
        name = p["name"]
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": i, "error": {"code": -32602, "message": "herramienta desconocida"}}
        try:
            res = TOOLS[name][0](p.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": i, "result": {"isError": True, "content": [{"type": "text", "text": "%s: %s" % (type(e).__name__, e)}]}}
    if i is None:
        return None
    return {"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": "método no soportado"}}


def fetch_jar(version):
    dest = os.path.join(ROOT, "dl.jar")
    if os.path.exists(dest):
        return dest
    os.makedirs(ROOT, exist_ok=True)
    man = json.load(urllib.request.urlopen("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", timeout=30))
    url = next(v["url"] for v in man["versions"] if v["id"] == version)
    meta = json.load(urllib.request.urlopen(url, timeout=30))
    urllib.request.urlretrieve(meta["downloads"]["server"]["url"], dest)
    return dest


def boot():
    global BOOT_ERROR
    try:
        jar = fetch_jar(os.environ.get("CHEM_MC_VERSION", "1.21.6"))
        wz = os.environ.get("CHEM_WORLD_ZIP")
        t_setup({"server_jar": jar, "world_zip": wz if wz and os.path.exists(wz) else None})
        t_start({"timeout": 240})
    except Exception as e:
        BOOT_ERROR = "%s: %s" % (type(e).__name__, e)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, b"ok", "text/plain")
        self.reply(405)

    def do_POST(self):
        if self.path != "/%s/mcp" % TOKEN:
            return self.reply(404)
        n = int(self.headers.get("Content-Length", "0"))
        try:
            msg = json.loads(self.rfile.read(n))
        except Exception:
            return self.reply(400)
        if isinstance(msg, list):
            out = [r for r in (handle(x) for x in msg) if r is not None]
            return self.reply(200, json.dumps(out).encode()) if out else self.reply(202)
        r = handle(msg)
        if r is None:
            return self.reply(202)
        self.reply(200, json.dumps(r, ensure_ascii=False).encode("utf-8"))


def serve():
    if not TOKEN:
        sys.exit("define MCP_TOKEN")
    if os.environ.get("CHEM_BOOT", "1") == "1":
        threading.Thread(target=boot, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), Handler).serve_forever()


def main():
    if "--http" in sys.argv:
        return serve()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        r = handle(msg)
        if r is not None:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    if running():
        proc.terminate()
    if bot_alive():
        botproc.terminate()


if __name__ == "__main__":
    main()
