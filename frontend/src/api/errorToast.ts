import type { AxiosError } from 'axios'

type ErrorHandler = (error: AxiosError, message: string) => void

let handler: ErrorHandler | null = null

export function setErrorToastHandler(fn: ErrorHandler | null): void {
  handler = fn
}

function getErrorPayload(error: AxiosError): any {
  const data = error.response?.data as any
  if (data && typeof data === 'object' && 'detail' in data) return data.detail
  return data
}

function extractDetailMessage(detail: any): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message.trim()) return detail.message
    if (typeof detail.error === 'string' && detail.error.trim()) return detail.error
  }
  return null
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function getCreditLimitParts(error: AxiosError): {
  remaining: number | null
  required: number | null
} {
  const payload = getErrorPayload(error)
  const userGuard = payload && typeof payload === 'object' ? payload.cost_guard?.user : null
  return {
    remaining: toNumber(userGuard?.credits_remaining),
    required: toNumber(payload?.credits_to_reserve),
  }
}

export function isCreditLimitError(error: AxiosError): boolean {
  if (error.response?.status !== 429) return false
  const payload = getErrorPayload(error)
  if (!payload || typeof payload !== 'object') return false

  const message = String(payload.message || '')
  return (
    message.includes('用户每日信用额度已达') ||
    Boolean(payload.cost_guard?.user) ||
    payload.credits_to_reserve != null
  )
}

export function creditLimitRedirectUrl(error: AxiosError): string {
  const { remaining, required } = getCreditLimitParts(error)
  const params = new URLSearchParams({
    type: 'tier_upgrade',
    reason: 'daily_credit_limit',
  })
  if (remaining != null) params.set('remaining', String(remaining))
  if (required != null) params.set('required', String(required))
  return `/recharge?${params.toString()}`
}

function formatCreditLimitMessage(error: AxiosError): string {
  const { remaining, required } = getCreditLimitParts(error)
  if (remaining != null && required != null) {
    return `今日可用积分不足：剩余 ${remaining}，本次需要 ${required}。请充值或升级会员后继续。`
  }
  return '今日可用积分不足，请充值或升级会员后继续。'
}

export function extractErrorMessage(error: AxiosError): string {
  const payload = getErrorPayload(error)
  const status = error.response?.status

  if (isCreditLimitError(error)) return formatCreditLimitMessage(error)

  const detailMessage = extractDetailMessage(payload)
  if (detailMessage) return detailMessage

  const detailObj = payload && typeof payload === 'object' ? (payload as any) : null

  if (status === 400) return '请求参数有误'
  if (status === 401) return '登录状态已失效，请重新登录'
  if (status === 403) return '没有权限执行此操作'
  if (status === 404) return '资源不存在或已删除'
  if (status === 409) return '当前操作与现有状态冲突，请刷新后重试'
  if (status === 422) return '提交内容未通过校验'
  if (status === 429) {
    const detailError = String(detailObj?.error || '').toLowerCase()
    const retryAfterRaw = detailObj?.retry_after ?? error.response?.headers?.['retry-after']
    const retryAfter = Number(retryAfterRaw)
    if (detailError.includes('concurrent task limit exceeded')) {
      const current = detailObj?.current ?? '?'
      const limit = detailObj?.limit ?? '?'
      return `并发任务已达上限（${current}/${limit}），请等待后重试`
    }
    if (Number.isFinite(retryAfter) && retryAfter > 0) {
      return `请求过于频繁，请在 ${retryAfter} 秒后重试`
    }
    return '请求过于频繁，请稍后再试'
  }
  if (status && status >= 500) return '服务暂不可用，请稍后再试'

  if (error.code === 'ECONNABORTED') return '请求超时，请检查网络后重试'
  if (error.code === 'ERR_NETWORK') return '网络连接异常，请检查后重试'
  if (error.code === 'ERR_CANCELED') return ''
  if (error.message?.toLowerCase().includes('network error')) return '网络连接异常'

  return error.message || '请求失败'
}

export function showErrorToast(error: AxiosError): void {
  const message = extractErrorMessage(error)
  if (!message) return

  // 401 由 client.ts 的登录刷新流程处理，避免重复提示。
  if (error.response?.status === 401) return

  if (handler) {
    handler(error, message)
    return
  }
  console.error('[http]', message, error)
}
