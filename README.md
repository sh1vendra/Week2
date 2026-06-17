# FitFindr

A secondhand shopping agent that takes a natural language query, finds matching thrift listings, and generates outfit suggestions and a shareable caption — all in one planning loop.

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the project root:
```
GROQ_API_KEY=your_key_here
```

Run the app:
```bash
python app.py
```

Then open `http://localhost:7860` in your browser.

---

## Project Structure

```
Week2/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example/empty wardrobe
├── utils/
│   └── data_loader.py         # load_listings(), get_example_wardrobe(), etc.
├── tools.py                   # The three agent tools
├── agent.py                   # Planning loop (run_agent)
├── app.py                     # Gradio UI (handle_query)
├── tests/
│   └── test_tools.py          # 5 unit tests for the tools
├── planning.md                # Design spec and architecture
└── requirements.txt
```

---

## Tool Inventory

These match the exact signatures in `tools.py`.

### `search_listings(description, size, max_price)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | `str` | Keywords describing what the user wants (e.g. `"vintage graphic tee"`) |
| `size` | `str \| None` | Size filter; case-insensitive `in` match so `"M"` matches `"S/M"`. `None` skips filtering. |
| `max_price` | `float \| None` | Inclusive price ceiling. `None` skips filtering. |

**Returns:** `list[dict]` — matching listing dicts sorted by relevance score (keyword overlap) descending. Empty list `[]` if nothing matches. Never raises.

Each dict contains: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand` (str or None), `platform`.

---

### `suggest_outfit(new_item, wardrobe)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_item` | `dict` | A listing dict for the item being considered. Uses `title`, `category`, `style_tags`, `colors`. |
| `wardrobe` | `dict` | Wardrobe dict with an `items` key (list of wardrobe item dicts). May be empty. |

**Returns:** `str` — a non-empty outfit suggestion or general styling advice. Never returns empty string, never raises.

---

### `create_fit_card(outfit, new_item)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `outfit` | `str` | Outfit suggestion from `suggest_outfit()`. Empty/whitespace triggers early return. |
| `new_item` | `dict` | Listing dict for the thrifted item. Uses `title`, `price`, `platform`. |

**Returns:** `str` — a 2–4 sentence Instagram/TikTok caption. If `outfit` is empty or whitespace, returns exactly: `"Could not generate fit card: no outfit suggestion provided."`. Never raises.

---

## How the Planning Loop Works

`run_agent(query, wardrobe)` in `agent.py` runs a fixed linear sequence of five steps. It does not dynamically reorder tools — conditional logic only decides whether to continue or exit early.

```
query
  |
  v
[LLM parse] --> {description, size, max_price}
  |
  v
[search_listings] --> results[]
  |
  +-- empty? --> session["error"] set --> return early
  |
  v
select results[0] as selected_item
  |
  v
[suggest_outfit] --> outfit_suggestion
  |
  v
[create_fit_card] --> fit_card
  |
  v
return session
```

**Parse step:** The query is sent to the Groq LLM (`llama-3.3-70b-versatile`) with `response_format: json_object`. The model extracts `description` (str), `size` (str or null), and `max_price` (float or null) from natural language. This handles phrasings like "under thirty bucks" or "in a medium" without regex fragility.

**Search step:** `search_listings()` is called with the parsed parameters. Scoring counts how many words from the description appear across five fields of each listing (title, description, category, style_tags, colors). Zero-score listings are dropped. Results are sorted by score.

**Selection:** The top result (`results[0]`) is used. No tie-breaking needed — the sort is stable.

**Outfit + fit card:** Both LLM calls happen unconditionally if a selected item exists.

---

## State Management

All state lives in a single session dict initialized by `_new_session()`. Tools are pure functions — they receive inputs as arguments and return values; they do not read or write the session dict directly. `run_agent()` is the only place that reads and writes session keys.

