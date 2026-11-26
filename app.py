"""Serwer MCP (stdio) dla API Multikatalogu (opis: API.md)."""
import functools
import os
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

load_dotenv(Path(__file__).with_name(".env"))
URL = os.environ["MULTIKATALOG_URL"]
TOKEN = os.environ["API_TOKEN"]
NC_DIR = os.environ.get("NEXTCLOUD_DIR", "Cenniki").strip("/")

nc = httpx.Client(
    base_url=f"{os.environ['NEXTCLOUD_URL'].rstrip('/')}/remote.php/dav/files/{quote(os.environ['NEXTCLOUD_USER'])}/",
    auth=(os.environ["NEXTCLOUD_USER"], os.environ["NEXTCLOUD_PASSWORD"]),
    timeout=120,
)

# zimne wyszukiwanie w IdoSell trwa do ~90 s, a równoległe zapytania backend kolejkuje
api = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=300)
mcp = MCPServer(
    "multikatalog",
    instructions=(
        "Katalog towarów (IdoSell, produkty własne, KRIS). Szukaj najpierw pełnym kodem; "
        "gdy rows puste a kris coś zwraca, szukaj krótkim fragmentem nazwy z kris. "
        "Wyszukuj pojedynczo, nigdy równolegle, frazą 1–2 słów z nazwy. Po timeoucie ponów raz sam, bez pytania. "
        "Zawsze sprawdzaj pole error. Do eksportu podawaj kody (skrot) z wyników wyszukiwania. "
        "Cały cennik kategorii eksportuj przez export_category, nie przez get_category_products."
    ),
)


_rows: dict[str, dict] = {}  # pełne wiersze z API po skrócie; agent dostaje tylko odchudzone
MAX_VALUE = 200  # dłuższe wartości (opisy, listy zdjęć) to ~95% wagi wiersza, agentowi niepotrzebne


def _slim(data: dict) -> dict:
    # shortcut: cache rośnie przez całą sesję MCP; przy długo żyjącym serwerze dodać limit/TTL
    out = []
    for row in data.get("rows", []):
        # część towarów IdoSell nie ma kodu – dostają klucz zastępczy, żeby się nie nadpisywały
        key = row["skrot"] or f"bez-kodu-{row['values'].get('IAI_ProductId') or len(_rows)}"
        _rows[key] = row
        out.append({"skrot": key, "values": {k: v for k, v in row["values"].items() if v and len(v) <= MAX_VALUE}})
    return {**data, "rows": out}


def _check(r: httpx.Response) -> httpx.Response:
    # API zwraca {"error": "..."} przy 400/401 – przekaż treść agentowi zamiast gołego statusu
    if r.is_error:
        try:
            msg = r.json().get("error")
        except ValueError:
            msg = r.text[:500]
        raise RuntimeError(f"HTTP {r.status_code}: {msg}")
    return r


def show_errors(fn):
    # błąd ze szczegółami wraca jako wynik toola, zamiast gołego "Error executing tool"
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e
    return wrapper


@mcp.tool()
@show_errors
def search_products(query: str, visibility: str = "aktywne") -> dict:
    """Szuka towaru po kodzie (IdoSell: dokładnie cały kod) lub ciągłym fragmencie nazwy (min. 3 znaki).
    visibility: aktywne | ukryte | wszystkie.
    Zwraca rows (skrot + niepuste krótkie wartości; długie opisy pominięte), columns,
    kris (ceny z KRIS, nie są wierszami eksportu), obciete, error."""
    return _slim(_check(api.get("/api/szukaj", params={"q": query, "widocznosc": visibility})).json())


@mcp.tool()
@show_errors
def list_categories() -> dict:
    """Zwraca kategorie: idosell[] (id do parametru kat) i wlasne[] (id do parametru wkat)."""
    return _check(api.get("/api/kategorie")).json()


@mcp.tool()
@show_errors
def get_category_products(kat: int | None = None, wkat: int | None = None, visibility: str = "aktywne") -> dict:
    """Wszystkie towary z kategorii. Podaj kat (id kategorii IdoSell) albo wkat (id kategorii własnej).
    Zwraca tytul, liczba, rows (max 5000, odchudzone), columns, obciete, error. Uwaga: wynik może być duży –
    do eksportu całej kategorii użyj export_category."""
    return _slim(_category(kat, wkat, visibility))


