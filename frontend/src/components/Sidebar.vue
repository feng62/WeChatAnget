<template>
  <aside class="w-16 bg-[#16181d] flex flex-col items-center py-5 justify-between border-r border-slate-800/60 flex-shrink-0 select-none z-10">
    <!-- 顶部头像与主导航 -->
    <div class="flex flex-col items-center space-y-6 w-full">
      <!-- 账号头像 -->
      <div class="relative group cursor-pointer" :title="currentAccount?.name || '微信账号'">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 text-white flex items-center justify-center font-semibold text-sm shadow-sm ring-1 ring-white/10 group-hover:ring-white/20 transition">
          {{ (currentAccount?.name || '微').slice(0, 1) }}
        </div>
        <div
          class="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-500 border-2 border-[#16181d] shadow-xs"
          title="账号在线已挂载"
        ></div>
      </div>

      <!-- 垂直导航项 -->
      <nav class="flex flex-col space-y-2 w-full px-2.5">
        <button
          v-for="item in navItems"
          :key="item.id"
          @click="$emit('update:activeTab', item.id)"
          :class="[
            'relative w-full h-11 rounded-xl flex items-center justify-center transition-all duration-150 group cursor-pointer',
            activeTab === item.id
              ? 'bg-slate-800/80 text-emerald-400 shadow-inner'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          ]"
          :title="item.title"
        >
          <!-- Active Indicator Pill on the left -->
          <div
            v-if="activeTab === item.id"
            class="absolute left-0 top-2.5 bottom-2.5 w-1 rounded-r-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]"
          ></div>
          <component :is="item.icon" class="w-[18px] h-[18px] stroke-[1.6]" />
        </button>
      </nav>
    </div>

    <!-- 底部状态指示灯 -->
    <div class="flex flex-col items-center">
      <div
        :class="[
          'w-2 h-2 rounded-full transition-all duration-300',
          isOnline
            ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]'
            : 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]'
        ]"
        :title="isOnline ? '实时增量数据同步已就绪' : '数据连接断开重试中...'"
      ></div>
    </div>
  </aside>
</template>

<script setup>
import {
  MessageSquare,
  SlidersHorizontal,
  Bot,
  BrainCircuit,
  ShieldCheck,
} from 'lucide-vue-next'

defineProps({
  activeTab: { type: String, default: 'chat' },
  currentAccount: { type: Object, default: () => null },
  isOnline: { type: Boolean, default: true }
})

defineEmits(['update:activeTab'])

const navItems = [
  { id: 'chat', title: '会话与消息监控', icon: MessageSquare },
  { id: 'config', title: 'AI 引擎与自动化配置', icon: SlidersHorizontal },
  { id: 'persona', title: '角色人设设计器', icon: Bot },
  { id: 'memory', title: '双层记忆架构中心', icon: BrainCircuit },
  { id: 'whitelist', title: '智能托管白名单', icon: ShieldCheck },
]
</script>