| Key | Written by | Read by |
|-----|-----------|---------|
| `query` | `_new_session()` | LLM parse prompt |
| `parsed` | LLM parse step | `search_listings()` call |
| `search_results` | `search_listings()` call | selection step |
| `selected_item` | selection step | `suggest_outfit()`, `create_fit_card()`, `handle_query()` |
| `wardrobe` | `_new_session()` | `suggest_outfit()` |
| `outfit_suggestion` | `suggest_outfit()` call | `create_fit_card()` call |
| `fit_card` | `create_fit_card()` call | `handle_query()` → Gradio panel 3 |
| `error` | any failure point | `handle_query()` → Gradio panel 1 |

No state persists between separate calls to `run_agent()`. Each call gets a fresh session dict.

---

## Error Handling

### Per-tool failure modes with concrete examples

**`search_listings`**

- *Failure:* No listings match the description + filters. Example: query `"designer ballgown size XXS under $5"` — the price ceiling eliminates everything, leaving `[]`.
- *Response:* Returns `[]`. `run_agent()` detects the empty list, constructs a message like `"No listings found for "designer ballgown" matching size XXS and under $5.0. Try different keywords, a higher price, or a different size."`, sets `session["error"]`, and returns the session immediately. `handle_query()` shows this in panel 1; panels 2 and 3 are empty strings.
- *Code path:* `tools.py:56–58` (exception catch returns `[]`); `agent.py` early-return block.

**`suggest_outfit`**

- *Failure:* Wardrobe is empty (`{"items": []}`). Example: new user has no wardrobe items.
- *Response:* The tool detects `not items` and switches to a general styling prompt (`"My wardrobe is currently empty. Give me general styling advice..."`). The LLM still responds with useful guidance — no error is shown to the user.
- *Failure 2:* LLM call throws (network error, bad API key).
- *Response:* Caught by `except Exception as e`, returns `"Could not generate outfit suggestion: <error>"`.

**`create_fit_card`**

- *Failure:* `outfit` is empty or whitespace. Example: `suggest_outfit()` returned `""` due to a bug.
- *Response:* Returns exactly `"Could not generate fit card: no outfit suggestion provided."` before any LLM call is made. This exact string is asserted in `tests/test_tools.py::test_create_fit_card_empty_outfit`.
- *Failure 2:* LLM call throws.
- *Response:* Caught by `except Exception as e`, returns `"Could not generate fit card: <error>"`.

---

## Spec Reflection

**One way planning.md helped during implementation:**

Writing out the state management table (which key is written by which step, consumed by which step) before writing any code made it immediately obvious that tools should be pure functions — they take arguments and return values, not read from a shared dict. That decision is what made the tools independently testable with `pytest` without needing to construct a full session object in every test.

**One divergence from the spec, and why:**

The original plan described the LLM parse step as optional — falling back to regex if the LLM call failed. During implementation it became clear that wrapping the entire planning loop in a single try/except was cleaner and more reliable: if the parse step throws, `session["error"]` is set by the outer catch and returned immediately. A separate regex fallback would have added complexity for a failure mode (Groq being unreachable) that surfaces its own clear error message anyway.

---

## AI Usage

**Instance 1 — Implementing `search_listings` scoring logic**

I gave Claude the Tool 1 spec from `planning.md` (exact parameters, return type, the requirement to score by word overlap across five fields, drop zero-score results, sort descending) along with the `data_loader.py` source. Claude produced the scoring implementation using a set of lowercased description words and a joined string of all five listing fields. I verified it against three manual queries (broad keyword, nonsense input, tight price filter) and then locked it in with the `pytest` tests before moving on.

**Instance 2 — Implementing `run_agent` planning loop**

I gave Claude the Architecture ASCII diagram from `planning.md`, the State Management table, and the `_new_session()` source. I asked specifically for LLM-based query parsing using Groq's `response_format: json_object` mode, an early return on empty search results with a filter-aware error message, and a single outer try/except to catch any unhandled exceptions. Claude generated the loop; I then ran `python agent.py` to exercise both the happy path (graphic tee query returning results) and the no-results path (ballgown query) to confirm `session["error"]` was set correctly in each case.
