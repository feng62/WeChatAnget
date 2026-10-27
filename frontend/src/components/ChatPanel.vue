<template>
  <main class="flex-1 bg-[#f8fafc] flex flex-col min-w-0 h-full overflow-hidden select-text relative">
    <!-- 未选会话时的缺省状态 -->
    <div v-if="!activeSession" class="flex-1 flex flex-col items-center justify-center text-slate-400 select-none">
      <div class="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-3 text-slate-300">
        <MessageSquare class="w-8 h-8 stroke-[1.5]" />
      </div>
      <p class="text-xs text-slate-400">选择左侧会话开启智能交互监控</p>
    </div>

    <!-- 选中会话后的完整聊天窗口 -->
    <template v-else>
      <!-- 聊天头部 -->
      <header class="h-14 px-6 bg-white/70 backdrop-blur-md border-b border-slate-200/70 flex items-center justify-between flex-shrink-0 select-none z-10">
        <div class="flex items-center gap-3 min-w-0">
          <h2 class="text-sm font-bold text-slate-900 truncate tracking-tight">{{ activeSession.title || activeSession.username }}</h2>
          <span class="text-[10px] font-medium bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full ring-1 ring-slate-200/60 flex-shrink-0">
            {{ activeSession.is_group ? '群聊' : '私聊' }}
          </span>

          <!-- 白名单托管快捷胶囊按钮 -->
          <button
            @click="$emit('toggle-whitelist')"
            :class="[
              'text-xs px-2.5 py-1 rounded-lg border flex items-center gap-1.5 font-medium transition cursor-pointer',
              (activeSession.in_whitelist || activeSession.auto_reply)
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
            ]"
            title="开启后收到消息将自动唤醒微信、搜索定位并回复"
          >
            <ShieldCheck class="w-3.5 h-3.5 stroke-[1.8] text-emerald-600" />
            <span>托管状态: {{ (activeSession.in_whitelist || activeSession.auto_reply) ? '生效中' : '未开启' }}</span>
          </button>

          <!-- 聚合防刷等待时间设置 -->
          <button
            @click="$emit('config-debounce')"
            class="text-xs px-2.5 py-1 rounded-lg border bg-white text-slate-600 border-slate-200 hover:bg-slate-50 transition cursor-pointer flex items-center gap-1.5"
            title="点击配置该聊天多条消息合并防刷等待秒数"
          >
            <Clock class="w-3.5 h-3.5 stroke-[1.8] text-slate-400" />
            <span>防刷聚合: {{ activeSession.debounce_sec > 0 ? `${activeSession.debounce_sec}s` : `默认 (${activeSession.is_group ? '6s' : '3s'})` }}</span>
          </button>
        </div>

        <div class="text-[11px] text-slate-400 font-mono">
          增量轮询 0.4s
        </div>
      </header>

      <!-- 消息记录区域 -->
      <div ref="chatBodyRef" class="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        <div
          v-for="msg in messages"
          :key="msg.msg_id || msg.local_id"
          :class="['flex gap-3', msg.is_from_me ? 'flex-row-reverse' : 'flex-row']"
        >
          <!-- 头像 -->
          <div
            :class="[
              'w-8 h-8 rounded-xl flex-shrink-0 flex items-center justify-center font-medium text-xs text-white shadow-2xs select-none',
              msg.is_from_me
                ? 'bg-gradient-to-br from-emerald-500 to-emerald-700'
                : 'bg-gradient-to-br from-slate-600 to-slate-800'
            ]"
          >
            {{ (msg.sender_name || (msg.is_from_me ? '我' : '友')).slice(0, 1) }}
          </div>

          <!-- 消息内容体 -->
          <div :class="['max-w-[72%] flex flex-col', msg.is_from_me ? 'items-end' : 'items-start']">
            <!-- 群聊发送人名字 -->
            <span v-if="!msg.is_from_me && activeSession.is_group" class="text-[11px] font-medium text-slate-400 mb-1 px-1">
              {{ msg.sender_name }}
            </span>

            <!-- 普通文本 / 气泡 -->
            <div
              v-if="msg.type === '文本' || !msg.type"
              :class="[
                'px-4 py-2.5 text-xs break-words leading-relaxed tracking-normal',
                msg.is_from_me
                  ? 'bg-emerald-600 text-white rounded-2xl rounded-tr-xs shadow-[0_1px_3px_rgba(5,150,105,0.2)]'
                  : 'bg-white text-slate-800 rounded-2xl rounded-tl-xs border border-slate-200/80 shadow-[0_1px_2px_rgba(0,0,0,0.03)]'
              ]"
            >
              {{ msg.text || msg.content }}
            </div>

            <!-- 图片消息 -->
            <div
              v-else-if="msg.type === '图片'"
              class="rounded-xl overflow-hidden border border-slate-200/80 bg-white p-1 max-w-[280px] shadow-2xs"
            >
              <img
                :src="`/api/media/image?chat_id=${encodeURIComponent(msg.chat_id || activeSession.username)}&local_id=${msg.local_id || msg.msg_id}&shard=${msg.shard || ''}`"
                alt="图片"
                class="rounded-lg object-cover max-h-60 w-auto cursor-pointer"
                loading="lazy"
                @error="onImageError"
              />
            </div>

            <!-- 语音消息 -->
            <div
              v-else-if="msg.type === '语音'"
              :class="[
                'px-4 py-2.5 rounded-2xl text-xs flex items-center gap-2 border shadow-2xs',
                msg.is_from_me
                  ? 'bg-emerald-600 text-white rounded-tr-xs border-emerald-500'
                  : 'bg-white text-slate-800 rounded-tl-xs border-slate-200/80'
              ]"
            >
              <Volume2 class="w-4 h-4 stroke-[1.8]" />
              <span>语音 {{ msg.voice_sec ? `${msg.voice_sec}s` : '' }}</span>
              <span v-if="msg.voice_text" class="italic opacity-90 pl-1 border-l border-current/20">"{{ msg.voice_text }}"</span>
            </div>

            <!-- 引用消息 -->
            <div
              v-else-if="msg.type === '引用消息'"
              :class="[
                'p-3.5 rounded-2xl text-xs border max-w-md shadow-2xs',
                msg.is_from_me
                  ? 'bg-emerald-600 text-white rounded-tr-xs border-emerald-500'
                  : 'bg-white text-slate-800 rounded-tl-xs border-slate-200/80'
              ]"
            >
              <div
                :class="[
                  'p-2 rounded-lg mb-1.5 text-[11px] border-l-2',
                  msg.is_from_me
                    ? 'bg-black/10 border-white/60 text-emerald-50'
                    : 'bg-slate-50 border-emerald-500 text-slate-600'
                ]"
              >
                <b>{{ msg.refer_name || '引用' }}:</b> {{ msg.refer_quote }}
              </div>
              <div class="text-xs font-medium">{{ msg.text || msg.content }}</div>
            </div>

            <!-- 分享卡片 -->
            <div
              v-else-if="msg.type === '卡片'"
              class="p-4 rounded-xl text-xs bg-white border border-slate-200/80 max-w-sm shadow-xs"
            >
              <div class="font-semibold text-slate-900 text-xs mb-1 truncate">{{ msg.card_title || '网页卡片' }}</div>
              <div class="text-slate-500 line-clamp-2 text-[11px] mb-2 leading-relaxed">{{ msg.card_desc || '' }}</div>
              <span class="text-[10px] text-slate-400 font-mono">链接分享卡片</span>
            </div>

            <!-- 兜底其他格式 -->
            <div v-else class="px-3.5 py-2 rounded-xl text-xs bg-slate-200/70 text-slate-700">
              [{{ msg.type }}] {{ msg.text || msg.content }}
            </div>
          </div>
        </div>
      </div>

      <!-- 底部操作与发送栏 (macOS / Linear 悬浮卡片风格) -->
      <div class="p-4 bg-transparent select-none">
        <div class="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-3 relative">
          <!-- AI 智能候选建议浮层 (Pop-over) -->
          <div
            v-if="showSuggestions"
            class="absolute bottom-full left-0 right-0 mb-3 bg-white/95 backdrop-blur-md rounded-2xl shadow-xl border border-slate-200/90 p-4 z-20"
          >
            <div class="flex items-center justify-between pb-2 mb-3 border-b border-slate-100 text-xs font-semibold text-slate-800">
              <span class="flex items-center gap-1.5 text-emerald-700">
                <Sparkles class="w-4 h-4 stroke-[2]" />
                <span>AI 智能建议回复 (结合最近上下文生成，点击一键发送)</span>
              </span>
              <button @click="showSuggestions = false" class="text-slate-400 hover:text-slate-600 p-1 cursor-pointer">
                <X class="w-4 h-4" />
              </button>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-2.5">
              <button
                v-for="s in suggestions"
                :key="s.style"
                @click="applySuggestion(s.text)"
                class="text-left p-3 rounded-xl bg-slate-50/80 hover:bg-emerald-50/60 border border-slate-200/60 hover:border-emerald-300 transition-all text-xs group cursor-pointer"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-800">
                    {{ s.style }}
                  </span>
                  <span class="text-[10px] text-slate-400 group-hover:text-emerald-600 font-medium">发送 →</span>
                </div>
                <p class="text-slate-700 line-clamp-3 leading-relaxed group-hover:text-slate-900">{{ s.text }}</p>
              </button>
            </div>
          </div>

          <!-- 快捷操作工具条 -->
          <div class="flex items-center gap-2 mb-2 text-xs">
            <button
              @click="triggerGenerateSuggestions"
              :disabled="isGeneratingSuggestions"
              class="px-3 py-1 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200/80 hover:bg-emerald-100 font-medium transition flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            >
              <Sparkles class="w-3.5 h-3.5 stroke-[2]" />
              <span>{{ isGeneratingSuggestions ? '正在推演...' : '建议回复' }}</span>
            </button>

            <button
              @click="quickFill('好的，收到！')"
              class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200/70 text-slate-600 transition cursor-pointer text-xs"
            >
              好的
            </button>
            <button
              @click="quickFill('稍等一下，我手头处理完联系你~')"
              class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200/70 text-slate-600 transition cursor-pointer text-xs"
            >
              稍后联系
            </button>
            <button
              @click="quickFill('收到，辛苦啦！')"
              class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200/70 text-slate-600 transition cursor-pointer text-xs"
            >
              辛苦啦
            </button>

            <button @click="scrollToBottom(true)" class="ml-auto text-slate-400 hover:text-slate-600 cursor-pointer flex items-center gap-1 text-xs">
              <span>回到底部</span>
              <ArrowDown class="w-3 h-3 stroke-[2]" />
            </button>
          </div>

          <!-- 输入文本框与发送按钮 -->
          <div class="flex gap-2 items-end">
            <textarea
              v-model="inputContent"
              @keydown.enter="handleEnterKey"
              rows="2"
              placeholder="输入内容... (Enter 唤醒微信发送，Shift+Enter 换行)"
              class="flex-1 resize-none border-0 p-2 text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-0 leading-relaxed"
            ></textarea>
            <button
              @click="sendCurrentMessage"
              :disabled="isSending || !inputContent.trim()"
              class="h-10 px-5 rounded-xl bg-emerald-600 hover:bg-emerald-700 active:scale-[0.98] text-white font-medium text-xs transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-xs flex items-center gap-1.5 cursor-pointer"
            >
              <Send class="w-3.5 h-3.5 stroke-[2]" />
              <span>{{ isSending ? '发送中' : '发送' }}</span>
            </button>
          </div>
        </div>
      </div>
    </template>
  </main>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import {
  MessageSquare,
  ShieldCheck,
  Clock,
  Volume2,
  Sparkles,
  ArrowDown,
  Send,
  X,
} from 'lucide-vue-next'
import { api } from '@/api'