def _category(kat: int | None, wkat: int | None, visibility: str) -> dict:
    if (kat is None) == (wkat is None):
        raise ValueError("Podaj dokładnie jeden z parametrów: kat albo wkat.")
    params = {"widocznosc": visibility, **({"kat": kat} if kat is not None else {"wkat": wkat})}
    return _check(api.get("/api/towary", params=params)).json()


@mcp.tool()
@show_errors
def export_price_list(codes: list[str], columns: list[str], fmt: str = "xlsx", thumbnails: bool = False,
                      changes: dict[str, dict[str, str]] | None = None) -> str:
    """Generuje plik (xlsx | csv | xml) z towarów znalezionych wcześniej przez search_products / get_category_products.
    codes: kody (skrot) z rows, w kolejności wierszy pliku.
    columns: nazwy kolumn z pola columns, np. ["Skrot", "Nazwa", "IAI_Cena detaliczna", "KRIS_CenaPLN"].
    changes: opcjonalne zmiany wartości przed eksportem, np. {"SG03808": {"IAI_Cena detaliczna": "7900"}}.
    Kolumny "Param: …" z plikami dają ZIP.
    Plik trafia do Nextclouda; zwraca jego ścieżkę w Nextcloudzie (np. "Cenniki/Towary_20261125_1048.xlsx")."""
    if missing := [c for c in codes if c not in _rows]:
        raise ValueError(f"Nieznane kody (najpierw wyszukaj je search_products): {', '.join(missing)}")
    changes = changes or {}
    rows = [{**_rows[c], "values": {**_rows[c]["values"], **changes.get(c, {})}} for c in codes]
    return _export(rows, columns, fmt, thumbnails)


@mcp.tool()
@show_errors
def export_category(columns: list[str], kat: int | None = None, wkat: int | None = None,
                    visibility: str = "aktywne", fmt: str = "xlsx", thumbnails: bool = False) -> dict:
    """Cały cennik kategorii prosto do pliku w Nextcloudzie – wiersze nie przechodzą przez agenta.
    Podaj kat (IdoSell) albo wkat (własna) z list_categories. Cały katalog: wołaj kolejno dla każdej kategorii.
    Zwraca path, liczba (towarów w kategorii), obciete (true = w pliku tylko pierwsze 5000), error."""
    data = _category(kat, wkat, visibility)
    if not data["rows"]:
        return {"path": None, "liczba": 0, "obciete": False, "error": data.get("error") or "Kategoria jest pusta."}
    return {"path": _export(data["rows"], columns, fmt, thumbnails), "liczba": data["liczba"],
            "obciete": data["obciete"], "error": data.get("error")}


def _export(rows: list[dict], columns: list[str], fmt: str, thumbnails: bool) -> str:
    r = _check(api.post("/api/eksport", json={"rows": rows, "columns": columns, "fmt": fmt, "thumbnails": thumbnails}))
    m = re.search(r'filename="?([^";]+)', r.headers.get("content-disposition", ""))
    name = Path(m.group(1) if m else f"eksport.{fmt}").name  # .name: nie ufamy ścieżce z nagłówka
    folder = nc.request("MKCOL", quote(NC_DIR) + "/")
    if folder.status_code not in (201, 405):  # 405 = folder już istnieje
        raise RuntimeError(f"Nextcloud: nie można utworzyć folderu {NC_DIR} (HTTP {folder.status_code})")
    stem, ext = Path(name).stem, Path(name).suffix
    for i in range(1, 100):  # nazwa z API ma dokładność do minuty – kolejne eksporty nie mogą się nadpisać
        nc_path = f"{NC_DIR}/{stem if i == 1 else f'{stem}_{i}'}{ext}"
        up = nc.put(quote(nc_path), content=r.content, headers={"If-None-Match": "*"})
        if up.status_code != 412:  # 412 = plik już istnieje
            break
    if up.status_code not in (201, 204):
        raise RuntimeError(f"Nextcloud: zapis {nc_path} nie powiódł się (HTTP {up.status_code})")
    return nc_path


if __name__ == "__main__":
    mcp.run()
