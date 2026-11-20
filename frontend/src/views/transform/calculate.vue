<template>
  <section class="page" data-module="transform-calc">
    <header class="page-head">
      <div>
        <h2>转换计算结果</h2>
        <p class="page-desc">
          按标准化事件明细与表达式的字段依赖生成计算结果；每条计算记录区分正常产出、被阻断、未纳入，并能指回称重原文行号。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="loading" @click="calculate">执行计算</button>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="calculate">
      <label class="filter-item">
        <span>解析配置</span>
        <select v-model="configNo">
          <option v-for="config in configs" :key="config.解析编号" :value="config.解析编号">
            {{ config.解析编号 }} · {{ config.source_name }}
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>转换表达式</span>
        <select v-model="expressionNo">
          <option value="">全部表达式</option>
          <option v-for="expr in expressions" :key="expr.表达式编号" :value="expr.表达式编号">
            {{ expr.表达式编号 }} · {{ expr.名称 }}
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>计算记录</span>
        <select v-model="outcomeFilter">
          <option value="">全部</option>
          <option value="produced">正常产出</option>
          <option value="blocked">被阻断</option>
          <option value="excluded">未纳入</option>
        </select>
      </label>
      <button class="btn" type="submit">重新计算</button>
    </form>

    <div class="stat-row">
      <article v-for="card in summaryCards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <p v-if="result" class="page-desc">
      解析来源：{{ result.source_name }} · 生成时间：{{ result.生成时间 }} · 阻断记录 {{ result.阻断记录.length }} 条
    </p>

    <article v-for="expr in visibleExpressions" :key="expr.表达式编号" class="expr-card">
      <header class="expr-head">
        <div>
          <strong>{{ expr.表达式编号 }}</strong>
          <span class="expr-name">{{ expr.名称 }}</span>
          <code class="formula">{{ expr.公式 }}</code>
        </div>
        <div class="expr-meta">
          依赖字段：
          <span v-for="dep in expr.依赖字段" :key="dep.field" class="dep">
            {{ dep.field }}<small>{{ dep.required ? '必填' : '可选' }}</small>
          </span>
        </div>
      </header>

      <div class="stat-row tight">
        <article v-for="(value, label) in expr.summary" :key="label" class="stat-card mini">
          <span class="stat-label">{{ label }}</span>
          <strong class="stat-value">{{ value }}</strong>
        </article>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>分组</th>
            <th>产出条数</th>
            <th>数值</th>
            <th>输出字段</th>
            <th>关联原始行号</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in expr.结果" :key="String(item.分组)">
            <td>{{ item.分组 }}</td>
            <td>{{ item.产出条数 }}</td>
            <td>{{ item.数值 }} {{ item.输出单位 }}</td>
            <td>{{ item.输出字段 }}</td>
            <td>{{ item.关联行号.join('、') }}</td>
          </tr>
          <tr v-if="!expr.结果.length">
            <td colspan="5" class="empty-state">该表达式没有可正常产出的事件</td>
          </tr>
        </tbody>
      </table>

      <details class="records" open>
        <summary>计算记录（{{ filteredRecords(expr).length }} / {{ expr.计算记录.length }}）</summary>
        <table class="data-table">
          <thead>
            <tr>
              <th>行号</th>
              <th>归属</th>
              <th>分组</th>
              <th>贡献值</th>
              <th>原文</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in filteredRecords(expr)" :key="`${expr.表达式编号}-${record.行号}`">
              <td>{{ record.行号 }}</td>
              <td><span :class="['pill', record.outcome]">{{ record.outcome_label }}</span></td>
              <td>{{ record.group ?? '—' }}</td>
              <td>{{ record.contribution ?? '—' }}</td>
              <td class="raw-cell">{{ rawSummary(record) }}</td>
              <td :class="record.outcome === 'blocked' ? 'reason-cell' : 'muted'">
                {{ record.reason ?? (record.outcome === 'produced' ? '已参与计算' : '不满足纳入条件') }}
              </td>
            </tr>
          </tbody>
        </table>
      </details>
    </article>

    <footer class="page-foot">
      <span v-if="result">共 {{ result.计算记录.length }} 条计算记录，其中阻断 {{ result.阻断记录.length }} 条</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type ParseConfig = { 解析编号: string; source_name: string }
