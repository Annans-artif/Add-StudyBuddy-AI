function localApiBase(configured: string | undefined): string {
  const value = configured ?? 'http://127.0.0.1:8001/api'
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    const isLocal = host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
    if (!isLocal || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error()
    }
    return value.replace(/\/+$/, '')
  } catch {
    throw new Error('For privacy, VITE_API_URL must point to a local backend such as http://127.0.0.1:8001/api.')
  }
}

const BASE = localApiBase(import.meta.env.VITE_API_URL)
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(`${BASE}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } }) }
  catch { throw new Error('Backend is offline. Start the FastAPI server and try again.') }
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try { message = (await response.json()).detail ?? message } catch { /* keep fallback */ }
    throw new Error(message)
  }
  return response.json()
}
export type Note = { id: number; title: string; subject: string; content: string; summary: string; created_at: string; updated_at: string }
export type Task = { id: number; title: string; due_date: string; completed: number }
export type Question = { question: string; options: string[]; answer: number; explanation: string }
export type Flashcard = { front: string; back: string }
export type Quiz = { id: number; note_id: number; title: string; questions: Question[]; score: number | null; total: number | null }
export type CardSet = { id: number; title: string; cards: Flashcard[]; seen_cards?: number[] }
export type Health = { backend: string; ai: string; model: string; ai_message?: string }
export type WeakTopic = { topic:string; note_id:number; note_title:string; misses:number }
export type DueCard = { set_id:number; card_index:number; front:string; back:string; title:string }
export type DueSet = { set_id:number; title:string; due_indices:number[]; due_count:number }
export type FocusSession = { id:number; task_id:number|null; duration_seconds:number; completed_at:string }
export type StudyPack = { note:Note; quiz:{title:string;questions:Question[]}|null; flashcards:{title:string;cards:Flashcard[]}|null }
export const api = {
  health: () => request<Health>('/health'),
  notes: () => request<Note[]>('/notes'),
  saveNote: (n: Pick<Note,'title'|'subject'|'content'>, id?: number) => request<Note>(id ? `/notes/${id}` : '/notes', { method: id ? 'PUT' : 'POST', body: JSON.stringify(n) }),
  deleteNote: (id: number) => request(`/notes/${id}`, { method: 'DELETE' }),
  tasks: () => request<Task[]>('/tasks'),
  addTask: (title: string, due_date: string) => request<Task>('/tasks', { method: 'POST', body: JSON.stringify({ title, due_date }) }),
  toggleTask: (id: number, completed: boolean) => request<Task>(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ completed }) }),
  deleteTask: (id: number) => request(`/tasks/${id}`, { method: 'DELETE' }),
  stats: () => request<{ notes:number; quizzes:number; cards:number; tasks:number; recent:{kind:string;label:string;created_at:string}[] }>('/stats'),
  generate: <T,>(kind: 'summary'|'quiz'|'flashcards', note_id: number) => request<T>(`/ai/${kind}`, { method: 'POST', body: JSON.stringify({ note_id }) }),
  focusQuiz: (note_id:number,topics:string[]) => request<{id:number;note_id:number;title:string;questions:Question[]}>('/ai/focus-quiz',{method:'POST',body:JSON.stringify({note_id,topics})}),
  ask: (note_id:number,question:string) => request<{answer:string;citations:string[]}>('/ai/ask',{method:'POST',body:JSON.stringify({note_id,question})}),
  quizzes: () => request<Quiz[]>('/quizzes'), cards: () => request<CardSet[]>('/flashcards'),
  dueSets: () => request<DueSet[]>('/flashcards/due'), dueCards: (id:number) => request<DueCard[]>(`/flashcards/${id}/due`),
  reviewCard: (setId:number,cardIndex:number,rating:'again'|'hard'|'good'|'easy') => request(`/flashcards/${setId}/cards/${cardIndex}/review`,{method:'POST',body:JSON.stringify({rating})}),
  cardProgress: (id:number, seen_cards:number[]) => request(`/flashcards/${id}/progress`, { method:'PATCH', body:JSON.stringify({seen_cards}) }),
  weakTopics: () => request<WeakTopic[]>('/insights/weak-topics'),
  focusSessions: () => request<{total_seconds:number;sessions:FocusSession[]}>('/focus/sessions'),
  saveFocus: (duration_seconds:number,task_id:number|null) => request<FocusSession>('/focus/sessions',{method:'POST',body:JSON.stringify({duration_seconds,task_id})}),
  studyPack: (note_id:number) => request<StudyPack>(`/study-pack/${note_id}`),
  attempt: (id:number, score:number,total:number,answers:number[]) => request(`/quizzes/${id}/attempts`, { method:'POST', body:JSON.stringify({score,total,answers}) }),
}
