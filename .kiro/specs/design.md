# StudyBuddy AI design

## Architecture
- `frontend/`: React + TypeScript + Vite single-page app. `services/api.ts` is the only HTTP layer; presentational pieces live under `components/` and page-level screens under `pages/`.
- `backend/app/`: FastAPI routes, Pydantic validation, SQLite repository, and LM Studio service. The browser talks only to FastAPI; AI endpoint configuration stays server-side.
- SQLite tables: notes, tasks, quizzes, quiz_attempts, flashcard_sets, card_reviews, focus_sessions, and activity. JSON content is stored in text fields for generated question/card arrays and answer selections.

## UX
- Sidebar navigation for Home, Notes, Flashcards, Planner, and Settings; compact bottom navigation on mobile.
- Warm parchment canvas, deep plum text, violet accents, orange highlights, rounded cards, and a small friendly ghost motif. Dark theme uses ink-purple surfaces.
- Dashboard emphasizes a welcoming headline, one primary create-note action, service status, progress, and recent activity.
- Notes workspace uses an editor list/detail layout; generated assets appear as focused study screens with clear loading and error feedback.
- Empty states guide the next real action. No decorative controls are presented as working actions unless wired.

## Data and API
- `GET /api/health`, `/api/notes`, `/api/tasks`, `/api/activity`, `/api/stats`
- `POST /api/notes`, `PUT/DELETE /api/notes/{id}`
- `POST /api/ai/summary|quiz|flashcards` with note id; generated quiz/card sets are saved.
- `POST /api/quizzes/{id}/attempts`; task create/update/delete endpoints.
- Responses use Pydantic models; AI output is JSON-only, parsed defensively, and checked for shape and answer validity.
- Spaced repetition schedules each card after Again/Hard/Good/Easy ratings; the due queue combines sets.
- Quiz attempts store selected choices so the dashboard can group misses by generated topic and request a short focused quiz.
- Note Q&A returns exact quotations and the backend filters out citations that do not occur in the source note.
- Focus sessions persist elapsed seconds and an optional linked task. Exam packs use a print stylesheet and the browser's Save as PDF flow.
