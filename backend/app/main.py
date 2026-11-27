import json
import os
import sqlite3
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Literal

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from .database.db import connection, initialize, record_activity
from .services.ai import AIUnavailable, generate, local_lm_studio_url

initialize()
app = FastAPI(title="StudyBuddy AI API", version="1.0.0")
def is_local_frontend_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname or ""
        is_loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        return parsed.scheme == "http" and is_loopback and parsed.port is not None and parsed.path in ("", "/") and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
    except ValueError:
        return False

configured_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
if not is_local_frontend_origin(configured_origin):
    raise RuntimeError("FRONTEND_ORIGIN must be a localhost or loopback HTTP origin.")
allowed_origins = list(dict.fromkeys([configured_origin, "http://localhost:5173", "http://127.0.0.1:5173"]))
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

@app.middleware("http")
async def private_api_headers(request: Request, call_next):
    try:
        is_loopback_client = bool(request.client) and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        is_loopback_client = False
    response = await call_next(request) if is_loopback_client else JSONResponse(
        status_code=403, content={"detail": "This study app is available only on this device."}
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

def now(): return datetime.now(timezone.utc).isoformat()
def one(db, query, values=()): return db.execute(query, values).fetchone()
def many(db, query, values=()): return [dict(x) for x in db.execute(query, values).fetchall()]

class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=10, max_length=50000)
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    due_date: str
class TaskUpdate(BaseModel): completed: bool
class GenerateIn(BaseModel): note_id: int; topics: list[str] = Field(default_factory=list, max_length=5); question: str | None = Field(default=None, max_length=500)
class AttemptIn(BaseModel): score: int = Field(ge=0); total: int = Field(gt=0); answers: list[int] = Field(default_factory=list, max_length=20)
class CardProgressIn(BaseModel): seen_cards: list[int] = Field(max_length=40)
class CardReviewIn(BaseModel): rating: Literal["again", "hard", "good", "easy"]
class AskIn(BaseModel): note_id: int; question: str = Field(min_length=3, max_length=500)
class FocusIn(BaseModel): task_id: int | None = None; duration_seconds: int = Field(ge=60, le=7200)

@app.get("/api/health")
def health():
    model = os.getenv("LM_STUDIO_MODEL", "deepseek-r1-distill-llama-8b")
    try:
        import urllib.request
        base_url = local_lm_studio_url()
        with urllib.request.urlopen(base_url + "/models", timeout=2) as response:
            available = json.loads(response.read().decode()).get("data", [])
        ready = any(item.get("id") == model for item in available)
        message = "Model ready" if ready else f"Load '{model}' in LM Studio to enable AI tools."
    except Exception:
        ready = False
        message = "Start the LM Studio server at 127.0.0.1:1234 to enable AI tools."
    return {"backend": "connected", "ai": "connected" if ready else "disconnected", "model": model, "ai_message": message}

@app.get("/api/notes")
def list_notes():
    with connection() as db: return many(db, "SELECT * FROM notes ORDER BY updated_at DESC")
@app.post("/api/notes")
def create_note(data: NoteIn):
    stamp = now()
    with connection() as db:
        cur = db.execute("INSERT INTO notes(title,subject,content,created_at,updated_at) VALUES(?,?,?,?,?)", (data.title.strip(), data.subject.strip(), data.content.strip(), stamp, stamp))
        result = dict(one(db, "SELECT * FROM notes WHERE id=?", (cur.lastrowid,)))
    record_activity("note", f"Created {data.title.strip()}")
    return result
@app.put("/api/notes/{note_id}")
def update_note(note_id: int, data: NoteIn):
    with connection() as db:
        cur = db.execute("UPDATE notes SET title=?,subject=?,content=?,updated_at=? WHERE id=?", (data.title.strip(), data.subject.strip(), data.content.strip(), now(), note_id))
        if not cur.rowcount: raise HTTPException(404, "Note not found")
        return dict(one(db, "SELECT * FROM notes WHERE id=?", (note_id,)))
@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    with connection() as db:
        cur = db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        if not cur.rowcount: raise HTTPException(404, "Note not found")
    return {"deleted": True}

@app.get("/api/tasks")
def list_tasks():
    with connection() as db: return many(db, "SELECT * FROM tasks ORDER BY completed, due_date")
