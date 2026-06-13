import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

const edgePath = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const runId = process.env.AGENT_RUN_ID
const token = process.env.AGENT_ACCESS_TOKEN
const baseUrl = process.env.FRONTEND_BASE_URL || 'http://localhost:3000'
const remotePort = Number(process.env.CDP_PORT || 9223)

if (!runId || !token) {
  throw new Error('AGENT_RUN_ID and AGENT_ACCESS_TOKEN are required')
}

const pageUrl = `${baseUrl}/director/agent-run/${runId}`
const userDataDir = resolve('storage', 'browser-agent-run-cdp-profile')
const screenshotPath = resolve('storage', 'browser-agent-run-check.png')
await mkdir(userDataDir, { recursive: true })
await mkdir(resolve('storage'), { recursive: true })

const browser = spawn(edgePath, [
  '--headless',
  '--disable-gpu',
  '--disable-dev-shm-usage',
  '--no-first-run',
  '--no-default-browser-check',
  `--remote-debugging-port=${remotePort}`,
  `--user-data-dir=${userDataDir}`,
  'about:blank',
], { stdio: ['ignore', 'pipe', 'pipe'], detached: false })

let browserOutput = ''
browser.stdout?.on('data', (chunk) => {
  browserOutput += chunk.toString()
})
browser.stderr?.on('data', (chunk) => {
  browserOutput += chunk.toString()
})

