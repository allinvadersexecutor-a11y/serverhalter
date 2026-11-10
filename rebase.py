import re
import sys
import zipfile

OLD = "minecraft:knowledge_book"
RECIPES = re.compile(r',recipes=\[[^\]]*\]')


def rebase(src, dst, item="minecraft:disc_fragment_5"):
    stats = {"archivos": 0, "cambiados": 0, "base": 0, "recipes": 0}
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in zi.infolist():
            data = zi.read(info.filename)
            stats["archivos"] += 1
            if not info.is_dir() and info.filename.endswith((".mcfunction", ".json")):
                t = data.decode("utf-8")
                n = t.count(OLD)
                t2 = t.replace(OLD, item)
                t2, r = RECIPES.subn("", t2)
                if n or r:
                    stats["cambiados"] += 1
                    stats["base"] += n
                    stats["recipes"] += r
                    data = t2.encode("utf-8")
            zo.writestr(info, data)
    return stats


if __name__ == "__main__":
    print(rebase(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "minecraft:disc_fragment_5"))
