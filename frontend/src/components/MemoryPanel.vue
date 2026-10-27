<template>
  <div class="flex-1 bg-slate-50/60 overflow-y-auto p-8 select-none">
    <div class="max-w-5xl mx-auto space-y-6">
      <!-- 顶部 Header 卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs flex items-center justify-between">
        <div class="flex items-center gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 flex items-center justify-center text-emerald-600">
            <BrainCircuit class="w-5 h-5" :stroke-width="1.8" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-slate-900 tracking-tight">双层记忆架构中心</h2>
            <p class="text-xs text-slate-500 mt-0.5">全局事实跨所有会话共享；专属记忆针对特定联系人单独记录，AI 在对话时自动唤醒融合</p>
          </div>
        </div>

        <button
          @click="refreshAllMemories"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-medium transition cursor-pointer"
        >
          <RefreshCw class="w-3.5 h-3.5 text-slate-500" :stroke-width="1.8" />
          <span>刷新记忆</span>
        </button>
      </div>

      <!-- 双栏记忆布局 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch">
        <!-- 左栏：整体全局共享记忆 -->
        <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs flex flex-col h-[560px]">
          <div class="flex items-center justify-between pb-3.5 mb-2 border-b border-slate-100">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center text-slate-700">
                <Globe class="w-4 h-4" :stroke-width="1.8" />
              </div>
              <span class="font-semibold text-xs text-slate-900 tracking-tight">全局共享记忆库</span>
            </div>
            <span class="text-[11px] font-mono px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200/60">
              {{ globalFacts.length }} 条事实
            </span>
          </div>

          <p class="text-[11px] text-slate-500 leading-relaxed mb-3">
            跨所有好友及群聊通用的主客体核心事实（如主人的职业、兴趣嗜好、日常时间表等）：
          </p>

          <div class="flex-1 overflow-y-auto space-y-2 mb-3 pr-1 scrollbar-thin">
            <div
              v-for="(f, idx) in globalFacts"
              :key="idx"
              class="p-3 bg-slate-50/70 hover:bg-slate-50 rounded-xl border border-slate-200/70 flex items-start justify-between gap-2.5 transition group"
            >
              <div class="flex items-start gap-2 min-w-0">
                <Bookmark class="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" :stroke-width="1.8" />
                <span class="text-xs text-slate-800 leading-relaxed select-text">{{ f }}</span>
              </div>
              <button
                @click="removeGlobalFact(idx)"
                class="text-slate-300 hover:text-rose-500 opacity-60 group-hover:opacity-100 transition p-1 cursor-pointer flex-shrink-0 rounded"
                title="删除该事实"
              >
                <Trash2 class="w-3.5 h-3.5" :stroke-width="1.8" />
              </button>
            </div>

            <div v-if="globalFacts.length === 0" class="h-48 flex flex-col items-center justify-center text-center text-slate-400">
              <Globe class="w-8 h-8 text-slate-300 mb-2 stroke-1" />
              <p class="text-xs">暂无全局事实</p>
              <p class="text-[10px] text-slate-400 mt-1">在下方输入框添加第一条全局事实</p>
            </div>
          </div>

          <div class="pt-3 border-t border-slate-100 flex gap-2">
            <input
              v-model="newGlobalFact"
              @keydown.enter="addGlobalFact"
              type="text"
              placeholder="新增一条全局事实 (例如: 我平时喜欢喝乌龙茶)"
              class="flex-1 bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all"
            />
            <button
              @click="addGlobalFact"
              class="flex items-center gap-1 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium cursor-pointer transition shadow-xs active:scale-[0.98]"
            >
              <Plus class="w-3.5 h-3.5" :stroke-width="2" />
              <span>添加</span>
            </button>
          </div>
        </div>

        <!-- 右栏：单会话专属记忆画像 -->
        <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs flex flex-col h-[560px]">
          <div class="flex items-center justify-between pb-3.5 mb-2 border-b border-slate-100 gap-2">
            <div class="flex items-center gap-2 min-w-0">
              <div class="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center text-slate-700 flex-shrink-0">
                <User class="w-4 h-4" :stroke-width="1.8" />
              </div>
              <span class="font-semibold text-xs text-slate-900 tracking-tight truncate">联系人专属记忆画像</span>
            </div>

            <select
              v-model="selectedChatId"
              @change="onSessionChange"
              class="border border-slate-200/90 rounded-lg px-2.5 py-1.5 bg-slate-50 text-xs text-slate-800 max-w-[170px] truncate focus:outline-none focus:border-emerald-500"
            >
              <option v-for="s in sessions" :key="s.username" :value="s.username">
                {{ s.title || s.username }}
              </option>
            </select>
          </div>

          <p class="text-[11px] text-slate-500 leading-relaxed mb-3">
            记录当前选定对象的独立画像标签（AI 在多轮对话中会优先融入这些个性化信息）：
          </p>

          <div class="flex-1 overflow-y-auto space-y-2 mb-3 pr-1 scrollbar-thin">
            <div
              v-for="(n, idx) in sessionNotes"
              :key="idx"
              class="p-3 bg-slate-50/70 hover:bg-slate-50 rounded-xl border border-slate-200/70 flex items-start justify-between gap-2.5 transition group"
            >
              <div class="flex items-start gap-2 min-w-0">
                <Tag class="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" :stroke-width="1.8" />
                <span class="text-xs text-slate-800 leading-relaxed select-text">{{ n }}</span>
              </div>
              <button
                @click="removeSessionNote(idx)"
                class="text-slate-300 hover:text-rose-500 opacity-60 group-hover:opacity-100 transition p-1 cursor-pointer flex-shrink-0 rounded"
                title="删除该标签"
              >
                <Trash2 class="w-3.5 h-3.5" :stroke-width="1.8" />
              </button>
            </div>

            <div v-if="sessionNotes.length === 0" class="h-48 flex flex-col items-center justify-center text-center text-slate-400">
              <Tag class="w-8 h-8 text-slate-300 mb-2 stroke-1" />
              <p class="text-xs">该会话暂无专属画像标签</p>
              <p class="text-[10px] text-slate-400 mt-1">可随时在下方输入框添加专属记忆</p>
            </div>
          </div>

          <div class="pt-3 border-t border-slate-100 flex gap-2">
            <input
              v-model="newSessionNote"
              @keydown.enter="addSessionNote"
              type="text"
              placeholder="添加专属记忆标签 (例如: 对方生日在5月、喜欢猫)"
              class="flex-1 bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all"
            />
            <button
              @click="addSessionNote"
              class="flex items-center gap-1 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium cursor-pointer transition shadow-xs active:scale-[0.98]"
            >
              <Plus class="w-3.5 h-3.5" :stroke-width="2" />
              <span>添加</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  BrainCircuit,
  Globe,
  User,
  Bookmark,
  Tag,
  Trash2,
  Plus,
  RefreshCw
} from 'lucide-vue-next'
import { api } from '@/api'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
})

