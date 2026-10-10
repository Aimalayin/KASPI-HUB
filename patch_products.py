"""Запускать в папке kaspi-hub:  python3 patch_products.py
Для товаров, которых нет в ACTIVE.xlsx, показывает среднюю цену продажи (~) и пометку «нет в файле». Копии: *.bak4"""
import re, ast, shutil, sys
NEW = r'''def products(p):
    a, b = rng(p)
    S, agg = load_stock(), {}
    for name, code, qty, total, ret in sold(a, b):
        s = match(code, name, S)
        k = s["sku"] if s else (code or name)
        r = agg.setdefault(k, {"name": s["name"] if s else name, "sku": s["sku"] if s else (code or ""), "price": s and s["price"],
                               "units": s and s["units"], "est": False, "sold": 0, "revenue": 0, "returns": 0})
        r["sold"] += qty
        r["revenue"] += total
        r["returns"] += ret
    for r in agg.values():  # товара нет в прайс-листе (закончился/снят): берём среднюю цену продажи из заказов
        if r["price"] is None and r["sold"]:
            r["price"] = round(r["revenue"] / r["sold"])
            r["est"] = True
    rows = list(agg.values())
    rows += [{"name": s["name"], "sku": s["sku"], "price": s["price"], "units": s["units"], "est": False, "sold": 0, "revenue": 0, "returns": 0}
             for s in S if s["sku"] not in agg]
    rows.sort(key=lambda r: -r["revenue"])
    return {"rows": rows, "sold": sum(r["sold"] for r in rows), "revenue": sum(r["revenue"] for r in rows), "pending": pending(a, b)}
'''
s = open("server.py", encoding="utf-8").read(); shutil.copy("server.py", "server.py.bak4")
m = re.search(r"def products\(.*?(?=\n\n\n)", s, re.S)
if not m: sys.exit("Не нашёл функцию products в server.py")
s = s[:m.start()] + NEW.rstrip("\n") + s[m.end():]
try: ast.parse(s)
except SyntaxError as e: sys.exit(f"Ошибка синтаксиса, строка {e.lineno}: {e.msg}. Файл не изменён.")
h = open("index.html", encoding="utf-8").read(); shutil.copy("index.html", "index.html.bak4")
a1, a2 = '${r.price!=null?f(r.price)+" ₸":"—"}', '${r.units??"—"}'
if a1 not in h or a2 not in h: sys.exit("Не нашёл ячейки цены/остатка в index.html. Файл не изменён.")
h = h.replace(a1, '${r.price!=null?(r.est?`<span class="mut" title="Средняя цена продажи за период: товара нет в ACTIVE.xlsx">~</span>`:"")+f(r.price)+" ₸":"—"}', 1)
h = h.replace(a2, '${r.units??`<span class="mut" title="Товара нет в ACTIVE.xlsx: возможно, закончился или снят с продажи">нет в файле</span>`}', 1)
open("server.py", "w", encoding="utf-8").write(s); open("index.html", "w", encoding="utf-8").write(h)
print("Готово. Перезапустите сервер.")
