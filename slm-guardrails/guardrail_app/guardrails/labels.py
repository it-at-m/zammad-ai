"""Label definitions and task settings for guardrail classifiers."""

SAFETY_LABELS = ["safe", "unsafe"]

REFUSAL_LABELS = ["refusal", "compliance"]

TOXICITY_LABELS = [
    "violence_and_weapons",
    "non_violent_crime",
    "sexual_content",
    "hate_and_discrimination",
    "self_harm_and_suicide",
    "pii_exposure",
    "misinformation",
    "copyright_violation",
    "child_safety",
    "political_manipulation",
    "unethical_conduct",
    "regulated_advice",
    "privacy_violation",
    "other",
    "benign",
]

JAILBREAK_LABELS = [
    "prompt_injection",
    "jailbreak_attempt",
    "policy_evasion",
    "instruction_override",
    "system_prompt_exfiltration",
    "data_exfiltration",
    "roleplay_bypass",
    "hypothetical_bypass",
    "obfuscated_attack",
    "multi_step_attack",
    "social_engineering",
    "benign",
]

PROMPT_TOXICITY_TASK = {
    "labels": TOXICITY_LABELS,
    "multi_label": True,
    "cls_threshold": 0.4,
}

RESPONSE_TOXICITY_TASK = {
    "labels": TOXICITY_LABELS,
    "multi_label": True,
    "cls_threshold": 0.4,
}

JAILBREAK_TASK = {
    "labels": JAILBREAK_LABELS,
    "multi_label": True,
    "cls_threshold": 0.4,
}