@app.post("/api/tasks")
def create_task(data: TaskIn):
    try: datetime.fromisoformat(data.due_date)
    except ValueError: raise HTTPException(422, "Deadline must be a valid date")
    with connection() as db:
        cur = db.execute("INSERT INTO tasks(title,due_date,created_at) VALUES(?,?,?)", (data.title.strip(), data.due_date, now()))
        result = dict(one(db, "SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)))
    record_activity("task", f"Planned {data.title.strip()}")
    return result
@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, data: TaskUpdate):
    with connection() as db:
        cur = db.execute("UPDATE tasks SET completed=? WHERE id=?", (int(data.completed), task_id))
        if not cur.rowcount: raise HTTPException(404, "Task not found")
        return dict(one(db, "SELECT * FROM tasks WHERE id=?", (task_id,)))
@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    with connection() as db:
        cur = db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        if not cur.rowcount: raise HTTPException(404, "Task not found")
    return {"deleted": True}

@app.get("/api/stats")
def stats():
    with connection() as db:
        return {"notes": one(db,"SELECT count(*) n FROM notes")["n"], "quizzes": one(db,"SELECT count(*) n FROM quiz_attempts")["n"], "cards": one(db,"SELECT count(*) n FROM flashcard_sets")["n"], "tasks": one(db,"SELECT count(*) n FROM tasks WHERE completed=0")["n"], "recent": many(db,"SELECT * FROM activity ORDER BY id DESC LIMIT 5")}
@app.get("/api/activity")
def activity():
    with connection() as db: return many(db,"SELECT * FROM activity ORDER BY id DESC LIMIT 30")

@app.post("/api/ai/{kind}")
def make_study_set(kind: str, data: GenerateIn):
    # These named actions are registered below too; dispatch explicitly because
    # the generic {kind} route is declared first in FastAPI's route table.
    if kind == "ask":
        if not data.question or len(data.question.strip()) < 3: raise HTTPException(422, "Question must contain at least 3 characters")
        return ask_notes(AskIn(note_id=data.note_id, question=data.question))
    if kind == "focus-quiz":
        return make_focus_quiz(data)
    if kind not in ("summary", "quiz", "flashcards"): raise HTTPException(404, "Unknown study material type")
    with connection() as db:
        note = one(db,"SELECT * FROM notes WHERE id=?",(data.note_id,))
        if not note: raise HTTPException(404,"Note not found")
    try: output = generate(kind, note["title"], note["subject"], note["content"], focus_topics=data.topics or None)
    except AIUnavailable as exc: raise HTTPException(503, str(exc))
    except ValueError as exc: raise HTTPException(502, str(exc))
    stamp = now()
    with connection() as db:
        if kind == "summary":
            db.execute("UPDATE notes SET summary=?,updated_at=? WHERE id=?", (output["summary"], stamp, data.note_id))
            result = {"summary": output["summary"]}
        elif kind == "quiz":
            cur = db.execute("INSERT INTO quizzes(note_id,title,questions,created_at) VALUES(?,?,?,?)", (data.note_id,note["title"],json.dumps(output["questions"]),stamp))
            result = {"id":cur.lastrowid,"note_id":data.note_id,"title":note["title"],"questions":output["questions"]}
        else:
            cur = db.execute("INSERT INTO flashcard_sets(note_id,title,cards,created_at) VALUES(?,?,?,?)", (data.note_id,note["title"],json.dumps(output["cards"]),stamp))
            result = {"id":cur.lastrowid,"note_id":data.note_id,"title":note["title"],"cards":output["cards"],"seen_cards":[]}
    record_activity(kind, f"Generated {kind} for {note['title']}")
    return result
@app.get("/api/flashcards")
def flashcard_sets():
    with connection() as db:
        rows=many(db,"SELECT * FROM flashcard_sets ORDER BY id DESC")
        for row in rows:
            row["cards"] = json.loads(row["cards"])
            row["seen_cards"] = json.loads(row["seen_cards"])
        return rows
@app.patch("/api/flashcards/{set_id}/progress")
def update_card_progress(set_id: int, data: CardProgressIn):
    with connection() as db:
        row = one(db, "SELECT cards FROM flashcard_sets WHERE id=?", (set_id,))
        if not row: raise HTTPException(404, "Flashcard set not found")
        total = len(json.loads(row["cards"]))
        if any(i < 0 or i >= total for i in data.seen_cards): raise HTTPException(422, "Card index is outside this set")
        db.execute("UPDATE flashcard_sets SET seen_cards=? WHERE id=?", (json.dumps(sorted(set(data.seen_cards))), set_id))
    return {"saved": True, "seen_cards": sorted(set(data.seen_cards))}
@app.get("/api/quizzes")
def quizzes():
    with connection() as db:
        rows=many(db,"SELECT * FROM quizzes ORDER BY id DESC")
        for row in rows: row["questions"] = json.loads(row["questions"])
        return rows
@app.post("/api/quizzes/{quiz_id}/attempts")
def save_attempt(quiz_id: int, data: AttemptIn):
    with connection() as db:
        quiz = one(db, "SELECT questions FROM quizzes WHERE id=?", (quiz_id,))
        if not quiz: raise HTTPException(404,"Quiz not found")
        questions = json.loads(quiz["questions"])
        if data.total != len(questions): raise HTTPException(422,"Quiz total does not match its questions")
        if data.answers:
            if len(data.answers) != len(questions) or any(answer not in range(4) for answer in data.answers): raise HTTPException(422,"Quiz answers are invalid")
            score = sum(answer == question.get("answer") for answer, question in zip(data.answers, questions))
        else:
            score = data.score
        if score > data.total: raise HTTPException(422,"Score cannot exceed total")
        db.execute("UPDATE quizzes SET score=?,total=? WHERE id=?",(score,data.total,quiz_id))
        db.execute("INSERT INTO quiz_attempts(quiz_id,score,total,answers,created_at) VALUES(?,?,?,?,?)", (quiz_id,score,data.total,json.dumps(data.answers),now()))
    record_activity("quiz",f"Completed a quiz: {score}/{data.total}")
    return {"saved":True,"score":score,"total":data.total}

@app.get("/api/insights/weak-topics")
def weak_topics():
    with connection() as db:
        attempts = many(db, "SELECT a.answers,q.questions,q.note_id,q.title FROM quiz_attempts a JOIN quizzes q ON q.id=a.quiz_id ORDER BY a.id DESC LIMIT 100")
    counts = {}
    for attempt in attempts:
        answers = json.loads(attempt["answers"])
        questions = json.loads(attempt["questions"])
        for index, answer in enumerate(answers):
            if index >= len(questions) or answer == questions[index].get("answer"):
                continue
            topic = str(questions[index].get("topic", "General"))[:60]
            key = (topic, attempt["note_id"], attempt["title"])
            counts[key] = counts.get(key, 0) + 1
    return [{"topic": key[0], "note_id": key[1], "note_title": key[2], "misses": misses} for key, misses in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]]

