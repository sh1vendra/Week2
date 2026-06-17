# FitFindr — planning.md

---

## Tools

### Tool 1: search_listings

**What it does:**
Loads all mock listings from `listings.json`, applies optional price and size filters, then scores each remaining listing by counting keyword overlaps between the user's description and the listing's title, description, category, style_tags, and colors fields. Returns listings sorted by relevance score, highest first.

**Input parameters:**
- `description` (str): Natural language keywords describing the item the user wants (e.g. `"vintage graphic tee"`). Required — used for scoring every listing.
- `size` (str | None): Size string to filter by (e.g. `"M"`, `"S/M"`, `"W30 L30"`). Matching is case-insensitive and uses `in` so `"M"` matches `"S/M"`. Pass `None` to skip size filtering.
- `max_price` (float | None): Upper price bound, inclusive (e.g. `30.0`). Pass `None` to skip price filtering.

**What it returns:**
A `list[dict]` of matching listing dicts, sorted by relevance score descending. Each dict contains:
`id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand` (str or None), `platform`.
Returns `[]` if no listings score above zero. Never raises an exception.

**What happens if it fails or returns nothing:**
Returns an empty list `[]`. The planning loop checks for this immediately after the call — if empty, it sets `session["error"]` to a descriptive message (mentioning which filters were active) and returns the session early without calling any further tools.

---

### Tool 2: suggest_outfit

**What it does:**
Calls the Groq LLM (`llama-3.3-70b-versatile`) to suggest outfit combinations for a thrifted item. If the user's wardrobe is empty, it asks the LLM for general styling advice. If the wardrobe has items, it formats them into a prompt and asks for 1–2 specific outfit combinations using named wardrobe pieces.

**Input parameters:**
- `new_item` (dict): A listing dict for the item the user is considering. Used fields: `title`, `category`, `style_tags`, `colors`.
- `wardrobe` (dict): A wardrobe dict with an `items` key containing a list of wardrobe item dicts. Each item has at minimum `name` and `category`. May be an empty `{"items": []}`.

**What it returns:**
A non-empty string with outfit suggestions or general styling advice. Never returns an empty string — if the LLM response is empty or an exception occurs, returns a descriptive fallback string.

**What happens if it fails or returns nothing:**
Any exception is caught and returns `"Could not generate outfit suggestion: <error>"`. If the LLM response content is empty, returns `"No outfit suggestion available."`. Never raises.

---

### Tool 3: create_fit_card

**What it does:**
Generates a 2–4 sentence Instagram/TikTok-style caption for the selected outfit. Uses the Groq LLM with `temperature=1.2` for varied, authentic-sounding output. The caption naturally mentions the item name, price, and platform once each.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by `suggest_outfit()`. If empty or whitespace-only, the tool short-circuits before calling the LLM.
- `new_item` (dict): The listing dict for the thrifted item. Used fields: `title`, `price`, `platform`.

**What it returns:**
A string caption (2–4 sentences) suitable for social media. If `outfit` is empty or whitespace, returns the exact string: `"Could not generate fit card: no outfit suggestion provided."`. Never raises an exception.

**What happens if it fails or returns nothing:**
Empty/whitespace `outfit` triggers an immediate early return with the fixed error string. Any LLM or network exception is caught and returns `"Could not generate fit card: <error>"`.

---

### Additional Tools (if any)

None beyond the required three.

---

## Planning Loop

The planning loop in `run_agent()` is a fixed linear sequence — it does not dynamically select tools. The order is always: parse → search → select → outfit → fit card. Conditional logic only determines whether to continue or exit early:

1. **Parse:** Always runs first. The LLM extracts `description`, `size`, and `max_price` from the raw query as JSON. If parsing fails, the exception is caught and `session["error"]` is set.
2. **Search:** Always runs after parse. If `search_results` is empty → set `session["error"]` and return immediately. No further tools run.
3. **Select:** If results exist, `results[0]` (highest relevance score) is selected as `session["selected_item"]`.
4. **Outfit:** `suggest_outfit()` always runs if a selected item exists. Result stored in `session["outfit_suggestion"]`.
5. **Fit card:** `create_fit_card()` always runs after outfit suggestion. Result stored in `session["fit_card"]`.
6. **Return:** Session dict returned with all fields populated (or `error` set and output fields as `None` if an early exit occurred).

The loop knows it is done when `create_fit_card()` returns — there is no dynamic replanning.

---

## State Management

All state for a single interaction lives in the session dict initialized by `_new_session()`. No global variables are used between runs. The keys and their data flow:

| Key | Set by | Consumed by |
|-----|--------|-------------|
| `query` | `_new_session()` | LLM parse prompt |
| `parsed` | LLM parse step | `search_listings()` call |
| `search_results` | `search_listings()` | selection step |
| `selected_item` | selection step | `suggest_outfit()`, `create_fit_card()`, `handle_query()` |
| `wardrobe` | `_new_session()` | `suggest_outfit()` |
| `outfit_suggestion` | `suggest_outfit()` | `create_fit_card()` |
| `fit_card` | `create_fit_card()` | `handle_query()` → Gradio panel |
| `error` | any failure point | `handle_query()` → panel 1 |

Each tool receives only what it needs via direct function arguments — the session dict is only read/written in `run_agent()` itself, not inside the tools.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listings score above zero (no keyword overlap, or price/size filters eliminate all results) | Returns `[]`; `run_agent()` sets `session["error"]` to a message naming the filters that were active and returns early. `handle_query()` shows the error in panel 1; panels 2 and 3 are blank. |
| `suggest_outfit` | Wardrobe is empty (`items: []`) | Switches to a general styling advice prompt instead of a specific combination prompt. The LLM still responds; the user sees useful guidance rather than an error. |
| `create_fit_card` | `outfit` is empty or whitespace | Returns the exact string `"Could not generate fit card: no outfit suggestion provided."` without calling the LLM. |

