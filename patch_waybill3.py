"""Запускать в папке kaspi-hub:  python3 patch_waybill3.py   (заменяет waybill_one на версию с поиском ссылки в нескольких местах)"""
import re, ast, shutil, sys
NEW = '''def waybill_one(oid):
    code = (q("select code from orders where id=?", (oid,)) or [[None]])[0][0]

    def find(x):  # ищем именно ссылку (http или путь), а не номер накладной
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str) and v.startswith(("http", "/")) and ("waybill" in str(k).lower() or v.lower().split("?")[0].endswith(".pdf")):
                    return v
            for v in x.values():
                r = find(v)
                if r:
                    return r
        elif isinstance(x, list):
            for v in x:
                r = find(v)
                if r:
                    return r
        return None

    def kdel(got):  # что Kaspi отдал про доставку: для сообщения об ошибке
        for d in got:
            dd = d.get("data")
            dd = dd[0] if isinstance(dd, list) and dd else dd
            a = (dd or {}).get("attributes") or {} if isinstance(dd, dict) else {}
            if a.get("kaspiDelivery"):
                return a["kaspiDelivery"]
        return None

    def link():
        got = []
        for path, prm in ((f"/orders/{oid}", {}), ("/orders", {"page[number]": 0, "page[size]": 1, "filter[orders][code]": code})):
            if path == "/orders" and not code:
                continue
            try:
                d = api(path, prm)
            except PermissionError:
                raise
            except Exception:
                continue
            u = find(d)
            if u:
                return u, got
            got.append(d)
        return None, got
    url, got = link()
    if not url:  # то же, что кнопка «Сформировать» в Упаковке: после сборки Kaspi создаёт накладную
        body = {"data": {"type": "orders", "id": oid, "attributes": {"status": "ASSEMBLE", "numberOfSpace": str(max(1, int(os.environ.get("PACK_SPACES", "1"))))}}}
        r = requests.post(BASE + "/orders", headers=H, json=body, timeout=60)
        if r.status_code not in (200, 201, 204):
            raise ValueError(f"Kaspi не принял сборку (код {r.status_code}): {r.text[:200]}")
        with lock:  # заказ собран: помним, чтобы он не пропал из списка, пока накладная не скачана
            db.execute("create table if not exists packed(oid text primary key)")
            db.execute("insert or ignore into packed values(?)", (oid,))
            db.commit()
        try:
            url = find(r.json())
        except ValueError:
            pass
        for _ in range(6):
            if url:
                break
            time.sleep(3)
            url, got = link()
    if not url:
        if not _seen.get("wb"):
            _seen["wb"] = True
            log("Диагностика", "Нет ссылки на накладную. Ответ Kaspi: " + json.dumps(got, ensure_ascii=False)[:1800])
        raise ValueError("Kaspi не отдал ссылку на накладную. Про доставку Kaspi отдал: " + json.dumps(kdel(got), ensure_ascii=False)[:300])
    if url.startswith("/"):
        url = "https://kaspi.kz" + url
    host = urlparse(url).hostname or ""
    if not (host == "kaspi.kz" or host.endswith(".kaspi.kz")):
        raise ValueError("ссылка ведёт не на Kaspi: " + url[:60])
    r = requests.get(url, headers={"X-Auth-Token": TOKEN, "User-Agent": "Mozilla/5.0"}, timeout=60)
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise ValueError(f"накладная не скачалась (код {r.status_code})")
    return r.content
'''
src = open("server.py", encoding="utf-8").read()
shutil.copy("server.py", "server.py.bak2")
src = src.replace('{os.environ.get("PORT", 8000)}', "{os.environ.get('PORT', 8000)}")
m = re.search(r"def waybill_one\(.*?(?=\n\n\ndef )", src, re.S)
if not m: sys.exit("Не нашёл waybill_one в server.py")
out = src[:m.start()] + NEW.rstrip("\n") + src[m.end():]
try: ast.parse(out)
except SyntaxError as e: sys.exit(f"Правка не применена, строка {e.lineno}: {e.msg}")
a = 'orders, _ = pack_sorted()\n        job["total"] = len(orders)'
if a in out and "PACK_LIMIT" not in out:  # для первой пробы: PACK_LIMIT=2 python3 server.py соберёт только 2 заказа
    out = out.replace(a, 'orders, _ = pack_sorted()\n        lim = int(os.environ.get("PACK_LIMIT", "0"))\n        if lim:\n            orders = orders[:lim]\n        job["total"] = len(orders)')
    ast.parse(out)
open("server.py", "w", encoding="utf-8").write(out)
try:
    h = open("index.html", encoding="utf-8").read()
    b = '$("#go").onclick=async()=>{$("#go").disabled=true;'
    if b in h:
        shutil.copy("index.html", "index.html.bak2")
        h = h.replace(b, '$("#go").onclick=async()=>{if(!confirm("Сформировать накладные для "+d.orders.length+" заказов? Заказы будут отмечены в Kaspi как упакованные (по 1 месту), это нельзя отменить."))return;$("#go").disabled=true;')
        open("index.html", "w", encoding="utf-8").write(h)
except OSError:
    pass

s2 = open("server.py", encoding="utf-8").read()
s2 = s2.replace('and assembled=0"', 'and (assembled=0 or id in (select oid from packed))"', 1) if "select oid from packed" not in s2 else s2
if "create table if not exists packed" not in s2.split("def waybill_one")[0]:
    mm = re.search(r"\nif __name__ == .__main__.:", s2)
    if mm: s2 = s2[:mm.start() + 1] + 'db.execute("create table if not exists packed(oid text primary key)")\ndb.commit()\n\n\n' + s2[mm.start() + 1:]
a = '        job.update(state="done", file=fn)'
if a in s2 and "delete from packed" not in s2:
    s2 = s2.replace(a, '        with lock:\n            db.executemany("delete from packed where oid=?", [(i,) for i in got])\n            db.commit()\n' + a, 1)
try: ast.parse(s2)
except SyntaxError as e: sys.exit(f"Ошибка синтаксиса, строка {e.lineno}: {e.msg}. Восстановите server.py из server.py.bak2")
open("server.py", "w", encoding="utf-8").write(s2)
print("Готово. Перезапустите сервер.")
