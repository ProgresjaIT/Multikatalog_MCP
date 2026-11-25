"""Serwer MCP (stdio) dla API Multikatalogu (opis: API.md)."""
import os
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv(Path(__file__).with_name(".env"))
URL = os.environ["MULTIKATALOG_URL"]
TOKEN = os.environ["API_TOKEN"]
NC_DIR = os.environ.get("NEXTCLOUD_DIR", "Cenniki").strip("/")

nc = httpx.Client(
    base_url=f"{os.environ['NEXTCLOUD_URL'].rstrip('/')}/remote.php/dav/files/{quote(os.environ['NEXTCLOUD_USER'])}/",
    auth=(os.environ["NEXTCLOUD_USER"], os.environ["NEXTCLOUD_PASSWORD"]),
    timeout=120,
)

api = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120)
mcp = MCPServer(
    "multikatalog",
    instructions=(
        "Katalog towarów (IdoSell, produkty własne, KRIS). Szukaj najpierw pełnym kodem; "
        "gdy rows puste a kris coś zwraca, szukaj krótkim fragmentem nazwy z kris. "
        "Zawsze sprawdzaj pole error. Do eksportu przekazuj rows bez zmian struktury."
    ),
)


def _check(r: httpx.Response) -> httpx.Response:
    # API zwraca {"error": "..."} przy 400/401 – przekaż treść agentowi zamiast gołego statusu
    if r.is_error:
        try:
            msg = r.json().get("error")
        except ValueError:
            msg = r.text[:500]
        raise RuntimeError(f"HTTP {r.status_code}: {msg}")
    return r


@mcp.tool()
def search_products(query: str, visibility: str = "aktywne") -> dict:
    """Szuka towaru po kodzie (IdoSell: dokładnie cały kod) lub ciągłym fragmencie nazwy (min. 3 znaki).
    visibility: aktywne | ukryte | wszystkie.
    Zwraca rows (wiersze do eksportu), columns, kris (ceny z KRIS, nie są wierszami eksportu), obciete, error."""
    return _check(api.get("/api/szukaj", params={"q": query, "widocznosc": visibility})).json()


@mcp.tool()
def list_categories() -> dict:
    """Zwraca kategorie: idosell[] (id do parametru kat) i wlasne[] (id do parametru wkat)."""
    return _check(api.get("/api/kategorie")).json()


@mcp.tool()
def get_category_products(kat: int | None = None, wkat: int | None = None, visibility: str = "aktywne") -> dict:
    """Wszystkie towary z kategorii. Podaj kat (id kategorii IdoSell) albo wkat (id kategorii własnej).
    Zwraca tytul, liczba, rows (max 5000), columns, obciete, error. Uwaga: wynik może być duży."""
    if (kat is None) == (wkat is None):
        raise ValueError("Podaj dokładnie jeden z parametrów: kat albo wkat.")
    params = {"widocznosc": visibility, **({"kat": kat} if kat is not None else {"wkat": wkat})}
    return _check(api.get("/api/towary", params=params)).json()


@mcp.tool()
def export_price_list(rows: list[dict], columns: list[str], fmt: str = "xlsx", thumbnails: bool = False) -> str:
    """Generuje plik (xlsx | csv | xml) z wierszy z search_products / get_category_products.
    columns: nazwy kolumn z pola columns, np. ["Skrot", "Nazwa", "IAI_Cena detaliczna", "KRIS_CenaPLN"].
    Kolumny "Param: …" z plikami dają ZIP.
    Plik trafia do Nextclouda; zwraca jego ścieżkę w Nextcloudzie (np. "Cenniki/Towary_20261125_1048.xlsx")."""
    r = _check(api.post("/api/eksport", json={"rows": rows, "columns": columns, "fmt": fmt, "thumbnails": thumbnails}))
    m = re.search(r'filename="?([^";]+)', r.headers.get("content-disposition", ""))
    name = Path(m.group(1) if m else f"eksport.{fmt}").name  # .name: nie ufamy ścieżce z nagłówka
    nc_path = f"{NC_DIR}/{name}"
    folder = nc.request("MKCOL", quote(NC_DIR) + "/")
    if folder.status_code not in (201, 405):  # 405 = folder już istnieje
        raise RuntimeError(f"Nextcloud: nie można utworzyć folderu {NC_DIR} (HTTP {folder.status_code})")
    up = nc.put(quote(nc_path), content=r.content)
    if up.status_code not in (201, 204):
        raise RuntimeError(f"Nextcloud: zapis {nc_path} nie powiódł się (HTTP {up.status_code})")
    return nc_path


if __name__ == "__main__":
    mcp.run()
