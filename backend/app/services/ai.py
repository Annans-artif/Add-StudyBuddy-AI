import json
import os
import re
import urllib.error
import urllib.request
import ipaddress
from urllib.parse import urlsplit

BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
MODEL = os.getenv("LM_STUDIO_MODEL", "deepseek-r1-distill-llama-8b")
API_KEY = os.getenv("LM_STUDIO_API_KEY", "")

def local_lm_studio_url() -> str:
    """Return the configured LM Studio URL only when it targets this computer."""
    try:
        parsed = urlsplit(BASE_URL)
        host = parsed.hostname or ""
        is_loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        if (
            parsed.scheme not in ("http", "https")
            or not is_loopback
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        return BASE_URL
    except ValueError as exc:
        raise AIUnavailable(
            "For privacy, LM_STUDIO_BASE_URL must point to a local address such as "
            "http://127.0.0.1:1234/v1."
        ) from exc

class AIUnavailable(Exception):
    pass

def _json_from_text(text: str):
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise ValueError("The model did not return valid JSON. Try again or use a shorter note.")
        return json.loads(match.group(0))

def generate(kind: str, title: str, subject: str, content: str, focus_topics: list[str] | None = None, question: str | None = None):
    formats = {
        "summary": 'Write at most 100 words. Return JSON: {"summary":"..."}',
        "quiz": 'Make 4 questions. Each has exactly 4 short options and one brief explanation. Return JSON: {"questions":[{"question":"...","options":["...","...","...","..."],"answer":0,"explanation":"..."}]}. answer is the zero-based correct option index.',
        "flashcards": 'Make 6 concise cards. Return JSON: {"cards":[{"front":"short question or term","back":"brief answer"}]}.'
    }
    if kind == "ask":
        formats[kind] = 'Answer the question from the notes only. Include up to 2 short exact quotations copied from the notes as evidence. If the notes do not contain the answer, say so. Return JSON: {"answer":"...","citations":["exact quote"]}.'
    if focus_topics:
        formats["quiz"] = f'Make 3 short questions only about these topics the student missed: {", ".join(focus_topics[:5])}. Each has exactly 4 short options and a brief explanation. Return JSON: {{"questions":[{{"question":"...","options":["...","...","...","..."],"answer":0,"explanation":"...","topic":"..."}}]}}. answer is the zero-based correct option index.'
    elif kind == "quiz":
        formats["quiz"] = 'Make 4 questions. Each has exactly 4 short options, one brief explanation, and a topic label (1-3 words). Return JSON: {"questions":[{"question":"...","options":["...","...","...","..."],"answer":0,"explanation":"...","topic":"..."}]}. answer is the zero-based correct option index.'
    if kind == "ask" and question:
        prompt = f"Answer this student question using only the notes. Question: {question}\n\nNOTES:\n{content}\n\n{formats[kind]}"
    else:
        prompt = f"Create {kind} using only these notes. Be accurate. Answer immediately; do not show reasoning. Output only valid JSON, with no markdown. Title: {title}. Subject: {subject}.\n\nNOTES:\n{content}\n\n{formats[kind]}"
    token_limits = {"summary": 800, "quiz": 1500 if focus_topics else 1800, "flashcards": 1200, "ask": 1000}
    body = json.dumps({"model": MODEL, "messages": [
        {"role": "system", "content": "You are a concise study tutor. Return only the requested JSON. Keep all wording short."},
        {"role": "user", "content": prompt}
    ], "temperature": 0.2, "max_tokens": token_limits[kind]}).encode()
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    base_url = local_lm_studio_url()
    req = urllib.request.Request(f"{base_url}/chat/completions", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            payload = json.loads(response.read().decode())
        raw = payload["choices"][0]["message"]["content"]
        result = _json_from_text(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            raise AIUnavailable(f"LM Studio could not use model '{MODEL}'. Check the configured model ID and make sure it is loaded.") from exc
        raise AIUnavailable(f"LM Studio returned HTTP {exc.code}. Check the local server and model status.") from exc
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise AIUnavailable("Can't reach LM Studio. Open LM Studio, load the configured model, and start the local server on port 1234.") from exc
    if kind == "summary":
        if not isinstance(result.get("summary"), str) or not result["summary"].strip():
            raise ValueError("The model returned an empty summary. Please try again.")
    elif kind == "quiz":
        questions = result.get("questions")
        if not isinstance(questions, list) or not 1 <= len(questions) <= 20:
            raise ValueError("The model returned an invalid quiz. Please try again.")
        for q in questions:
            if not isinstance(q.get("question"), str) or not isinstance(q.get("options"), list) or len(q["options"]) != 4 or not all(isinstance(x, str) for x in q["options"]) or type(q.get("answer")) is not int or q["answer"] not in range(4):
                raise ValueError("The model returned an invalid quiz question. Please try again.")
            q.setdefault("explanation", "")
            q.setdefault("topic", "General")
    else:
        if kind == "flashcards":
            cards = result.get("cards")
            if not isinstance(cards, list) or not 1 <= len(cards) <= 40 or any(not isinstance(c.get("front"), str) or not isinstance(c.get("back"), str) for c in cards):
                raise ValueError("The model returned invalid flashcards. Please try again.")
        elif kind == "ask":
            if not isinstance(result.get("answer"), str) or not result["answer"].strip() or not isinstance(result.get("citations", []), list):
                raise ValueError("The model returned an invalid answer. Please try again.")
            result["citations"] = [quote for quote in result.get("citations", []) if isinstance(quote, str) and quote.strip() and quote.casefold() in content.casefold()][:2]
            if not result["citations"] and "do not contain" not in result["answer"].casefold():
                result["answer"] = "I couldn't find a supporting passage in these notes. Try asking about a topic stated more directly in your notes."
    return result
