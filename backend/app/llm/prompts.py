"""System prompt and output schema for per-holding scenario analysis. Bump PROMPT_VERSION on any change."""

PROMPT_VERSION = "2026-10-17.1"
SCENARIOS = ["rate_cut", "rate_rise", "weaker_rupee", "higher_crude", "sector_regulation", "demand_slowdown"]
DIRECTIONS = ["upward pressure", "downward pressure", "mixed", "unclear"]
SCENARIO_LABELS = {"rate_cut": "a rate cut", "rate_rise": "a rate rise", "weaker_rupee": "a weaker rupee",
                   "higher_crude": "higher crude oil prices", "sector_regulation": "tighter sector regulation",
                   "demand_slowdown": "a demand slowdown"}

SYSTEM_PROMPT = """You write scenario and context analysis about one listed company for a private, single-user \
portfolio-analytics tool. The reader already owns the holding; your job is to explain context, risks and \
sensitivities, not to advise.

Use only the JSON input you are given. Every input value has an "id". For every statement you write, cite the \
ids of the input values that support it in "citations". If something is not in the input, do not state it; \
list what is missing in "data_gaps" (cite the id of the N/A value when there is one).

Numbers: copy any number exactly as it appears in the input, or use none. Do not compute, round, convert or \
estimate numbers, and do not mention years, quarters or amounts that are not in the input.

Never recommend or imply an action: no buy, sell, hold, accumulate, add, reduce or exit language, no target or \
fair price, no upside or downside figures, and no predictions of price moves (never say a price "will rise" or \
"will fall"). Describe the likely direction of pressure on the business under each scenario, and why, as a \
conditional ("if this happens, the pressure tends to be ...").

Valuation context may compare the company only with the "within my portfolio" medians provided, never with an \
industry or the market. Scenario directions use: upward pressure, downward pressure, mixed, unclear. Use "unclear" \
when the input does not support a direction.

Keep each statement to one or two plain sentences."""

STATEMENT = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "citations"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "valuation_context": {"type": "array", "items": STATEMENT},
        "business_quality": {"type": "array", "items": STATEMENT},
        "key_risks": {"type": "array", "items": STATEMENT},
        "macro_sensitivity": {"type": "array", "items": STATEMENT},
        "scenarios": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "scenario": {"type": "string", "enum": SCENARIOS},
                "direction": {"type": "string", "enum": DIRECTIONS},
                "because": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["scenario", "direction", "because", "citations"],
            "additionalProperties": False,
        }},
        "what_would_change_this_view": {"type": "array", "items": STATEMENT},
        "data_gaps": {"type": "array", "items": STATEMENT},
    },
    "required": ["valuation_context", "business_quality", "key_risks", "macro_sensitivity", "scenarios",
                 "what_would_change_this_view", "data_gaps"],
    "additionalProperties": False,
}
STATEMENT_SECTIONS = ["valuation_context", "business_quality", "key_risks", "macro_sensitivity",
                      "what_would_change_this_view", "data_gaps"]

CATEGORY_SYSTEM = """Suggest a category for each news headline about a listed company. Use only the headline text. \
Choose exactly one category from the allowed list; use "other" when none fits."""


def render_scenario(item: dict) -> str:
    return (f"If {SCENARIO_LABELS[item['scenario']]} happens, the likely direction of pressure on this holding is "
            f"{item['direction']}, because {item['because'].rstrip('.')}.")
