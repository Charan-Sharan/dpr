export interface Citation {
  source_id: string
  quote: string
}
export interface Claim {
  text: string
  citations?: Citation[]
}
export interface Block {
  id: string
  text: string
  claims?: Claim[]
}
export interface Section {
  id: string
  heading: string
  blocks: Block[]
}
export interface Paper {
  id: string
  number: number
  at: number
  title: string
  parent?: string
  sections: Section[]
}
export interface Source {
  id: string
  title: string
  text?: string
}
export interface Project {
  id: string
  name: string
  dpr_enabled?: boolean
}
export interface Task {
  id: string
  status: string
  instruction: string
  reason?: string
  before?: string
  diff?: string
  finding?: { finding: string }
  proposal?: { text: string; claims?: Claim[] }
  review?: { rationale: string }
  audit?: { rationale: string }
}
export interface Activity {
  id: string
  job_id: string
  at: number
  role: string
  message: string
  detail?: unknown
  seq: number
  kind: string
}
export interface Participant {
  id?: string
  perspective: string
  provider: string
  model: string
  role: string
}
export interface Turn {
  id: string
  role: string
  text: string
  at: number
  ignored?: boolean
  model?: string
  independent?: boolean
  reply_to?: string
}
export interface Job {
  id: string
  at: number
  status: string
  prompt: string
  summary?: string
  error?: string
  schema?: number
  tasks: Task[]
  mode: string
  round: number
  calls: number
  contributions: number
  panel: Participant[]
  actual_models?: Record<string, string>
  turns: Turn[]
  activity: Activity[]
  coverage?: string[]
  review_version?: string
  synthesis_complete?: boolean
  checkpoint?: {
    summary?: string
    disagreements?: string[]
    missing_evidence?: string[]
    choices?: string[]
  }
}
export interface Memory {
  id: string
  kind: string
  status: string
  text: string
  authority: string
  stale?: boolean
  turn_id?: string
  evidence_status?: string
  citations?: Citation[]
  history: { action: string; text: string }[]
}
export interface Snapshot {
  project: Project
  projects: Project[]
  paper: Paper
  sources: Source[]
  jobs: Job[]
  events: Activity[]
  providers: { id: string; configured: boolean }[]
  scholarship: { sessions: Job[]; memory: Memory[] }
  versions: { id: string; number: number; prompt: string; at: number }[]
}
export interface Selection {
  version_id: string
  section_id: string
  block_id: string
  text: string
  start: number
  end: number
}
