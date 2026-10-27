// API 集中请求封装
const BASE_URL = ''

async function request(url, options = {}) {
  const res = await fetch(`${BASE_URL}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })
  if (!res.ok) {
    let errText = ''
    try {
      const errJson = await res.json()
      errText = errJson.detail || errJson.message || res.statusText
    } catch {
      errText = await res.text()
    }
    throw new Error(errText || `请求失败 (${res.status})`)
  }
  return res.json()
}

export const api = {
  // 微信基础
  getAccounts: () => request('/api/accounts'),
  getSessions: (account) => request(`/api/sessions${account ? `?account=${encodeURIComponent(account)}` : ''}`),
  getMessages: (account, chatId, limit = 80) =>
    request(`/api/messages?chat_id=${encodeURIComponent(chatId)}&limit=${limit}${account ? `&account=${encodeURIComponent(account)}` : ''}`),

  // AI 模型与配置
  getAiConfig: () => request('/api/ai/config'),
  saveAiConfig: (payload) => request('/api/ai/config', { method: 'POST', body: JSON.stringify(payload) }),
  testAiConnection: () => request('/api/ai/test_connection', { method: 'POST' }),

  // 性格人设
  getPersona: () => request('/api/ai/persona'),
  savePersona: (payload) => request('/api/ai/persona', { method: 'POST', body: JSON.stringify(payload) }),

  // 记忆中心
  getGlobalMemory: () => request('/api/ai/memory/global'),
  saveGlobalMemory: (payload) => request('/api/ai/memory/global', { method: 'POST', body: JSON.stringify(payload) }),
  deleteGlobalFact: (index) => request(`/api/ai/memory/global?index=${index}`, { method: 'DELETE' }),

  getSessionMemory: (chatId) => request(`/api/ai/memory/session?chat_id=${encodeURIComponent(chatId)}`),
  addSessionNote: (payload) => request('/api/ai/memory/session/note', { method: 'POST', body: JSON.stringify(payload) }),
  deleteSessionNote: (chatId, index) =>
    request(`/api/ai/memory/session/note?chat_id=${encodeURIComponent(chatId)}&index=${index}`, { method: 'DELETE' }),

  // 会话独立开关与专属聚合延时
  toggleSessionAutoReply: (payload) => request('/api/ai/session/auto_reply', { method: 'POST', body: JSON.stringify(payload) }),
  setSessionDebounce: (payload) => request('/api/ai/session/debounce', { method: 'POST', body: JSON.stringify(payload) }),

  // 白名单管理
  getWhitelist: () => request('/api/ai/whitelist'),
  addWhitelist: (payload) => request('/api/ai/whitelist', { method: 'POST', body: JSON.stringify(payload) }),
  deleteWhitelist: (chatId) => request(`/api/ai/whitelist?chat_id=${encodeURIComponent(chatId)}`, { method: 'DELETE' }),
  toggleWhitelist: (enabled) => request('/api/ai/whitelist/toggle', { method: 'POST', body: JSON.stringify({ enabled }) }),

  // 建议与发送
  generateSuggestions: (payload) => request('/api/ai/generate_suggestions', { method: 'POST', body: JSON.stringify(payload) }),
  sendMessage: (payload) => request('/api/ai/send_message', { method: 'POST', body: JSON.stringify(payload) }),
}
