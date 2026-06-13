import client from './client'

interface RetrievePayload {
  query: string
  stage?: string
  top_k?: number
  style_hint?: string
  context_hint?: string
  filter_mode?: string
  filter_value?: string
}

interface AnnotatePayload {
  raw_text: string
  style_hint?: string
  context_hint?: string
  prompt_mode?: string
  filter_mode?: string
  filter_value?: string
}

interface ExportAnnotationPayload {
  raw_text: string
  format?: 'csv' | 'json' | 'markdown'
  style_hint?: string
  context_hint?: string
  prompt_mode?: string
  filter_mode?: string
  filter_value?: string
}

interface BindingEntry {
  shot_index: number
  character_refs?: string[]
  scene_refs?: string[]
  prop_refs?: string[]
  costume_refs?: string[]
  style_refs?: string[]
}

export const retrievePrompt = (payload: RetrievePayload) =>
  client.post('/prompt/retrieve', payload)

export const getLibraryFilters = () =>
  client.get('/prompt/library-filters')

export const annotateScript = (payload: AnnotatePayload) =>
  client.post('/director/annotate-clean-script', payload)

export const exportAnnotation = (payload: ExportAnnotationPayload) =>
  client.post('/director/annotate-clean-script/export', payload)

export const getReferenceBindings = (projectId: string) =>
  client.get(`/director/${projectId}/reference-bindings`)

export const saveReferenceBindings = (projectId: string, bindings: BindingEntry[]) =>
  client.post(`/director/${projectId}/reference-bindings`, { bindings })