@app.post("/api/ai/focus-quiz")
def make_focus_quiz(data: GenerateIn):
    if not data.topics:
        raise HTTPException(400, "Choose at least one topic to practice")
    with connection() as db:
        note = one(db, "SELECT * FROM notes WHERE id=?", (data.note_id,))
        if not note: raise HTTPException(404, "Note not found")
    try:
        output = generate("quiz", note["title"], note["subject"], note["content"], focus_topics=data.topics)
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    with connection() as db:
        cur = db.execute("INSERT INTO quizzes(note_id,title,questions,created_at) VALUES(?,?,?,?)", (data.note_id, f"Practice: {', '.join(data.topics[:2])}", json.dumps(output["questions"]), now()))
        result = {"id":cur.lastrowid,"note_id":data.note_id,"title":f"Practice: {', '.join(data.topics[:2])}","questions":output["questions"]}
    record_activity("quiz", f"Created a focused quiz for {note['title']}")
    return result

@app.post("/api/ai/ask")
def ask_notes(data: AskIn):
    with connection() as db:
        note = one(db, "SELECT * FROM notes WHERE id=?", (data.note_id,))
        if not note: raise HTTPException(404, "Note not found")
    try:
        result = generate("ask", note["title"], note["subject"], note["content"], question=data.question)
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    record_activity("question", f"Asked about {note['title']}")
    return result

@app.get("/api/flashcards/due")
def due_flashcard_sets():
    current = now()
    with connection() as db:
        sets = many(db, "SELECT * FROM flashcard_sets ORDER BY id DESC")
        reviews = many(db, "SELECT set_id,card_index,due_at FROM card_reviews")
    review_map = {(r["set_id"], r["card_index"]): r["due_at"] for r in reviews}
    result = []
    for card_set in sets:
        cards = json.loads(card_set["cards"])
        due = [i for i in range(len(cards)) if review_map.get((card_set["id"], i), current) <= current]
        if due:
            result.append({"set_id":card_set["id"],"title":card_set["title"],"due_indices":due,"due_count":len(due)})
    return result

