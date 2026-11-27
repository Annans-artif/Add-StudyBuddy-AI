# StudyBuddy AI requirements

## Purpose
StudyBuddy AI turns a student's own notes into summaries, multiple-choice quizzes, and flashcards. It also stores notes, study tasks, and progress locally for a single-user hackathon demo.

## Functional requirements
- Dashboard shows note and quiz counts, recent activity, quick actions, and backend/AI availability.
- Notes can be created, listed, edited, deleted, and used to generate a summary, quiz, or flashcards.
- Quiz items have four options, one correct answer, explanations, scoring, and retry support. Results persist.
- Flashcards can be flipped and navigated, with completion progress.
- Flashcards support spaced-repetition ratings that schedule their next review and provide a due queue.
- Planner tasks have a title, deadline, completion status, and can be created, completed, or deleted.
- Focus sessions can be started, paused, reset, linked to a task, and saved as study time.
- Students can ask questions about a saved note and see exact supporting note excerpts.
- Quiz misses are recorded by topic and can produce a focused follow-up quiz.
- A saved note can be exported as a print-ready study pack with its summary, quiz, and flashcards.
- Settings show service status, allow theme switching, and explain local AI configuration.
- SQLite persists all content and activity across backend restarts.
- The backend calls the configured OpenAI-compatible LM Studio endpoint and validates generated JSON. Service failures return actionable errors instead of crashing.

## Quality requirements
- Responsive, accessible, friendly Halloween-inspired UI with dark and light themes.
- Validate user input at the UI and API boundaries.
- Keep credentials and AI calls on the backend.
- Provide beginner-friendly setup and troubleshooting documentation.
- Use reusable React components and straightforward Python modules.

## Acceptance criteria
- Users can create a note and reload the app while retaining it.
- Each AI action uses the saved note text and either returns validated generated content or a readable local-server error.
- Users can finish/retry a quiz and move through/complete flashcards.
- Users can create, complete, and remove planner tasks.
- Flashcard ratings schedule future reviews and due cards can be reviewed together.
- Quiz attempts preserve selected answers; missed topics appear on the dashboard and can launch a targeted quiz.
- Note questions return a concise answer with quotations verified against the note text.
- Focus time is stored across restarts; the study pack prints from browser print/Save as PDF.
- Dashboard statistics update from persisted data.
- Both themes and mobile navigation work.
