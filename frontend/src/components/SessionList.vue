<template>
  <section class="w-80 bg-slate-50/70 border-r border-slate-200/80 flex flex-col flex-shrink-0 select-none">
    <!-- 顶部搜索栏与账号标识 -->
    <div class="p-3.5 border-b border-slate-200/60 bg-white/40 backdrop-blur-xs space-y-2.5">
      <div class="relative flex items-center">
        <Search class="w-3.5 h-3.5 text-slate-400 absolute left-3 pointer-events-none stroke-[1.8]" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索联系人、群聊..."
          class="w-full bg-slate-100/90 hover:bg-slate-100 text-xs text-slate-800 placeholder-slate-400 rounded-lg pl-8 pr-7 py-2 border border-slate-200/70 focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition-all"
        />
        <button
          v-if="searchQuery"
          @click="searchQuery = ''"
          class="absolute right-2.5 text-slate-400 hover:text-slate-600 p-0.5 text-xs cursor-pointer"
        >
          <X class="w-3 h-3" />
        </button>
      </div>

      <!-- 账号微标签 -->
      <div class="flex items-center justify-between text-[11px] text-slate-500 px-1 font-medium">
        <span class="flex items-center gap-1.5 truncate">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          <span class="truncate">{{ currentAccount?.name || currentAccount?.wxid || '微信账号' }}</span>
        </span>
        <span class="text-[10px] text-slate-400 font-mono">{{ filteredSessions.length }} 会话</span>
      </div>
    </div>

    <!-- 会话列表 -->
    <div class="flex-1 overflow-y-auto divide-y divide-slate-100/80 px-2 py-2 space-y-0.5">
      <div
        v-for="s in filteredSessions"
        :key="s.username"
        @click="$emit('select', s)"
        :class="[
          'px-3 py-2.5 rounded-xl flex items-center gap-3 cursor-pointer transition-all duration-150 relative group',
          activeSession?.username === s.username
            ? 'bg-white shadow-[0_1px_3px_rgba(0,0,0,0.06)] ring-1 ring-slate-200/80'
            : 'hover:bg-slate-200/40'
        ]"
      >
        <!-- 头像 -->
        <div
          :class="[
            'w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center font-medium text-xs shadow-2xs ring-1 ring-black/5',
            s.is_group
              ? 'bg-gradient-to-br from-slate-600 to-slate-800 text-white'
              : 'bg-gradient-to-br from-emerald-50 to-emerald-100 text-emerald-800 border border-emerald-200/50'
          ]"
        >
          {{ (s.title || '聊').slice(0, 1) }}
        </div>

        <!-- 文本详情 -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center justify-between mb-1">
            <span
              :class="[
                'text-xs font-semibold truncate',
                activeSession?.username === s.username ? 'text-slate-900' : 'text-slate-700'
              ]"
            >
              {{ s.title || s.username }}
            </span>
            <span class="text-[10px] text-slate-400 font-mono flex-shrink-0">{{ formatTime(s.last_time) }}</span>
          </div>

          <div class="flex items-center justify-between text-[11px] text-slate-500">
            <span class="truncate flex-1 pr-1.5">{{ s.summary || '暂无消息' }}</span>
            <span
              v-if="s.in_whitelist || s.auto_reply"
              class="flex-shrink-0 inline-flex items-center gap-0.5 text-[10px] bg-emerald-50 text-emerald-700 font-medium px-1.5 py-0.5 rounded-md ring-1 ring-emerald-600/15"
              title="已纳入智能托管白名单"
            >
              <ShieldCheck class="w-2.5 h-2.5 stroke-[2]" />
              <span>托管</span>
            </span>
          </div>
        </div>
      </div>

      <div v-if="filteredSessions.length === 0" class="p-8 text-center text-xs text-slate-400">
        无匹配联系人或群聊
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Search, X, ShieldCheck } from 'lucide-vue-next'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeSession: { type: Object, default: () => null },
  currentAccount: { type: Object, default: () => null },
})

defineEmits(['select'])

const searchQuery = ref('')

const filteredSessions = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return props.sessions
  return props.sessions.filter(s => (s.title || '').toLowerCase().includes(q))
})

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return `${d.getMonth() + 1}/${d.getDate()}`
}
</script>
