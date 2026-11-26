# Multikatalog – API dla narzędzi (MCP)

Tylko odczyt danych + generowanie pliku eksportu. Zwraca JSON (poza `/api/eksport`, który zwraca plik).
Typowy scenariusz: agent dostaje mail z prośbą o cennik → szuka towaru → generuje plik → odpowiada z załącznikiem.

## Autoryzacja

Każde wywołanie `/api/*` wymaga nagłówka:

```
Authorization: Bearer <API_TOKEN>
```

- `API_TOKEN` ustawiasz w `.env` na serwerze (generowanie: `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
- Pusty `API_TOKEN` = API wyłączone (każde wywołanie → 401).
- Token daje dostęp tylko do `/api/*`, nie do panelu. Poza siecią lokalną używaj wyłącznie HTTPS.

Brak / zły token:

```json
HTTP 401
{"error": "Brak lub nieprawidłowy token API."}
```

## Wspólne

**Parametr `widocznosc`** (opcjonalny, domyślnie `aktywne`): `aktywne` | `ukryte` | `wszystkie`.

**Wiersz towaru** (`rows[]` w `/api/szukaj` i `/api/towary`) – ten sam format, który przyjmuje `/api/eksport`:

```json
{
  "skrot": "SG03808RAL7016",
  "img": "https://.../1.jpg",
  "values": {
    "Źródło": "idosell",
    "Skrot": "SG03808RAL7016",
    "Nazwa": "Altana Ogrodowa 500×300×251 cm …",
    "IAI_Cena detaliczna": "8200",
    "IAI_Cena hurtowa": "…",
    "IAI_Cena minimalna": "…",
    "KRIS_CenaPLN": "…",
    "KRIS_CenaEUR": "…",
    "Param: Kolor": "…"
  }
}
```

**`columns`** – lista wszystkich dostępnych kolumn (kolumny produktu `IAI_*`, kolumny `KRIS_*` i parametry `Param: <nazwa>` ze słownika). Najważniejsze dla cennika:

| Kolumna | Znaczenie |
|---|---|
| `Skrot`, `Nazwa` | kod i nazwa towaru |
| `IAI_Cena detaliczna` / `IAI_Cena hurtowa` / `IAI_Cena minimalna` | ceny ze sklepu IdoSell (lub z produktu własnego) |
| `KRIS_CenaPLN` / `KRIS_CenaEUR` | ceny z KRIS (dopasowanie po pierwszych 7 znakach skrótu) |
| `IAI_Jednostka`, `IAI_EAN`, `IAI_Producent` | dane dodatkowe |

Wszystkie wartości w `values` są tekstami (puste = `""`).

**Błąd IdoSell** nie przerywa odpowiedzi: dostajesz `200` z wypełnionym polem `error` i wynikami z lokalnej bazy. Zawsze sprawdzaj `error`.

---

## `GET /api/szukaj` – szukanie towaru po kodzie lub nazwie

Główne narzędzie do obsługi maili.

| Parametr | Wymagany | Opis |
|---|---|---|
| `q` | tak | kod lub fragment nazwy, min. 3 znaki |
| `widocznosc` | nie | patrz wyżej |

Jak szuka:

| Źródło | Kod | Nazwa |
|---|---|---|
| IdoSell | **dokładnie cały kod** (bez wielkości liter) | ciągły fragment nazwy |
| produkty własne | początek skrótu | fragment nazwy |
| KRIS (`kris[]`) | początek kodu | fragment nazwy |

Odpowiedź:

```json
{
  "error": null,
  "obciete": false,
  "columns": ["Źródło", "Skrot", "Nazwa", "…"],
  "rows": [ /* wiersze towaru, gotowe do /api/eksport */ ],
  "kris": [
    {"kod": "SG03108", "kod7": "SG03108", "nazwa": "DONICA / EXCLUSIVE POLYRATTAN PLANTER 108X39X43",
     "jednostka": "szt.", "cena_pln": "277.15", "cena_eur": ""}
  ]
}
```

- `rows` – towary ze sklepu i własne; to je przekazujesz do eksportu.
- `kris` – rekordy z KRIS z cenami, także towary, których nie ma w sklepie. **Nie są** wierszami eksportu.
- `obciete: true` – fraza za szeroka (IdoSell: max 100 wyników na kryterium, baza: max 100) → zawęź frazę.

Błędy: `400` – fraza krótsza niż 3 znaki lub zła `widocznosc`.

Przykład:

```bash
curl -H "Authorization: Bearer $API_TOKEN" "https://<host>/api/szukaj?q=SG03808RAL7016&widocznosc=wszystkie"
```

**Wskazówki dla agenta:**
1. Szukaj najpierw pełnym kodem z maila.
2. `rows` puste, a `kris` coś zwraca → szukaj ponownie nazwą (lub jej fragmentem) z `kris`; jeśli dalej brak, towaru nie ma w sklepie – cenę można podać z `kris`.
3. Nazwa w IdoSell to ciągły fragment: `donica 100x50` znajdzie, `donica szara 100x50` może nie znaleźć – używaj krótszych fraz.

---

## `GET /api/kategorie` – lista kategorii

Kategorie zaznaczone w panelu w „Wybór kategorii”. Potrzebne tylko do `/api/towary`.

`?wszystkie=true` – wszystkie kategorie sklepu, które mają produkty (`nazwa` = pełna ścieżka, `liczba` = liczba towarów), i wszystkie kategorie własne. `/api/towary` przyjmuje każdą z nich, nie tylko zaznaczone. Błąd IdoSell → `502` z `{"error": "…"}`.

```json
{
  "idosell": [{"id": 1214555738, "nazwa": "Altany"}],
  "wlasne":  [{"id": 3, "nazwa": "Ogród / Donice"}]
}
```

---

## `GET /api/towary` – wszystkie towary z kategorii

Te same dane co tabela na stronie `/eksport`.

| Parametr | Wymagany | Opis |
|---|---|---|
| `kat` | jeden z dwóch | id kategorii IdoSell (z `idosell[]`) – dołącza też produkty własne przypięte do tej kategorii |
| `wkat` | jeden z dwóch | id kategorii własnej (z `wlasne[]`) |
| `widocznosc` | nie | patrz wyżej |

```json
{
  "tytul": "Kategoria IdoSell 1214555738",
  "error": null,
  "liczba": 2,
  "obciete": false,
  "columns": ["…"],
  "rows": [ /* wiersze towaru */ ]
}
```

- `liczba` – ile towarów jest w kategorii; `rows` zawiera max 5000 (`obciete: true`, gdy więcej).
- Wynik IdoSell jest cache'owany 10 minut.

Błędy: `400` – brak `kat`/`wkat` lub zła `widocznosc`.

---

## `POST /api/eksport` – generowanie pliku

Ta sama funkcja co przycisk „Generuj” na stronie `/eksport`.

Body (JSON):

| Pole | Wymagane | Opis |
|---|---|---|
| `columns` | tak | kolumny do pliku, nazwy z `columns` (nieznane są pomijane) |
| `rows` | tak | wiersze z `/api/szukaj` lub `/api/towary`, max 5000; wartości można przed eksportem zmienić |
| `fmt` | nie | `xlsx` (domyślnie) \| `csv` \| `xml` |
| `thumbnails` | nie | `true` = miniatury zdjęć w XLSX (wolniej), domyślnie `false` |

```json
{
  "columns": ["Skrot", "Nazwa", "IAI_Cena detaliczna", "KRIS_CenaPLN"],
  "rows": [ /* z /api/szukaj */ ],
  "fmt": "xlsx"
}
```

Odpowiedź: plik binarny, nazwa w nagłówku `Content-Disposition` (np. `Towary_20261124_1536.xlsx`).
Jeśli w `columns` są parametry (`Param: …`), do których wybrane towary mają pliki, dostajesz **ZIP** (arkusz + katalog `Pliki/`) – sprawdź rozszerzenie z nagłówka. Same kolumny cenowe dają zawsze pojedynczy plik.

| Typ | `Content-Type` |
|---|---|
| xlsx | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| csv | `text/csv; charset=utf-8` (z BOM, otwiera się poprawnie w Excelu) |
| xml | `application/xml` |
| zip | `application/zip` |

Błędy (`400`, JSON `{"error": "…"}`): nieznany format, brak kolumn, brak wierszy, ponad 5000 wierszy.

```bash
curl -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
     -d @body.json -OJ "https://<host>/api/eksport"