const props = defineProps({
  activeSession: { type: Object, default: () => null },
  messages: { type: Array, default: () => [] },
})

const emit = defineEmits(['toggle-whitelist', 'config-debounce', 'toast'])

const chatBodyRef = ref(null)
const inputContent = ref('')
const isSending = ref(false)
const showSuggestions = ref(false)
const isGeneratingSuggestions = ref(false)
const suggestions = ref([])

watch(
  () => props.messages.length,
  () => {
    nextTick(() => scrollToBottom(false))
  }
)

function scrollToBottom(smooth = true) {
  if (chatBodyRef.value) {
    chatBodyRef.value.scrollTo({
      top: chatBodyRef.value.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    })
  }
}

function handleEnterKey(e) {
  if (!e.shiftKey) {
    e.preventDefault()
    sendCurrentMessage()
  }
}

function quickFill(str) {
  inputContent.value = str
}

async function triggerGenerateSuggestions() {
  if (!props.activeSession) return
  isGeneratingSuggestions.value = true
  try {
    const lastMsg = props.messages[props.messages.length - 1]
    const text = lastMsg ? (lastMsg.text || lastMsg.content || '') : '在吗'
    const res = await api.generateSuggestions({
      chat_id: props.activeSession.username,
      text,
      sender_name: props.activeSession.title,
    })
    suggestions.value = res.data || []
    showSuggestions.value = true
  } catch (e) {
    emit('toast', '生成建议失败: ' + e.message)
  } finally {
    isGeneratingSuggestions.value = false
  }
}

async function applySuggestion(text) {
  inputContent.value = text
  showSuggestions.value = false
  await sendCurrentMessage()
}

async function sendCurrentMessage() {
  const text = inputContent.value.trim()
  if (!text || isSending.value) return

  isSending.value = true
  try {
    const res = await api.sendMessage({
      text,
      chat_id: props.activeSession.username,
      target_name: props.activeSession.title || props.activeSession.username,
      force_search: true,
    })
    if (res.code === 0) {
      inputContent.value = ''
      emit('toast', '已唤醒微信并成功发送！')
    }
  } catch (e) {
    emit('toast', '发送失败: ' + e.message)
  } finally {
    isSending.value = false
  }
}

function onImageError(e) {
  e.target.style.display = 'none'
}
</script>
