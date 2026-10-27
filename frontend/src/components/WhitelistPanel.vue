<template>
  <div class="flex-1 bg-slate-50/60 overflow-y-auto p-8 select-none">
    <div class="max-w-5xl mx-auto space-y-6">
      <!-- 顶部 Header 卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs flex items-center justify-between">
        <div class="flex items-center gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 flex items-center justify-center text-emerald-600">
            <ShieldCheck class="w-5 h-5" :stroke-width="1.8" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-slate-900 tracking-tight">自动回复白名单与自动化托管</h2>
            <p class="text-xs text-slate-500 mt-0.5">仅对名单内对象执行全自动微信挂起唤醒、精确搜索定位与智能回复（群聊无需 @ 也自动回复）</p>
          </div>
        </div>

        <div class="flex items-center gap-4">
          <ToggleSwitch
            v-model="isEnabled"
            @update:modelValue="onToggleWhitelist"
            label="白名单托管总开关"
          />
          <div class="h-4 w-px bg-slate-200"></div>
          <button
            @click="loadWhitelist"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-medium transition cursor-pointer"
          >
            <RefreshCw class="w-3.5 h-3.5 text-slate-500" :stroke-width="1.8" />
            <span>刷新</span>
          </button>
        </div>
      </div>

      <!-- 快速添加卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs">
        <div class="flex items-center gap-2 mb-3">
          <UserPlus class="w-4 h-4 text-emerald-600" :stroke-width="1.8" />
          <h3 class="text-xs font-semibold text-slate-800 tracking-tight">快速添加托管对象</h3>
        </div>

        <div class="flex flex-wrap gap-2.5 items-center">
          <input
            v-model="inputTarget"
            @keydown.enter="addManual"
            type="text"
            placeholder="输入微信ID、备注名或群聊准确名称..."
            class="flex-1 min-w-[260px] bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all"
          />

          <select
            v-model="inputType"
            class="bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-700 focus:outline-none focus:border-emerald-500 shadow-xs"
          >
            <option value="friend">好友私聊</option>
            <option value="group">微信群聊</option>
          </select>

          <button
            @click="addManual"
            class="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium cursor-pointer transition shadow-xs active:scale-[0.98]"
          >
            <Plus class="w-3.5 h-3.5" :stroke-width="2" />
            <span>添加至白名单</span>
          </button>
        </div>

        <div class="flex items-center gap-1.5 mt-3 text-[11px] text-slate-400">
          <Info class="w-3.5 h-3.5 flex-shrink-0" :stroke-width="1.8" />
          <span>快捷提示：在左侧「会话监控」列表中选中任意聊天，在对话框顶部右上角也可一键开启/关闭白名单托管。</span>
        </div>
      </div>

      <!-- 白名单生效列表 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs">
        <div class="flex items-center justify-between pb-4 mb-4 border-b border-slate-100">
          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold text-slate-800 tracking-tight">当前生效白名单</span>
            <span class="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">
              {{ list.length }} 个对象
            </span>
          </div>

          <span v-if="!isEnabled" class="text-[11px] text-amber-600 font-medium">
            (当前全局开关已关闭，白名单暂不生效)
          </span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <div
            v-for="item in list"
            :key="item.chat_id"
            class="p-3.5 rounded-xl border border-slate-200/80 bg-white hover:border-slate-300 hover:shadow-xs transition-all flex items-center justify-between group"
          >
            <div class="flex items-center gap-3 min-w-0 pr-2">
              <div
                :class="[
                  'w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0',
                  (item.is_group || String(item.chat_id).endsWith('@chatroom'))
                    ? 'bg-blue-50 text-blue-600 border border-blue-100'
                    : 'bg-emerald-50 text-emerald-600 border border-emerald-100'
                ]"
              >
                <Users v-if="(item.is_group || String(item.chat_id).endsWith('@chatroom'))" class="w-4 h-4" :stroke-width="1.8" />
                <User v-else class="w-4 h-4" :stroke-width="1.8" />
              </div>

              <div class="min-w-0">
                <div class="flex items-center gap-1.5">
                  <span class="font-semibold text-xs text-slate-900 truncate">{{ item.name || item.chat_id }}</span>
                  <span
                    :class="[
                      'text-[10px] px-1.5 py-0.2 rounded font-medium flex-shrink-0',
                      (item.is_group || String(item.chat_id).endsWith('@chatroom'))
                        ? 'bg-blue-50 text-blue-700'
                        : 'bg-emerald-50 text-emerald-700'
                    ]"
                  >
                    {{ (item.is_group || String(item.chat_id).endsWith('@chatroom')) ? '群聊' : '私聊' }}
                  </span>
                </div>
                <div class="text-[10px] text-slate-400 font-mono truncate mt-0.5">{{ item.chat_id }}</div>
              </div>
            </div>

            <button
              @click="removeItem(item.chat_id)"
              class="text-xs text-slate-400 hover:text-rose-600 font-medium px-2 py-1 rounded-md hover:bg-rose-50 transition cursor-pointer flex-shrink-0 opacity-60 group-hover:opacity-100 flex items-center gap-1"
              title="移出白名单"
            >
              <Trash2 class="w-3.5 h-3.5" :stroke-width="1.8" />
              <span>移除</span>
            </button>
          </div>
        </div>

        <div v-if="list.length === 0" class="py-14 flex flex-col items-center justify-center text-center text-slate-400">
          <ShieldAlert class="w-8 h-8 text-slate-300 mb-2 stroke-1" />
          <p class="text-xs">暂无白名单托管对象</p>
          <p class="text-[10px] text-slate-400 mt-1">请在上方输入好友/群名称添加，或在左侧会话详情中直接开启</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  ShieldCheck,
  ShieldAlert,
  UserPlus,
  RefreshCw,
  Plus,
  Info,
  Users,
  User,
  Trash2
} from 'lucide-vue-next'
import ToggleSwitch from './common/ToggleSwitch.vue'
import { api } from '@/api'

const emit = defineEmits(['toast', 'refresh-sessions'])

const isEnabled = ref(true)
const list = ref([])
const inputTarget = ref('')
const inputType = ref('friend')

onMounted(async () => {
  await loadWhitelist()
})

async function loadWhitelist() {
  try {
    const res = await api.getWhitelist()
    isEnabled.value = !!res.enabled
    list.value = res.list || []
  } catch (e) {
    emit('toast', '加载白名单失败: ' + e.message)
  }
}

async function onToggleWhitelist() {
  try {
    await api.toggleWhitelist(isEnabled.value)
    emit('toast', isEnabled.value ? '白名单自动托管已开启' : '白名单自动托管已暂停')
  } catch (e) {
    emit('toast', '切换状态失败: ' + e.message)
  }
}

async function addManual() {
  const t = inputTarget.value.trim()
  if (!t) {
    emit('toast', '请输入微信号、备注名或群名称')
    return
  }
  try {
    const res = await api.addWhitelist({
      chat_id: t,
      name: t,
      is_group: inputType.value === 'group',
    })
    if (res.code === 0) {
      inputTarget.value = ''
      emit('toast', '已成功添加到白名单！')
      await loadWhitelist()
      emit('refresh-sessions')
    }
  } catch (e) {
    emit('toast', '添加失败: ' + e.message)
  }
}

async function removeItem(chatId) {
  try {
    const res = await api.deleteWhitelist(chatId)
    if (res.code === 0) {
      emit('toast', '已从白名单移除')
      await loadWhitelist()
      emit('refresh-sessions')
    }
  } catch (e) {
    emit('toast', '移除失败: ' + e.message)
  }
}
</script>
