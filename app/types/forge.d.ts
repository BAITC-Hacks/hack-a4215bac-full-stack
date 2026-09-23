export type Role = 'business' | 'team'
export type FieldState = 'missing' | 'ai_draft' | 'confirmed' | 'warning'
export type Severity = 'error' | 'warning' | 'passed'
export type BuildStatus = 'failed' | 'warning' | 'success'

export interface Diagnostic {
  code: string
  severity: Severity
  field: string
  title: string
  consequence: string
  action: string
  max_score_impact: number
}

export interface TaskPackItem {
  key: string
  label: string
  value: string
  status: FieldState
  confirmed: boolean
  source: 'user' | 'answer' | 'ai' | 'none'
  answer_id: string | null
  updated_at: string | null
  points: number
}

export interface HandoffCheck {
  id: 'problem' | 'users' | 'data' | 'deliverable' | 'acceptance'
  question: string
  passed: boolean
  field: string
  explanation: string
  consequence: string
}

export interface ForgeTask {
  id: string
  owner_id: string
  owner: string
  title: string
  category: string
  industry: string
  deadline: string
  published: boolean
  fields: Record<string, string>
  confirmed: Record<string, boolean>
  extras: Record<string, string>
  extra_confirmed: Record<string, boolean>
  ai_evidence: Record<string, string>
  field_meta: Record<string, { source: string; answer_id: string | null; updated_at: string }>
  pack_version: string
  build: { status: BuildStatus; score: number; errors: number; warnings: number; diagnostics: Diagnostic[]; next_step: Diagnostic | null }
  task_pack: { version: string; sections: { name: string; items: TaskPackItem[] }[] }
  handoff_result: { passed: number; total: number; checks: HandoffCheck[]; mode: 'rules' | 'openai'; notice: string } | null
  test_lab_result: { version: string; generated_at: string; items: { kind: 'normal' | 'edge' | 'failure'; title: string; steps: string; expected: string; open_question: string; confirmed: boolean }[] } | null
  proposal_count: number
  created_at: string
}

export interface ForgeTeam {
  id: string
  name: string
  skills: string[]
  initials: string
  points: number
}

export interface ForgeProposal {
  id: string
  task_id: string
  team_id: string
  idea: string
  plan: string
  deadline: string
  link: string
  questions: string
  status: 'pending' | 'accepted' | 'rejected'
  progress_awarded: boolean
  created_at: string
}
