<template>
  <div class="flex-1 bg-[#f8fafc] overflow-y-auto p-8 select-none">
    <div class="max-w-3xl mx-auto space-y-6">
      <!-- 顶部 Header 卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-6 flex items-center justify-between">
        <div>
          <div class="flex items-center gap-2">
            <SlidersHorizontal class="w-5 h-5 text-emerald-600 stroke-[1.8]" />
            <h2 class="text-base font-bold text-slate-900 tracking-tight">AI 引擎与自动化策略设置</h2>
          </div>
          <p class="text-xs text-slate-500 mt-1">配置大语言模型服务商接口、串行防刷聚合机制与分条连续气泡发送策略</p>
        </div>
        <button
          @click="saveConfig"
          :disabled="isSaving"
          class="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 active:scale-[0.98] text-white text-xs font-semibold shadow-xs transition-all disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
        >
          <Check class="w-3.5 h-3.5 stroke-[2.2]" />
          <span>{{ isSaving ? '保存中...' : '保存配置' }}</span>
        </button>
      </div>

      <!-- 核心模型接入卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-6 space-y-5 text-xs text-slate-700">
        <h3 class="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
          <Bot class="w-4 h-4 text-slate-400 stroke-[1.8]" />
          <span>模型端点配置 (OpenAI 兼容协议)</span>
        </h3>

        <!-- 服务商预设 -->
        <div>
          <label class="block font-medium text-slate-700 mb-1.5">服务商快捷预设 (Provider)</label>
          <select
            v-model="cfg.provider"
            @change="onProviderChange"
            class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
          >
            <option value="deepseek">DeepSeek (深度求索官方)</option>
            <option value="qwen">通义千问 (DashScope / SiliconFlow)</option>
            <option value="kimi">月之暗面 (Moonshot / Kimi)</option>
            <option value="ollama">Ollama (本地私有化部署)</option>
            <option value="custom">自定义兼容接口</option>
          </select>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- Base URL -->
          <div>
            <label class="block font-medium text-slate-700 mb-1.5">API 根地址 (Base URL)</label>
            <input
              v-model="cfg.base_url"
              type="text"
              placeholder="https://api.deepseek.com/v1"
              class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
            />
          </div>

          <!-- Model Name -->
          <div>
            <label class="block font-medium text-slate-700 mb-1.5">模型名称 (Model)</label>
            <input
              v-model="cfg.model"
              type="text"
              placeholder="deepseek-chat"
              class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
            />
          </div>
        </div>

        <!-- API Key -->
        <div>
          <label class="block font-medium text-slate-700 mb-1.5">API Key (密钥)</label>
          <input
            v-model="cfg.api_key"
            type="password"
            placeholder="sk-..."
            class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
          />
          <span class="text-[11px] text-slate-400 mt-1 block">本地部署免密模型可留空；已采用掩码保护</span>
        </div>

        <!-- 测试连通性按钮 -->
        <div class="flex items-center gap-3 pt-2">
          <button
            @click="testConnection"
            :disabled="isTesting"
            class="px-4 py-2 rounded-xl bg-slate-100 hover:bg-slate-200/80 active:scale-[0.98] border border-slate-200 text-slate-700 font-medium transition cursor-pointer flex items-center gap-1.5"
          >
            <Sparkles class="w-3.5 h-3.5 text-emerald-600 stroke-[2]" />
            <span>{{ isTesting ? '测试中...' : '测试接口连通性' }}</span>
          </button>
          <span v-if="testResult" :class="['font-medium text-[11px]', testSuccess ? 'text-emerald-600' : 'text-rose-500']">
            {{ testResult }}
          </span>
        </div>
      </div>

      <!-- 自动化开关与上下文卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-6 space-y-5 text-xs text-slate-700">
        <h3 class="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
          <Sliders class="w-4 h-4 text-slate-400 stroke-[1.8]" />
          <span>托管回复与上下文感知</span>
        </h3>

        <!-- 开关项 1 -->
        <div class="flex items-center justify-between py-2 border-b border-slate-100">
          <div>
            <div class="font-semibold text-slate-900">全局自动托管回复总开关</div>
            <div class="text-[11px] text-slate-400 mt-0.5">开启后，被勾选了「白名单托管」的联系人收到消息时，将自动调用 AI 代发回复</div>
          </div>
          <ToggleSwitch v-model="cfg.auto_reply_global" />
        </div>

        <!-- 开关项 2 -->
        <div class="flex items-center justify-between py-2 border-b border-slate-100">
          <div>
            <div class="font-semibold text-slate-900">非白名单普通群聊仅在被 @ 时回复</div>
            <div class="text-[11px] text-slate-400 mt-0.5">白名单内的群聊不受此约束，无论是否被 @ 均自动接话</div>
          </div>
          <ToggleSwitch v-model="cfg.group_at_only" />
        </div>

        <!-- 上下文参考滑动条 -->
        <div class="pt-2">
          <div class="flex justify-between items-center mb-2">
            <div>
              <span class="font-semibold text-slate-900">对话上下文参考条数</span>
              <span class="text-[11px] text-slate-400 ml-2">结合微信真实本地记录推理，防断章取义</span>
            </div>
            <span class="font-bold text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-md ring-1 ring-emerald-600/20 font-mono">
              {{ cfg.context_messages_count }} 条
            </span>
          </div>
          <input
            v-model.number="cfg.context_messages_count"
            type="range"
            min="5"
            max="30"
            class="w-full accent-emerald-600 cursor-pointer"
          />
        </div>
      </div>

      <!-- 消息池聚合防刷与分条发送卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-6 space-y-6 text-xs text-slate-700">
        <h3 class="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
          <Clock class="w-4 h-4 text-slate-400 stroke-[1.8]" />
          <span>消息池聚合防刷 (Debounce) 与分条发送</span>
        </h3>

        <!-- 防刷聚合等待时间 -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div>
            <label class="block font-medium text-slate-700 mb-1">私聊多消息聚合等待时间 (秒)</label>
            <input
              v-model.number="cfg.private_debounce_sec"
              type="number"
              step="0.5"
              min="0.5"
              class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500"
            />
            <span class="text-[11px] text-slate-400 mt-1 block">私聊连发多句时，等待静默期结束合并回复一次 (默认 3s)</span>
          </div>

          <div>
            <label class="block font-medium text-slate-700 mb-1">群聊多人连发聚合等待时间 (秒)</label>
            <input
              v-model.number="cfg.group_debounce_sec"
              type="number"
              step="1"
              min="1"
              class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500"
            />
            <span class="text-[11px] text-slate-400 mt-1 block">群里多人连续发消息时，合并等待结束统一回复一次 (默认 6s)</span>
          </div>
        </div>

        <div class="border-t border-slate-100 pt-4 space-y-4">
          <!-- 分条发送开关 -->
          <div class="flex items-center justify-between">
            <div>
              <div class="font-semibold text-slate-900">开启长消息智能切分多条发送</div>
              <div class="text-[11px] text-slate-400 mt-0.5">按自然句式标点拆分为 1~N 条气泡，带打字停顿，告别生硬长篇大论</div>
            </div>
            <ToggleSwitch v-model="cfg.multi_bubble_enabled" />
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-5 pt-1">
            <div>
              <label class="block font-medium text-slate-700 mb-1">单次回复最大分条数</label>
              <select
                v-model.number="cfg.max_bubbles_count"
                class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500"
              >
                <option :value="1">1 条 (单气泡完整发送)</option>
                <option :value="2">2 条 (自然分段推荐)</option>
                <option :value="3">3 条 (短句连发)</option>
                <option :value="4">4 条</option>
              </select>
            </div>

            <div>
              <label class="block font-medium text-slate-700 mb-1">多条气泡发送间隔 (毫秒)</label>
              <input
                v-model.number="cfg.bubble_send_interval_ms"
                type="number"
                step="100"
                min="300"
                class="w-full border border-slate-200 rounded-xl px-3 py-2 bg-slate-50/50 text-xs focus:outline-none focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500"
              />
              <span class="text-[11px] text-slate-400 mt-1 block">模拟真人打字停顿间隔，默认 800ms</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  SlidersHorizontal,
  Bot,
  Sliders,
  Clock,
  Sparkles,
  Check,
} from 'lucide-vue-next'
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import { api } from '@/api'

