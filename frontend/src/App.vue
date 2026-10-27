<template>
  <div class="flex h-screen w-screen overflow-hidden bg-[#e5e5e5] font-sans antialiased text-gray-800">
    <!-- 最左侧深色导航栏 -->
    <Sidebar
      v-model:activeTab="activeTab"
      :currentAccount="currentAccount"
      :isOnline="isWsOnline"
    />

    <!-- 视图 1：微信聊天主视图 (中间会话列表 + 右侧主聊天面板) -->
    <div v-show="activeTab === 'chat'" class="flex-1 flex min-w-0 h-full overflow-hidden">
      <SessionList
        :sessions="sessions"
        :activeSession="activeSession"
        :currentAccount="currentAccount"
        @select="onSelectSession"
      />
      <ChatPanel
        :activeSession="activeSession"
        :messages="messages"
        @toggle-whitelist="toggleWhitelistForActive"
        @config-debounce="promptDebounceForActive"
        @toast="triggerToast"
      />
    </div>

    <!-- 视图 2：模型配置 -->
    <ConfigPanel
      v-if="activeTab === 'config'"
      @toast="triggerToast"
    />

    <!-- 视图 3：性格设计 -->
    <PersonaPanel
      v-if="activeTab === 'persona'"
      @toast="triggerToast"
    />

    <!-- 视图 4：分层记忆中心 -->
    <MemoryPanel
      v-if="activeTab === 'memory'"
      :sessions="sessions"
      @toast="triggerToast"
    />

    <!-- 视图 5：自动回复白名单 -->
    <WhitelistPanel
      v-if="activeTab === 'whitelist'"
      @toast="triggerToast"
      @refresh-sessions="loadSessions"
    />

    <!-- 全局轻量浮层提示 -->
    <Toast ref="toastRef" />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import Sidebar from '@/components/Sidebar.vue'
import SessionList from '@/components/SessionList.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import ConfigPanel from '@/components/ConfigPanel.vue'
import PersonaPanel from '@/components/PersonaPanel.vue'
import MemoryPanel from '@/components/MemoryPanel.vue'
import WhitelistPanel from '@/components/WhitelistPanel.vue'
import Toast from '@/components/Toast.vue'
import { api } from '@/api'

const activeTab = ref('chat')
const accounts = ref([])
const currentAccount = ref(null)
const sessions = ref([])
const activeSession = ref(null)
const messages = ref([])
const isWsOnline = ref(false)
const toastRef = ref(null)

let ws = null
let pollTimer = null

function triggerToast(msg) {
  if (toastRef.value) toastRef.value.show(msg)
}

onMounted(async () => {
  await loadAccounts()
  initWebSocket()
})

onUnmounted(() => {
  if (ws) ws.close()
  if (pollTimer) clearInterval(pollTimer)
})

async function loadAccounts() {
  try {
    const res = await api.getAccounts()
    accounts.value = res.data || []
    if (accounts.value.length > 0) {
      currentAccount.value = accounts.value[0]
      await loadSessions()
    }
  } catch (e) {
    triggerToast('加载账号列表失败: ' + e.message)
  }
}

async function loadSessions() {
  if (!currentAccount.value) return
  try {
    const res = await api.getSessions(currentAccount.value.account)
    sessions.value = res.data || []
    // 同步刷新当前 activeSession 的白名单与聚合状态
    if (activeSession.value) {
      const match = sessions.value.find(s => s.username === activeSession.value.username)
      if (match) {
        activeSession.value = { ...activeSession.value, ...match }
      }
    }
  } catch (e) {
    console.error('加载会话失败:', e)
  }
}

async function onSelectSession(s) {
  activeSession.value = s
  await loadMessages(s.username)
}

async function loadMessages(chatId) {
  if (!currentAccount.value || !chatId) return
  try {
    const res = await api.getMessages(currentAccount.value.account, chatId, 80)
    messages.value = res.data || []
  } catch (e) {
    console.error('加载消息历史失败:', e)
  }
}

async function toggleWhitelistForActive() {
  if (!activeSession.value) return
  const current = !!(activeSession.value.in_whitelist || activeSession.value.auto_reply)
  const target = !current
  try {
    const res = await api.toggleSessionAutoReply({
      chat_id: activeSession.value.username,
      name: activeSession.value.title,
      is_group: !!activeSession.value.is_group,
      enabled: target,
    })
    if (res.code === 0) {
      activeSession.value.in_whitelist = target
      activeSession.value.auto_reply = target
      await loadSessions()
      triggerToast(target ? '已加入白名单并开启全自动回复！' : '已移出白名单并关闭自动回复')
    }
  } catch (e) {
    triggerToast('设置白名单失败: ' + e.message)
  }
}

async function promptDebounceForActive() {
  if (!activeSession.value) return
  const current = activeSession.value.debounce_sec || 0
  const isGroup = activeSession.value.is_group
  const defaultSec = isGroup ? 6 : 3
  const input = prompt(
    `设置当前【${activeSession.value.title}】的连发消息防刷聚合等待时间 (秒)：\n` +
    `（在此期间群友/好友连发的多条消息会合并为一次回复）\n` +
    `输入具体秒数（如 5 或 10），填 0 则恢复系统默认 (${defaultSec} 秒)：`,
    current > 0 ? current : defaultSec
  )
  if (input === null) return
  const val = parseFloat(input)
  if (isNaN(val) || val < 0) {
    triggerToast('请输入有效的秒数！')
    return
  }
  try {
    const res = await api.setSessionDebounce({
      chat_id: activeSession.value.username,
      debounce_sec: val,
    })
    if (res.code === 0) {
      activeSession.value.debounce_sec = val
      await loadSessions()
      triggerToast(val > 0 ? `已设置该会话聚合等待时间为 ${val} 秒` : '已恢复系统默认聚合时间')
    }
  } catch (e) {
    triggerToast('设置聚合时间失败: ' + e.message)
  }
}

function initWebSocket() {
  const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${wsProto}//${location.host}/ws`
  try {
    ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      isWsOnline.value = true
    }
    ws.onclose = () => {
      isWsOnline.value = false
      setTimeout(initWebSocket, 3000)
    }
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.type === 'new_message') {
          const msg = payload.data
          if (activeSession.value && (msg.chat_id === activeSession.value.username || msg.username === activeSession.value.username)) {
            messages.value.push(msg)
          }
          loadSessions()
        } else if (payload.type === 'ai_auto_reply') {
          triggerToast(`🤖 [AI自动回复 -> ${payload.sender_name}]: ${payload.reply}`)
        }
      } catch (err) {
        console.error('WS 数据解析异常:', err)
      }
    }
  } catch (e) {
    console.error('WebSocket 连接异常:', e)
  }
}
</script>
