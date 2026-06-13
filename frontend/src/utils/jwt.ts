/**
 * JWT 工具 — 只做客户端解码（payload）。不做签名验证，仅用于读 exp 预判是否过期。
 * 解码失败返回 null；调用方需兜底。
 */

export interface JwtPayload {
  exp?: number  // seconds since epoch
  iat?: number
  sub?: string | number
  [key: string]: unknown
}

function base64UrlDecode(input: string): string {
  let s = input.replace(/-/g, '+').replace(/_/g, '/')
  const pad = s.length % 4
  if (pad) s += '='.repeat(4 - pad)
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return decodeURIComponent(
      atob(s)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    )
  } catch {
    return ''
  }
}

export function decodeJwt(token: string): JwtPayload | null {
  const parts = token.split('.')
  if (parts.length !== 3) return null
  const decoded = base64UrlDecode(parts[1])
  if (!decoded) return null
  try {
    return JSON.parse(decoded) as JwtPayload
  } catch {
    return null
  }
}

/** Token 还剩多少秒过期；未能解析或无 exp 返回 Infinity（视作不过期，由后端兜底） */
export function tokenRemainingSeconds(token: string | null | undefined): number {
  if (!token) return 0
  const payload = decodeJwt(token)
  if (!payload?.exp) return Number.POSITIVE_INFINITY
  const now = Math.floor(Date.now() / 1000)
  return payload.exp - now
}

/** 剩余时间 < 阈值 ⇒ 视为即将过期，值单位秒 */
export function tokenExpiringSoon(token: string | null | undefined, thresholdSeconds = 60): boolean {
  const remaining = tokenRemainingSeconds(token)
  return remaining !== Number.POSITIVE_INFINITY && remaining < thresholdSeconds
}