type Expression = { 表达式编号: string; 名称: string; 依赖字段: { field: string; required: boolean }[] }
type CalculationRecord = {
  raw_event_id: number
  行号: number
  outcome: 'produced' | 'blocked' | 'excluded'
  outcome_label: string
  group: string | null
  contribution: number | null
  reason: string | null
  原始事件: { 行号: number; 原文: Record<string, string | null> }
}
type ExpressionResult = {
  表达式编号: string
  名称: string
  公式: string
  输出字段: string
  依赖字段: { field: string; required: boolean }[]
  summary: Record<string, number>
  结果: {
    分组: string
    产出条数: number
    数值: number
    输出字段: string
    输出单位: string
    关联行号: number[]
  }[]
  计算记录: CalculationRecord[]
}
type Calculation = {
  解析编号: string
  source_name: string
  生成时间: string
  summary: Record<string, number>
  表达式: ExpressionResult[]
  计算记录: CalculationRecord[]
  阻断记录: CalculationRecord[]
}

const configs = ref<ParseConfig[]>([])
const expressions = ref<Expression[]>([])
const configNo = ref('')
const expressionNo = ref('')
const outcomeFilter = ref('')
const result = ref<Calculation | null>(null)
const errorMessage = ref('')
const loading = ref(false)

const visibleExpressions = computed(() =>
  (result.value?.表达式 ?? []).filter((expr) => !expressionNo.value || expr.表达式编号 === expressionNo.value),
)

const summaryCards = computed(() => {
  const summary = result.value?.summary ?? {}
  return [
    { label: '正常产出', value: summary['正常产出'] ?? 0 },
    { label: '被阻断', value: summary['被阻断'] ?? 0 },
    { label: '未纳入', value: summary['未纳入'] ?? 0 },
    { label: '事件总数', value: summary['事件总数'] ?? 0 },
  ]
})

function filteredRecords(expr: ExpressionResult): CalculationRecord[] {
  if (!outcomeFilter.value) {
    return expr.计算记录
  }
  return expr.计算记录.filter((record) => record.outcome === outcomeFilter.value)
}

function rawSummary(record: CalculationRecord): string {
  return Object.entries(record.原始事件?.原文 ?? {})
    .map(([key, value]) => `${key}=${value === '' || value === null ? '空' : value}`)
    .join('，')
}

async function loadMetadata() {
  const [configResponse, exprResponse] = await Promise.all([
    request('/api/parser/events/configs'),
    request('/api/transform/expressions'),
  ])
  if (!configResponse.ok || !exprResponse.ok) {
    throw new Error('计算所需的解析配置或表达式读取失败')
  }
  configs.value = (await configResponse.json()).items ?? []
  expressions.value = (await exprResponse.json()).items ?? []
  if (!configNo.value && configs.value.length) {
    configNo.value = configs.value[0].解析编号
  }
}

async function calculate() {
  errorMessage.value = ''
  if (!configNo.value) {
    return
  }
  loading.value = true
  try {
    const params = new URLSearchParams({ config: configNo.value })
    if (expressionNo.value) {
      params.set('expression', expressionNo.value)
    }
    const response = await request(`/api/transform/calculate?${params.toString()}`)
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || '转换计算执行失败')
    }
    result.value = (await response.json()) as Calculation
  } catch (error) {
    result.value = null
    errorMessage.value = error instanceof Error ? error.message : '转换计算执行失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await loadMetadata()
    await calculate()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '计算所需的解析配置或表达式读取失败'
  }
})
</script>

<style scoped>
.expr-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
}
.expr-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.expr-name { margin-left: 8px; font-size: 14px; }
.formula { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; }
.expr-meta { font-size: 12px; color: var(--muted); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.dep { background: #eef2f7; border-radius: 10px; padding: 1px 8px; color: #334155; }
.dep small { margin-left: 4px; color: #64748b; }
.stat-row.tight { margin-bottom: 8px; }
.stat-card.mini { padding: 6px 10px; }
.stat-card.mini .stat-value { font-size: 16px; }
.records { margin-top: 10px; font-size: 13px; }
.records summary { cursor: pointer; color: var(--muted); margin-bottom: 6px; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.pill.produced { background: #e7f6ec; color: #1a7f37; }
.pill.blocked { background: #fde8e8; color: #b42318; }
.pill.excluded { background: #eef2f7; color: #475569; }
.raw-cell { font-size: 12px; color: var(--muted); max-width: 320px; }
.reason-cell { font-size: 12px; color: #b42318; min-width: 240px; }
.muted { color: var(--muted); }
.filter-item select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
</style>