```

---

## Przykład narzędzi MCP (Python, FastMCP)

```python
import os, re, httpx
from mcp.server.fastmcp import FastMCP

URL, TOKEN = os.environ["MULTIKATALOG_URL"], os.environ["MULTIKATALOG_TOKEN"]
api = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120)
mcp = FastMCP("multikatalog")


@mcp.tool()
def szukaj_towaru(fraza: str, widocznosc: str = "aktywne") -> dict:
    """Szuka towaru po kodzie (cały kod) lub fragmencie nazwy. Zwraca rows (do eksportu) i kris (ceny KRIS)."""
    r = api.get("/api/szukaj", params={"q": fraza, "widocznosc": widocznosc})
    r.raise_for_status()
    return r.json()


@mcp.tool()
def eksportuj_cennik(rows: list[dict], columns: list[str], fmt: str = "xlsx", katalog: str = ".") -> str:
    """Generuje plik z podanych wierszy (z szukaj_towaru). Zwraca ścieżkę zapisanego pliku."""
    r = api.post("/api/eksport", json={"rows": rows, "columns": columns, "fmt": fmt})
    r.raise_for_status()
    name = re.search(r'filename="?([^";]+)', r.headers["content-disposition"]).group(1)
    path = os.path.join(katalog, name)
    with open(path, "wb") as f:
        f.write(r.content)
    return path


if __name__ == "__main__":
    mcp.run()
```