try {
  const version = await waitForJson(`http://127.0.0.1:${remotePort}/json/version`, 50)
  const wsUrl = version.webSocketDebuggerUrl
  const cdp = await connectCdp(wsUrl)
  const page = await cdp.send('Target.createTarget', { url: 'about:blank' })
  const session = await cdp.attach(page.targetId)

  const network = {
    snapshot: 0,
    stream: 0,
    apiErrors: [],
    eventSource: false,
  }
  const consoleErrors = []

  session.on('Network.requestWillBeSent', (event) => {
    const url = String(event.request?.url || '')
    if (url.includes(`/api/agent-runs/${runId}/snapshot`)) network.snapshot += 1
    if (url.includes(`/api/agent-runs/${runId}/stream`)) network.stream += 1
  })
  session.on('Network.responseReceived', (event) => {
    const url = String(event.response?.url || '')
    const status = Number(event.response?.status || 0)
    if (event.type === 'EventSource') network.eventSource = true
    if (url.includes('/api/') && status >= 400) {
      network.apiErrors.push({ url, status })
    }
  })
  session.on('Runtime.consoleAPICalled', (event) => {
    if (['error', 'warning'].includes(event.type)) {
      consoleErrors.push({
        type: event.type,
        text: (event.args || []).map((arg) => arg.value || arg.description || '').join(' '),
      })
    }
  })
  session.on('Runtime.exceptionThrown', (event) => {
    consoleErrors.push({ type: 'exception', text: event.exceptionDetails?.text || 'Runtime exception' })
  })

  await session.send('Runtime.enable')
  await session.send('Network.enable')
  await session.send('Page.enable')
  await session.send('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  })
  await session.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      localStorage.setItem('access_token', ${JSON.stringify(token)});
      localStorage.setItem('refresh_token', ${JSON.stringify(token)});
    `,
  })
  await session.send('Page.navigate', { url: pageUrl })
  await waitForLoad(session)
  await waitForCondition(session, `
    Boolean(document.querySelector('.output-board')) &&
    !document.body.innerText.includes('Loading run snapshot...')
  `, 80)
  await delay(3500)

  const beforeSubmit = await evalJson(session, `
    (() => {
      const text = document.body.innerText;
      const textarea = document.querySelector('.human-composer textarea');
      const button = document.querySelector('.human-composer button[type="submit"]');
      return {
        url: location.href,
        title: document.title,
        text,
        outputText: document.querySelector('.output-board')?.innerText || '',
        timelineText: document.querySelector('.run-workspace')?.innerText || '',
        outputBoard: Boolean(document.querySelector('.output-board')),
        timelineItems: document.querySelectorAll('.timeline-item, .event-item, [class*="event"]').length,
        images: document.querySelectorAll('.output-board img').length,
        videos: document.querySelectorAll('.output-board video').length,
        textareaDisabled: Boolean(textarea?.disabled),
        submitDisabledEmpty: Boolean(button?.disabled),
      };
    })()
  `)

  await session.send('Runtime.evaluate', {
    expression: `
      (() => {
        const textarea = document.querySelector('.human-composer textarea');
        textarea.value = '现在进度怎么样';
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
      })()
    `,
    awaitPromise: true,
  })
  await delay(250)
  const draftState = await evalJson(session, `
    (() => ({
      composer: document.querySelector('.human-composer')?.innerText || '',
      submitDisabledWithText: Boolean(document.querySelector('.human-composer button[type="submit"]')?.disabled),
    }))()
  `)

  if (draftState.submitDisabledWithText === false) {
    await session.send('Runtime.evaluate', {
      expression: `document.querySelector('.human-composer button[type="submit"]')?.click()`,
      awaitPromise: true,
    })
    await delay(1800)
  }
  const afterSubmit = await evalJson(session, `
    (() => ({
      composer: document.querySelector('.human-composer')?.innerText || '',
      textareaValue: document.querySelector('.human-composer textarea')?.value || '',
      errorText: document.querySelector('.composer-error')?.innerText || '',
      noticeText: document.querySelector('.composer-notice')?.innerText || '',
      url: location.href,
    }))()
  `)

  const png = await session.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
  await writeFile(screenshotPath, Buffer.from(png.data, 'base64'))

  const allText = `${beforeSubmit.text}\n${draftState.composer}\n${afterSubmit.composer}`
  const mojibakePattern = /鐢|鍙|瑙|闀|杩|鎴|鍓|瀵|绗|锛|�|\?\/(?:span|strong|a)>/
  const requiredText = ['生成成果', '参考图 / 关键帧', '视频片段 / 成片', '镜头状态']
  const missingText = requiredText.filter((item) => !allText.includes(item))

  const result = {
    ok:
      network.snapshot > 0 &&
      network.stream > 0 &&
      network.eventSource &&
      network.apiErrors.length === 0 &&
      beforeSubmit.outputBoard &&
      beforeSubmit.images >= 1 &&
      beforeSubmit.videos >= 1 &&
      beforeSubmit.submitDisabledEmpty &&
      draftState.composer.includes('运行已结束') &&
      draftState.submitDisabledWithText === true &&
      !afterSubmit.errorText &&
      missingText.length === 0 &&
      !mojibakePattern.test(allText),
    pageUrl,
    network,
    output: {
      hasBoard: beforeSubmit.outputBoard,
      images: beforeSubmit.images,
      videos: beforeSubmit.videos,
      missingText,
      mojibakeFound: mojibakePattern.test(allText),
    },
    composer: {
      disabledWhenEmpty: beforeSubmit.submitDisabledEmpty,
      terminalRunLockedWithText: draftState.submitDisabledWithText === true,
      afterSubmitError: afterSubmit.errorText,
      afterSubmitNotice: afterSubmit.noticeText,
      afterSubmitUrl: afterSubmit.url,
    },
    consoleErrors,
    screenshotPath,
  }

  console.log(JSON.stringify(result, null, 2))
  if (!result.ok) process.exitCode = 1
} finally {
  browser.kill()
}

async function waitForJson(url, attempts) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const response = await fetch(url)
      if (response.ok) return await response.json()
    } catch {
      // keep waiting
    }
    await delay(200)
  }
  throw new Error(`Timed out waiting for ${url}\n${browserOutput.slice(-2000)}`)
}

function connectCdp(wsUrl) {
  const ws = new WebSocket(wsUrl)
  let nextId = 1
  const callbacks = new Map()
  const rootHandlers = new Map()
  const sessionHandlers = new Map()

  ws.addEventListener('message', (message) => {
    const payload = JSON.parse(message.data)
    if (payload.id && callbacks.has(payload.id)) {
      const { resolve, reject } = callbacks.get(payload.id)
      callbacks.delete(payload.id)
      if (payload.error) reject(new Error(payload.error.message || JSON.stringify(payload.error)))
      else resolve(payload.result || {})
      return
    }
    const handlers = payload.sessionId ? sessionHandlers.get(payload.sessionId) : rootHandlers
    const set = handlers?.get(payload.method)
    if (set) set.forEach((handler) => handler(payload.params || {}))
  })

  const sendRaw = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = nextId++
    callbacks.set(id, { resolve, reject })
    ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }))
  })

  return new Promise((resolve, reject) => {
    ws.addEventListener('open', () => {
      resolve({
        send: (method, params) => sendRaw(method, params),
        attach: async (targetId) => {
          const attached = await sendRaw('Target.attachToTarget', { targetId, flatten: true })
          const sessionId = attached.sessionId
          sessionHandlers.set(sessionId, new Map())
          return {
            send: (method, params) => sendRaw(method, params, sessionId),
            on: (method, handler) => {
              const map = sessionHandlers.get(sessionId)
              if (!map.has(method)) map.set(method, new Set())
              map.get(method).add(handler)
            },
          }
        },
        on: (method, handler) => {
          if (!rootHandlers.has(method)) rootHandlers.set(method, new Set())
          rootHandlers.get(method).add(handler)
        },
      })
    })
    ws.addEventListener('error', reject)
  })
}

async function waitForLoad(session) {
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 15000)
    session.on('Page.loadEventFired', () => {
      clearTimeout(timeout)
      resolve()
    })
  })
}

async function waitForCondition(session, expression, attempts) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    if (value.result?.value) return
    await delay(250)
  }
  throw new Error(`Timed out waiting for condition: ${expression}`)
}

async function evalJson(session, expression) {
  const value = await session.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  })
  return value.result?.value
}