const emit = defineEmits(['toast'])

const globalFacts = ref([])
const newGlobalFact = ref('')

const selectedChatId = ref('')
const sessionNotes = ref([])
const newSessionNote = ref('')

onMounted(async () => {
  await loadGlobalMemory()
  if (props.sessions.length > 0) {
    selectedChatId.value = props.sessions[0].username
    await loadSessionMemory(selectedChatId.value)
  }
})

async function refreshAllMemories() {
  await loadGlobalMemory()
  if (selectedChatId.value) {
    await loadSessionMemory(selectedChatId.value)
  }
  emit('toast', '记忆数据已刷新')
}

async function loadGlobalMemory() {
  try {
    const res = await api.getGlobalMemory()
    globalFacts.value = res.data?.facts || []
  } catch (e) {
    emit('toast', '加载全局记忆失败: ' + e.message)
  }
}

async function addGlobalFact() {
  const f = newGlobalFact.value.trim()
  if (!f) return
  try {
    await api.saveGlobalMemory({ fact: f })
    newGlobalFact.value = ''
    await loadGlobalMemory()
    emit('toast', '全局事实已成功追加！')
  } catch (e) {
    emit('toast', '添加失败: ' + e.message)
  }
}

async function removeGlobalFact(index) {
  try {
    await api.deleteGlobalFact(index)
    await loadGlobalMemory()
    emit('toast', '已删除该全局记忆')
  } catch (e) {
    emit('toast', '删除失败: ' + e.message)
  }
}

async function onSessionChange() {
  if (selectedChatId.value) {
    await loadSessionMemory(selectedChatId.value)
  }
}

async function loadSessionMemory(chatId) {
  try {
    const res = await api.getSessionMemory(chatId)
    sessionNotes.value = res.data?.notes || []
  } catch (e) {
    console.error('加载专属记忆失败:', e)
  }
}

async function addSessionNote() {
  const note = newSessionNote.value.trim()
  if (!note || !selectedChatId.value) return
  try {
    await api.addSessionNote({ chat_id: selectedChatId.value, note })
    newSessionNote.value = ''
    await loadSessionMemory(selectedChatId.value)
    emit('toast', '专属标签添加成功！')
  } catch (e) {
    emit('toast', '添加标签失败: ' + e.message)
  }
}

async function removeSessionNote(index) {
  if (!selectedChatId.value) return
  try {
    await api.deleteSessionNote(selectedChatId.value, index)
    await loadSessionMemory(selectedChatId.value)
    emit('toast', '已删除该标签')
  } catch (e) {
    emit('toast', '删除失败: ' + e.message)
  }
}
</script>