---

## Architecture

```
User query (natural language)
        |
        v
+-------------------+
|   run_agent()     |  <-- planning loop + session dict
+-------------------+
        |
        | Step 1: LLM parse (Groq JSON)
        v
  parsed: {description, size, max_price}
        |
        | Step 2: search_listings(description, size, max_price)
        v
  search_results: [listing, ...]
        |
        +-- empty? --> session["error"] = "No listings found..."
        |                      |
        |                      v
        |               return session (early exit)
        |
        | Step 3: select top result
        v
  selected_item: listing dict
        |
        | Step 4: suggest_outfit(selected_item, wardrobe)
        |           |
        |           +-- wardrobe empty? --> general styling LLM prompt
        |           +-- wardrobe has items? --> specific combo LLM prompt
        v
  outfit_suggestion: str
        |
        | Step 5: create_fit_card(outfit_suggestion, selected_item)
        |           |
        |           +-- outfit empty? --> return fixed error string
        |           +-- outfit present? --> LLM caption (temp=1.2)
        v
  fit_card: str
        |
        v
  return session
        |
        v
handle_query() --> (listing_text, outfit_suggestion, fit_card)
        |
        v
  Gradio UI (3 panels)
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **Tool used:** Claude (claude-sonnet-4-6 via Claude Code CLI)
- **Input given:** The Tool 1/2/3 spec sections from this file (parameter names, types, return value description, failure mode), plus the `data_loader.py` source so it knew about `load_listings()`.
- **Expected output:** A working `search_listings()` using `in` matching for size, inclusive price filtering, word-level scoring across five fields, sorted results.
- **Verification:** Ran three manual test calls — broad query (expected multiple results), nonsense query (expected `[]`), tight price filter (expected all results ≤ max_price). Then confirmed with `pytest tests/test_tools.py`.

For `suggest_outfit` and `create_fit_card`: same approach — gave Claude the spec and asked for implementations that handle the empty-wardrobe and empty-outfit edge cases explicitly. Verified the empty-wardrobe branch by mocking the Groq client and checking the returned string is non-empty. Verified the empty-outfit guard by passing `""` and `"   "` and asserting the exact error string.

**Milestone 4 — Planning loop and state management:**

- **Tool used:** Claude (Claude Code CLI)
- **Input given:** The Architecture diagram above, the State Management table, and the session dict keys from `_new_session()`.
- **Expected output:** A `run_agent()` that parses via LLM JSON mode, calls tools in order, stores results in the correct session keys, exits early with a descriptive error on empty search results, and wraps the whole thing in a try/except.
- **Verification:** Ran `python agent.py` which exercises both the happy path (graphic tee query) and the no-results path (ballgown under $5). Checked that `session["error"]` was `None` on the happy path and contained a readable message on the failure path.

---

## A Complete Interaction (Step by Step)

**Example user query:** `"vintage graphic tee under $30, size M"`

**Step 1 — LLM query parse:**
- Tool: Groq LLM (`llama-3.3-70b-versatile`, JSON mode)
- Input: The raw query string
- Why: Natural language queries need to be decomposed into structured parameters that `search_listings()` can use. Regex would miss variations in phrasing.
- Output: `{"description": "vintage graphic tee", "size": "M", "max_price": 30.0}`
- Stored in: `session["parsed"]`

**Step 2 — search_listings:**
- Tool: `search_listings("vintage graphic tee", size="M", max_price=30.0)`
- Input: Parsed description, size, and max_price
- Why: Finds candidate listings from the dataset that match the user's criteria before making any LLM calls.
- Output: A list of listing dicts scored by keyword overlap, e.g. the Y2K Baby Tee (price $18, size S/M — "M" matches via `in`) and a vintage band tee. Sorted by score.
- Stored in: `session["search_results"]`; `session["selected_item"] = results[0]`

**Step 3 — suggest_outfit:**
- Tool: `suggest_outfit(selected_item, wardrobe)`
- Input: The top listing dict (Y2K Baby Tee — category: tops, style_tags: ["y2k", "vintage", "graphic tee"], colors: ["white", "pink", "purple"]) and the user's wardrobe (10 items including baggy jeans, chunky sneakers, oversized hoodie)
- Why: Pairs the new find with what the user already owns to produce actionable outfit ideas.
- Output: `"Pair the Y2K Baby Tee with your wide-leg denim and platform sneakers for a full Y2K moment. Or tuck it into your high-waist cargo pants with a cropped zip-up for a more streetwear vibe."`
- Stored in: `session["outfit_suggestion"]`

**Step 4 — create_fit_card:**
- Tool: `create_fit_card(outfit_suggestion, selected_item)`
- Input: The outfit suggestion string and the listing dict (title: "Y2K Baby Tee — Butterfly Print", price: 18.0, platform: "depop")
- Why: Converts the outfit idea into shareable social caption copy the user can actually post.
- Output: `"y2k era found me 🦋 snagged this Y2K Baby Tee — Butterfly Print off depop for $18 and it goes with literally everything. wide-leg denim + platforms = the whole vibe. thrift szn is undefeated."`
- Stored in: `session["fit_card"]`

**Final output to user:**
The Gradio UI displays three panels:
- **Panel 1 (listing):** Formatted card showing title, brand, category, size, condition, price, platform, colors, style tags, and original item description.
- **Panel 2 (outfit idea):** The LLM's outfit suggestion text.
- **Panel 3 (fit card):** The Instagram/TikTok caption ready to copy-paste.
