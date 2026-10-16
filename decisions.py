"""Validate typed answers and apply a transparent inspection review policy."""

from __future__ import annotations

import math


def _number(value: object, name: str, lower: float = 0, upper: float = 1) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric.")
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} is outside its allowed range.")
    return float(value)


def _distribution(answer: dict, keys: set[str]) -> dict[str, float]:
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != keys:
        raise ValueError("Probability keys must exactly match the declared outcomes.")
    result = {key: _number(value, "probability") for key, value in probabilities.items()}
    if not math.isclose(sum(result.values()), 1.0, abs_tol=1e-4):
        raise ValueError("Probabilities must sum to approximately one.")
    return result


def validate_answers(request: dict, response: dict) -> dict:
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("Response must contain an answers object.")
    answers = response["answers"]
    if set(answers) != set(request["questions"]):
        raise ValueError("Response answer names differ from request questions.")
    for name, question in request["questions"].items():
        answer = answers[name]
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise ValueError(f"Wrong answer type for {name}.")
        kind = question["type"]
        if kind == "noul":
            _number(answer.get("noul"), name)
            continue
        _number(answer.get("confidence"), f"{name}.confidence")
        if kind == "choice":
            probabilities = _distribution(answer, set(question["criteria"]))
            selected = answer.get("choice")
            if selected not in probabilities:
                raise ValueError(f"Undeclared choice for {name}.")
            if probabilities[selected] + 1e-6 < max(probabilities.values()):
                raise ValueError(f"Selected choice is not a most probable outcome for {name}.")
        elif kind == "score":
            levels = question["criteria"]
            probabilities = _distribution(answer, {str(i) for i in range(len(levels))})
            score = _number(answer.get("score"), name, upper=len(levels) - 1)
            expected = sum(int(key) * value for key, value in probabilities.items())
            if not math.isclose(score, expected, abs_tol=1e-3):
                raise ValueError(f"Score is not the expected rubric level for {name}.")
            if answer.get("legend") != {str(i): value for i, value in enumerate(levels)}:
                raise ValueError(f"Score legend differs from request rubric for {name}.")
        else:
            raise ValueError(f"Unsupported question type: {kind}")
    return answers


def route_inspection(
    answers: dict, minimum_confidence: float = 0.8, minimum_choice_probability: float = 0.8
) -> dict:
    """Return a recommendation only; this function performs no external action."""
    _number(minimum_confidence, "minimum confidence")
    _number(minimum_choice_probability, "minimum choice probability")
    condition, severity, review = (
        answers["condition"], answers["severity"], answers["needs_review"]["noul"]
    )
    reasons = []
    if condition["confidence"] < minimum_confidence:
        reasons.append("condition confidence below threshold")
    selected_probability = condition["probabilities"][condition["choice"]]
    if selected_probability < minimum_choice_probability:
        reasons.append("selected condition probability below threshold")
    if severity["confidence"] < minimum_confidence:
        reasons.append("severity confidence below threshold")
    if condition["choice"] != "intact":
        reasons.append("condition is damaged or unclear")
    if severity["score"] >= 1:
        reasons.append("damage reaches the minor-damage level")
    if review >= 0.2:
        reasons.append("human inspection probability reaches 0.2 review threshold")
    return {
        "route": "human_review" if reasons else "accept_recommendation",
        "reasons": reasons or ["all inspection thresholds passed"],
        "minimum_confidence": minimum_confidence,
        "minimum_choice_probability": minimum_choice_probability,
        "condition": condition,
        "severity": severity,
        "needs_review_probability": review,
    }
