<template>
  <section class="page" data-module="inspection">
    <header class="page-head">
      <div>
        <h2>巡检任务管理</h2>
        <p class="page-desc">维护巡检单，围绕巡检单号、巡检站点、巡检人员、巡检日期做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检单</button>
        <button class="btn" type="button" @click="exportRows">导出巡检任务清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无巡检任务数据，可先登记巡检单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条巡检任务记录，其中待处理 {{ stats['待处理巡检'] }} 条（已提交、已作废不再计入）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Stats = Record<'待处理巡检' | '待派发巡检' | '巡检中任务' | '本月发现问题', number>

const ENDPOINT = '/api/inspection'
const columns = ["巡检单号", "巡检站点", "巡检人员", "巡检日期", "巡检项目", "发现问题数", "巡检时长", "巡检状态"]
const actions = ["派发巡检", "提交结果", "作废巡检"]
const STAT_LABELS = ["待处理巡检", "待派发巡检", "巡检中任务", "本月发现问题"] as const
const EMPTY_STATS: Stats = { 待处理巡检: 0, 待派发巡检: 0, 巡检中任务: 0, 本月发现问题: 0 }

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stats>({ ...EMPTY_STATS })
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const statCards = computed(() => STAT_LABELS.map((label) => ({ label, value: stats.value[label] })))

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '巡检单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || payload?.detail || '巡检任务动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检任务操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('巡检单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 统计以后端口径为准；后端未返回时按同一规则在当前页兜底，保证页脚、卡片、看板三处对得上。
    stats.value = { ...EMPTY_STATS, ...(payload.stats ?? {}) }
    if (!payload.stats) {
      const pendingRows = rows.value.filter((row) => ['待派发', '巡检中'].includes(String(row.status)))
      stats.value['待处理巡检'] = pendingRows.length
      stats.value['待派发巡检'] = pendingRows.filter((row) => row.status === '待派发').length
      stats.value['巡检中任务'] = pendingRows.filter((row) => row.status === '巡检中').length
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检任务列表读取失败'
  }
}

onMounted(reload)
</script>