const emit = defineEmits(['toast'])

const cfg = ref({
  provider: 'deepseek',
  base_url: 'https://api.deepseek.com/v1',
  api_key: '',
  model: 'deepseek-chat',
  auto_reply_global: true,
  group_at_only: false,
  reply_cooldown_sec: 3,
  context_messages_count: 15,
  search_before_send: true,
  search_delay_ms: 400,
  private_debounce_sec: 3.0,
  group_debounce_sec: 6.0,
  multi_bubble_enabled: true,
  max_bubbles_count: 2,
  bubble_send_interval_ms: 800,
})

const isSaving = ref(false)
const isTesting = ref(false)
const testResult = ref('')
const testSuccess = ref(false)

onMounted(async () => {
  try {
    const res = await api.getAiConfig()
    if (res.config) {
      cfg.value = { ...cfg.value, ...res.config }
    }
  } catch (e) {
    emit('toast', '加载模型配置失败: ' + e.message)
  }
})

function onProviderChange() {
  const p = cfg.value.provider
  if (p === 'deepseek') {
    cfg.value.base_url = 'https://api.deepseek.com/v1'
    cfg.value.model = 'deepseek-chat'
  } else if (p === 'qwen') {
    cfg.value.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    cfg.value.model = 'qwen-plus'
  } else if (p === 'kimi') {
    cfg.value.base_url = 'https://api.moonshot.cn/v1'
    cfg.value.model = 'moonshot-v1-8k'
  } else if (p === 'ollama') {
    cfg.value.base_url = 'http://127.0.0.1:11434/v1'
    cfg.value.model = 'qwen2.5:7b'
  }
}

async function testConnection() {
  isTesting.value = true
  testResult.value = '正在测试连接...'
  testSuccess.value = false
  try {
    const res = await api.testAiConnection()
    testResult.value = res.message
    testSuccess.value = res.code === 0
  } catch (e) {
    testResult.value = '接口连接失败: ' + e.message
    testSuccess.value = false
  } finally {
    isTesting.value = false
  }
}

async function saveConfig() {
  isSaving.value = true
  try {
    const res = await api.saveAiConfig(cfg.value)
    if (res.code === 0) {
      emit('toast', '配置已保存成功！')
    }
  } catch (e) {
    emit('toast', '保存失败: ' + e.message)
  } finally {
    isSaving.value = false
  }
}
</script>