@app.get("/api/flashcards/{set_id}/due")
def due_cards_for_set(set_id: int):
    current = now()
    with connection() as db:
        card_set = one(db, "SELECT * FROM flashcard_sets WHERE id=?", (set_id,))
        if not card_set: raise HTTPException(404, "Flashcard set not found")
        reviews = many(db, "SELECT card_index,due_at FROM card_reviews WHERE set_id=?", (set_id,))
    cards = json.loads(card_set["cards"])
    due_map = {r["card_index"]:r["due_at"] for r in reviews}
    return [{"set_id":set_id,"card_index":i,"front":cards[i]["front"],"back":cards[i]["back"],"title":card_set["title"]} for i in range(len(cards)) if due_map.get(i, current) <= current]

@app.post("/api/flashcards/{set_id}/cards/{card_index}/review")
def review_flashcard(set_id: int, card_index: int, data: CardReviewIn):
    current = datetime.now(timezone.utc)
    with connection() as db:
        card_set = one(db, "SELECT cards,seen_cards FROM flashcard_sets WHERE id=?", (set_id,))
        if not card_set: raise HTTPException(404, "Flashcard set not found")
        cards = json.loads(card_set["cards"])
        if card_index < 0 or card_index >= len(cards): raise HTTPException(404, "Flashcard not found")
        previous = one(db, "SELECT interval_days,repetitions,ease FROM card_reviews WHERE set_id=? AND card_index=?", (set_id, card_index))
        interval = previous["interval_days"] if previous else 0
        reps = previous["repetitions"] if previous else 0
        ease = previous["ease"] if previous else 2.5
        if data.rating == "again": interval, reps = 1/48, 0
        elif data.rating == "hard": interval, reps, ease = max(1, interval * 1.2), reps + 1, max(1.3, ease - 0.15)
        elif data.rating == "good": interval, reps = (1 if reps == 0 else max(1, interval * ease)), reps + 1
        else: interval, reps, ease = (3 if reps == 0 else max(2, interval * (ease + 0.3))), reps + 1, min(3.2, ease + 0.15)
        due = current + timedelta(days=interval)
        db.execute("INSERT INTO card_reviews(set_id,card_index,due_at,interval_days,repetitions,ease,last_rating) VALUES(?,?,?,?,?,?,?) ON CONFLICT(set_id,card_index) DO UPDATE SET due_at=excluded.due_at,interval_days=excluded.interval_days,repetitions=excluded.repetitions,ease=excluded.ease,last_rating=excluded.last_rating", (set_id,card_index,due.isoformat(),interval,reps,ease,data.rating))
        seen = sorted(set(json.loads(card_set["seen_cards"]) + [card_index]))
        db.execute("UPDATE flashcard_sets SET seen_cards=? WHERE id=?", (json.dumps(seen), set_id))
    return {"saved":True,"due_at":due.isoformat(),"interval_days":round(interval,2),"rating":data.rating}

@app.get("/api/focus/sessions")
def focus_sessions():
    with connection() as db:
        return {"total_seconds":one(db,"SELECT COALESCE(SUM(duration_seconds),0) n FROM focus_sessions")["n"],"sessions":many(db,"SELECT * FROM focus_sessions ORDER BY id DESC LIMIT 10")}

@app.post("/api/focus/sessions")
def save_focus_session(data: FocusIn):
    with connection() as db:
        if data.task_id is not None and not one(db,"SELECT id FROM tasks WHERE id=?",(data.task_id,)):
            raise HTTPException(404,"Study task not found")
        cur = db.execute("INSERT INTO focus_sessions(task_id,duration_seconds,completed_at) VALUES(?,?,?)", (data.task_id,data.duration_seconds,now()))
        session = dict(one(db,"SELECT * FROM focus_sessions WHERE id=?",(cur.lastrowid,)))
    record_activity("focus",f"Focused for {max(1,round(data.duration_seconds/60))} minutes")
    return session

@app.get("/api/study-pack/{note_id}")
def study_pack(note_id: int):
    with connection() as db:
        note = one(db,"SELECT * FROM notes WHERE id=?",(note_id,))
        if not note: raise HTTPException(404,"Note not found")
        quiz = one(db,"SELECT title,questions FROM quizzes WHERE note_id=? ORDER BY id DESC LIMIT 1",(note_id,))
        card_set = one(db,"SELECT title,cards FROM flashcard_sets WHERE note_id=? ORDER BY id DESC LIMIT 1",(note_id,))
    return {"note":dict(note),"quiz":{"title":quiz["title"],"questions":json.loads(quiz["questions"])} if quiz else None,"flashcards":{"title":card_set["title"],"cards":json.loads(card_set["cards"])} if card_set else None}
