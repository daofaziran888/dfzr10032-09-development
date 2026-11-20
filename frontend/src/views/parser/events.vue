<template>
  <section class="page" data-module="parser-events">
    <header class="page-head">
      <div>
        <h2>标准化事件明细</h2>
        <p class="page-desc">
          按解析配置读取原始事件，逐字段记录类型转换结果并保留文件行号；源数据缺值与已提供但无法转换分开标记。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="loading" @click="normalize">重新标准化</button>
        <button class="btn" type="button" @click="loadRaw">查看原始事件</button>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>解析配置</span>
        <select v-model="configNo" @change="reload">
          <option v-for="config in configs" :key="config.解析编号" :value="config.解析编号">
            {{ config.解析编号 }} · {{ config.source_name }}（{{ config.input_format }}）
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>事件状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option value="ok">全部转换成功</option>
          <option value="partial">部分字段失败</option>
          <option value="failed">全部字段失败</option>
        </select>
      </label>
      <label class="filter-item">
        <span>原始行号</span>
        <input v-model="lineKeyword" placeholder="例如 3" />
      </label>
      <button class="btn" type="submit">按条件筛选</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="stat-row">
      <article v-for="card in summaryCards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <div v-if="activeConfig" class="config-card">
      <div class="config-line"><strong>字段映射</strong><span>{{ activeConfig.fields.map(f => `${f.source}→${f.target}`).join('，') }}</span></div>
      <div class="config-line"><strong>类型转换</strong><span>{{ activeConfig.fields.map(f => `${f.target}=${f.type}`).join('，') }}</span></div>
      <div class="config-line"><strong>空值处理</strong><span>{{ activeConfig.null_tokens.join('、') }}</span></div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>行号</th>
          <th>事件状态</th>
          <th v-for="field in fieldColumns" :key="field.target">
            {{ field.label }}
            <small class="head-note">{{ field.type }}</small>
          </th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="event in visibleEvents" :key="String(event.raw_event_id)">
          <td>{{ event.行号 }}</td>
          <td>
            <span :class="['pill', event.status]">{{ event.status_label }}</span>
          </td>
          <td v-for="field in fieldColumns" :key="field.target" class="field-cell">
            <template v-if="event.字段[field.target]">
              <span :class="['pill', event.字段[field.target].status]">
                {{ event.字段[field.target].status_label }}
              </span>
              <div class="field-value">
                原文：{{ displayRaw(event.字段[field.target].raw_value) }}
              </div>
              <div v-if="event.字段[field.target].status === 'ok'" class="field-value">
                转换：{{ displayValue(event.字段[field.target]) }}
              </div>
            </template>
            <span v-else class="muted">—</span>
          </td>
          <td class="reason-cell">{{ eventReason(event) }}</td>
        </tr>
        <tr v-if="!visibleEvents.length">
          <td :colspan="fieldColumns.length + 3" class="empty-state">当前筛选条件下没有标准化事件</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ visibleEvents.length }} 条标准化事件（全部 {{ events.length }} 条）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="showRawModal" class="modal-overlay" @click.self="showRawModal = false">
        <div class="modal-card wide">
          <header class="modal-head">
            <h3>原始事件（按解析配置读取，保留原始行号）</h3>
            <button class="btn ghost" type="button" @click="showRawModal = false">&times;</button>
          </header>
          <div class="modal-body">
            <table class="data-table">
              <thead>
                <tr>
                  <th>行号</th>
                  <th v-for="column in rawColumns" :key="column">{{ column }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in rawEvents" :key="String(row.id)">
                  <td>{{ row.行号 }}</td>
                  <td v-for="column in rawColumns" :key="column">{{ displayRaw(row.原文[column]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type FieldConfig = { source: string; target: string; label: string; type: string }
type ParseConfig = {
  解析编号: string
  source_name: string
  input_format: string
  null_tokens: string[]
  fields: FieldConfig[]
}
type FieldResult = {
  source: string
  label: string
  raw_value: string | null
  value: string | number | null
  status: 'ok' | 'missing' | 'invalid'
  status_label: string
  error: string | null
}
type NormalizedEvent = {
  raw_event_id: number
  行号: number
  status: 'ok' | 'partial' | 'failed'
  status_label: string
  字段: Record<string, FieldResult>
  missing_fields: string[]
  invalid_fields: string[]
}
type RawEvent = { id: number; 行号: number; 原文: Record<string, string | null> }

const configs = ref<ParseConfig[]>([])
const configNo = ref('')
const events = ref<NormalizedEvent[]>([])
const rawEvents = ref<RawEvent[]>([])
const statusFilter = ref('')
const lineKeyword = ref('')
const errorMessage = ref('')
const loading = ref(false)
const showRawModal = ref(false)

const activeConfig = computed(() => configs.value.find((config) => config.解析编号 === configNo.value))
const fieldColumns = computed(() => activeConfig.value?.fields ?? [])
const rawColumns = computed(() => fieldColumns.value.map((field) => field.source))

const visibleEvents = computed(() =>
  events.value.filter((event) => {
    if (statusFilter.value && event.status !== statusFilter.value) {
      return false
    }
    if (lineKeyword.value.trim() && String(event.行号) !== lineKeyword.value.trim()) {
      return false
    }
    return true
  }),
)

const summaryCards = computed(() => [
  { label: '事件总数', value: events.value.length },
  { label: '全部转换成功', value: events.value.filter((event) => event.status === 'ok').length },
  { label: '部分字段失败', value: events.value.filter((event) => event.status === 'partial').length },
  { label: '源数据缺值字段', value: events.value.reduce((sum, event) => sum + event.missing_fields.length, 0) },
  { label: '转换失败字段', value: events.value.reduce((sum, event) => sum + event.invalid_fields.length, 0) },
])

function displayRaw(value: string | null | undefined): string {
  if (value === null || value === undefined) {
    return '（字段缺失）'
  }
  return value === '' ? '（空值）' : value
}

function displayValue(field: FieldResult): string {
  return field.value === null ? '—' : String(field.value)
}

function eventReason(event: NormalizedEvent): string {
  const failures = [...event.missing_fields, ...event.invalid_fields]
    .map((key) => event.字段[key]?.error)
    .filter(Boolean)
  return failures.length ? failures.join('；') : '字段全部转换成功'
}

function applyFilters() {
  // 状态与行号都是本地筛选条件，提交时不需要额外请求。
}

function resetFilters() {
  statusFilter.value = ''
  lineKeyword.value = ''
}

async function loadConfigs() {
  const response = await request('/api/parser/events/configs')
  if (!response.ok) {
    throw new Error('解析配置读取失败')
  }
  const payload = await response.json()
  configs.value = payload.items ?? []
  if (!configNo.value && configs.value.length) {
    configNo.value = configs.value[0].解析编号
  }
}

async function readEvents(config: string): Promise<NormalizedEvent[]> {
  const response = await request(`/api/parser/events?config=${encodeURIComponent(config)}`)
  if (!response.ok) {
    throw new Error('标准化事件明细读取失败')
  }
  const payload = await response.json()
  return payload.items ?? []
}

async function loadRaw() {
  errorMessage.value = ''
  try {
    const response = await request(`/api/parser/events/raw?config=${encodeURIComponent(configNo.value)}`)
    if (!response.ok) {
      throw new Error('原始事件读取失败')
    }
    const payload = await response.json()
    rawEvents.value = payload.items ?? []
    showRawModal.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '原始事件读取失败'
  }
}

async function normalize() {
  errorMessage.value = ''
  loading.value = true
  try {
    const response = await request(`/api/parser/events/normalize?config=${encodeURIComponent(configNo.value)}`, {
      method: 'POST',
    })
    if (!response.ok) {
      throw new Error('标准化执行失败')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '标准化执行失败'
  } finally {
    loading.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  if (!configNo.value) {
    events.value = []
    return
  }
  loading.value = true
  try {
    events.value = await readEvents(configNo.value)
  } catch (error) {
    events.value = []
    errorMessage.value = error instanceof Error ? error.message : '标准化事件明细读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await loadConfigs()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '解析配置读取失败'
  }
})
</script>

<style scoped>
.config-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.config-line { display: flex; gap: 8px; margin: 2px 0; }
.config-line strong { color: var(--muted); font-weight: 500; min-width: 64px; }
.filter-item select, .filter-item input {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.head-note { color: var(--muted); font-weight: 400; }
.pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  white-space: nowrap;
}
.pill.ok { background: #e7f6ec; color: #1a7f37; }
.pill.missing { background: #fff4e5; color: #b25b00; }
.pill.invalid { background: #fde8e8; color: #b42318; }
.pill.partial { background: #fff4e5; color: #b25b00; }
.pill.failed { background: #fde8e8; color: #b42318; }
.field-cell { min-width: 150px; vertical-align: top; }
.field-value { color: var(--muted); font-size: 12px; margin-top: 2px; }
.reason-cell { min-width: 220px; font-size: 12px; color: #b42318; }
.muted { color: var(--muted); }
.modal-card.wide { width: 720px; }
</style>
