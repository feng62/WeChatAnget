<template>
  <div class="flex-1 bg-slate-50/60 overflow-y-auto p-8 select-none">
    <div class="max-w-5xl mx-auto space-y-6">
      <!-- 顶部 Header 卡片 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs flex items-center justify-between">
        <div class="flex items-center gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 flex items-center justify-center text-emerald-600">
            <Sparkles class="w-5 h-5" :stroke-width="1.8" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-slate-900 tracking-tight">性格设计与专属人设定制</h2>
            <p class="text-xs text-slate-500 mt-0.5">选择预设模板或为 AI 注入符合自然微信日常对话风格的说话语气与行为守则</p>
          </div>
        </div>

        <button
          @click="savePersona"
          :disabled="isSaving"
          class="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium shadow-xs transition-all active:scale-[0.98] disabled:opacity-50 cursor-pointer"
        >
          <Check v-if="!isSaving" class="w-3.5 h-3.5" :stroke-width="2" />
          <span>{{ isSaving ? '保存中...' : '保存人设配置' }}</span>
        </button>
      </div>

      <!-- 预设性格模板网格 -->
      <div class="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs">
        <div class="flex items-center justify-between mb-3.5">
          <label class="text-xs font-semibold text-slate-800 tracking-tight flex items-center gap-1.5">
            <span>快速套用人设模板</span>
            <span class="text-[10px] font-normal text-slate-400">（点击即可填充下列参数）</span>
          </label>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div
            v-for="(p, pid) in presets"
            :key="pid"
            @click="applyPreset(pid, p)"
            :class="[
              'p-4 rounded-xl border cursor-pointer transition-all flex flex-col justify-between text-left group',
              persona.preset_id === pid
                ? 'border-emerald-500 bg-emerald-50/30 ring-1 ring-emerald-500/20 shadow-xs'
                : 'border-slate-200/90 bg-white hover:border-slate-300 hover:bg-slate-50/50'
            ]"
          >
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <span class="font-semibold text-xs text-slate-900 group-hover:text-emerald-700 transition-colors">
                  {{ p.title }}
                </span>
                <span
                  v-if="persona.preset_id === pid"
                  class="flex items-center gap-0.5 text-[10px] font-medium text-emerald-600 bg-emerald-100/70 px-1.5 py-0.5 rounded-full"
                >
                  <Check class="w-2.5 h-2.5" :stroke-width="2.5" />
                  <span>使用中</span>
                </span>
              </div>
              <p class="text-[11px] text-slate-500 leading-relaxed line-clamp-3">{{ p.description }}</p>
            </div>

            <div class="mt-3 pt-2.5 border-t border-slate-100 flex items-center justify-between text-[10px] text-slate-400">
              <span>{{ p.job || '微信助理' }}</span>
              <span class="text-emerald-600 font-medium group-hover:translate-x-0.5 transition-transform">套用模板 →</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 参数配置与实时渲染 -->
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <!-- 左侧：表单配置 -->
        <div class="lg:col-span-7 bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs space-y-4">
          <div class="grid grid-cols-2 gap-3.5">
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1.5">AI 名字 / 称呼</label>
              <input
                v-model="persona.name"
                type="text"
                placeholder="例如：小暖、小助手"
                class="w-full bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all"
              />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1.5">职业 / 身份设定</label>
              <input
                v-model="persona.job"
                type="text"
                placeholder="例如：自由撰稿人、项目经理"
                class="w-full bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all"
              />
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1.5">性格特质与沟通语气</label>
            <textarea
              v-model="persona.personality"
              rows="2"
              placeholder="例如：细腻、真诚、包容、讲话自然松弛..."
              class="w-full bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all resize-none"
            ></textarea>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1.5">经历与生活背景</label>
            <textarea
              v-model="persona.background"
              rows="2"
              placeholder="例如：喜欢在阳光温暖的午后画画、平时爱喝茶..."
              class="w-full bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all resize-none"
            ></textarea>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1.5">常用口头禅 / 口癖习惯 (顿号或逗号分隔)</label>
            <input
              v-model="persona.catchphrases"
              type="text"
              placeholder="例如：好嘞、抱抱你、没关系慢慢来、听我的准没错~"
              class="w-full bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all"
            />
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1.5">单条回复最大字数限制</label>
            <div class="flex items-center gap-2">
              <input
                v-model.number="persona.max_words"
                type="number"
                min="30"
                max="500"
                class="w-32 bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all"
              />
              <span class="text-xs text-slate-400">字（超出部分会自动智能切分为多条气泡发送）</span>
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1.5">自定义额外 System Prompt 约束 (可选)</label>
            <textarea
              v-model="persona.custom_prompt"
              rows="3"
              placeholder="例如：遇到打听隐私的提问委婉转移话题，多用提问引导对方多分享..."
              class="w-full bg-white border border-slate-200/90 rounded-lg px-3 py-2 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 shadow-xs transition-all resize-none"
            ></textarea>
          </div>
        </div>

        <!-- 右侧：实时 System Prompt 渲染预览 (Linear Code/Terminal Surface) -->
        <div class="lg:col-span-5 bg-slate-900 rounded-2xl border border-slate-800 p-5 shadow-xs flex flex-col h-[520px]">
          <div class="flex items-center justify-between pb-3.5 mb-3 border-b border-slate-800">
            <div class="flex items-center gap-2">
              <div class="flex items-center gap-1.5">
                <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
                <span class="w-2 h-2 rounded-full bg-slate-700"></span>
                <span class="w-2 h-2 rounded-full bg-slate-700"></span>
              </div>
              <span class="text-xs font-mono font-medium text-slate-300 ml-1">System Prompt Preview</span>
            </div>

            <button
              @click="copyPrompt"
              class="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-[11px] font-mono transition-all cursor-pointer"
            >
              <Check v-if="copied" class="w-3 h-3 text-emerald-400" />
              <Copy v-else class="w-3 h-3" />
              <span>{{ copied ? '已复制' : '复制' }}</span>
            </button>
          </div>

          <pre class="flex-1 overflow-y-auto text-[11px] text-slate-300 font-mono whitespace-pre-wrap leading-relaxed pr-2 select-text selection:bg-emerald-500/30 scrollbar-thin">{{ previewPrompt }}</pre>

          <div class="pt-3 mt-3 border-t border-slate-800 text-[10px] text-slate-400 flex items-center justify-between font-mono">
            <span>Tokens 预估: ~{{ Math.round(previewPrompt.length * 1.2) }}</span>
            <span class="text-emerald-400">实时热更新</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Sparkles, Check, Copy } from 'lucide-vue-next'
