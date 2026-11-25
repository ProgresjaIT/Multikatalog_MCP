# Multikatalog MCP

Serwer MCP (stdio) do API Multikatalogu: szukanie towarów, kategorie i eksport cennika do Nextclouda.

## Narzędzia

| Narzędzie | Co robi |
|---|---|
| `search_products(query, visibility)` | szuka po pełnym kodzie lub fragmencie nazwy (min. 3 znaki); zwraca `rows` (do eksportu) i `kris` (ceny KRIS) |
| `list_categories()` | kategorie IdoSell (`kat`) i własne (`wkat`) |
| `get_category_products(kat \| wkat, visibility)` | wszystkie towary z kategorii (max 5000) |
| `export_price_list(rows, columns, fmt, thumbnails)` | generuje xlsx/csv/xml, zapisuje w Nextcloudzie i zwraca ścieżkę, np. `Cenniki/Towary_20261125_1111.xlsx` |

`visibility`: `aktywne` (domyślnie) | `ukryte` | `wszystkie`.

## Uruchomienie

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt     # Windows: venv\Scripts\pip
cp .env.example .env                         # uzupełnij API_TOKEN i NEXTCLOUD_PASSWORD
venv/bin/python app.py
```

Wymaga Pythona 3.10+. Wdrożenie przez `mcp_loader`: szablon `python-uv`, `run_cmd: ["python", "app.py"]`, zmienne jak w `.env.example`.

## Uwagi

- Dwa eksporty w tej samej minucie mają tę samą nazwę – drugi nadpisze pierwszy w Nextcloudzie.
- Opis API Multikatalogu: `API.md`.
