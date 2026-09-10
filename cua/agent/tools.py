"""The action tool surface the discovery agent is given.

One tool call per turn (``tool_choice: any``). Every tool names its target the
way a human would -- by accessibility role + visible name -- never by a CSS
selector or coordinate. The recorder turns each accepted call into a step with a
full multi-strategy :class:`~cua.targeting.selector.Target`.
"""
from __future__ import annotations

_ROLE_DESC = ("ARIA role of the control, e.g. 'button', 'link', 'textbox', "
              "'combobox', 'heading', 'cell'. Copy it from the OBSERVATION.")
_NAME_DESC = ("The control's visible / accessible name exactly as shown in the "
              "OBSERVATION (the text in quotes).")

TOOLS = [
    {
        "name": "navigate",
        "description": "Load a URL. Only URLs on the target application are allowed.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click a control identified by its role and name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": _ROLE_DESC},
                "name": {"type": "string", "description": _NAME_DESC},
                "nth": {"type": "integer",
                        "description": "0-based index if several controls share the name.",
                        "default": 0},
                "why": {"type": "string", "description": "One short phrase: the purpose of this click."},
            },
            "required": ["role", "name", "why"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into a textbox / field identified by role and name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": _ROLE_DESC},
                "name": {"type": "string", "description": _NAME_DESC},
                "text": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["role", "name", "text", "why"],
        },
    },
    {
        "name": "select_option",
        "description": "Choose an option in a dropdown / combobox by its visible label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": _ROLE_DESC},
                "name": {"type": "string", "description": _NAME_DESC},
                "value": {"type": "string", "description": "The option label to select."},
                "why": {"type": "string"},
            },
            "required": ["role", "name", "value", "why"],
        },
    },
    {
        "name": "press_key",
        "description": "Press a single keyboard key (e.g. 'Enter', 'Escape', 'Tab').",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "why": {"type": "string"}},
            "required": ["key", "why"],
        },
    },
    {
        "name": "read_value",
        "description": ("Extract a value from the screen to return to the caller as a "
                        "named output. Use for the data the goal asks you to read."),
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string",
                          "description": "snake_case name for this output, e.g. savings_balance."},
                "role": {"type": "string", "description": _ROLE_DESC},
                "name": {"type": "string", "description": _NAME_DESC},
                "why": {"type": "string"},
            },
            "required": ["label", "role", "name", "why"],
        },
    },
    {
        "name": "finish",
        "description": "The goal is fully accomplished. Provide the collected outputs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "outputs": {"type": "object",
                            "description": "Map of output label -> value read during the run."},
                "summary": {"type": "string"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "escalate",
        "description": ("You cannot safely proceed -- stuck, a dead end, an unexpected "
                        "state you don't know how to handle, or a risky action you "
                        "should not take alone. Hand off to a human operator."),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}