import { api } from '@/api'

const emit = defineEmits(['toast'])

const persona = ref({
  preset_id: 'friend',
  name: '小暖',
  age: 24,
  job: '自由撰稿人',
  personality: '细腻、真诚、包容、讲话自然松弛...',
  background: '喜欢在阳光温暖的午后画画、煮花茶...',
  catchphrases: '抱抱你、好嘞、没关系慢慢来、听我的准没错~',
  max_words: 120,
  custom_prompt: '',
})

const presets = ref({})
const isSaving = ref(false)
const copied = ref(false)

onMounted(async () => {
  try {
    const res = await api.getPersona()
    if (res.persona) persona.value = { ...persona.value, ...res.persona }
    if (res.presets) presets.value = res.presets
  } catch (e) {
    emit('toast', '加载性格设置失败: ' + e.message)
  }
})

function applyPreset(pid, p) {
  persona.value.preset_id = pid
  persona.value.name = p.name
  persona.value.job = p.job
  persona.value.personality = p.personality
  persona.value.background = p.background
  persona.value.catchphrases = p.catchphrases
  persona.value.max_words = p.max_words
}

const previewPrompt = computed(() => {
  return `你是「${persona.value.name}」，正在微信上与朋友聊天。请完全沉浸在该角色中，用真实的微信日常口吻回复，严禁暴露你是一个人工智能或语言模型。

【人设背景】：
- 称呼/姓名：${persona.value.name}
- 职业/身份：${persona.value.job}
- 性格特点：${persona.value.personality}
- 背景经历：${persona.value.background}
- 口头禅/口癖习惯：${persona.value.catchphrases}

【微信聊天行为守则】：
1. 语言自然生活化，像真实微信好友一样随性，避免长篇大论或机械说教；
2. 单次回复控制在 ${persona.value.max_words || 100} 字以内，言简意赅，适合手机气泡阅读；
3. 严格遵循人设的语气和口吻；如果有记忆事实，请自然融入对话中，表现出你记得彼此经历的熟络感；
${persona.value.custom_prompt ? `\n【补充规则】：\n${persona.value.custom_prompt}` : ''}`
})

async function copyPrompt() {
  try {
    await navigator.clipboard.writeText(previewPrompt.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch (e) {
    emit('toast', '复制失败，请手动选取复制')
  }
}

async function savePersona() {
  isSaving.value = true
  try {
    const res = await api.savePersona(persona.value)
    if (res.code === 0) {
      emit('toast', '角色人设配置已保存！')
    }
  } catch (e) {
    emit('toast', '保存人设失败: ' + e.message)
  } finally {
    isSaving.value = false
  }
}
</script>
