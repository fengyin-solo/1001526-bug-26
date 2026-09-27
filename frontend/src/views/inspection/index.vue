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
      <span>共 {{ total }} 条巡检任务记录，待处理 {{ pendingCount }} 条</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Stats = {
  total: number
  pending: number
  pending_dispatch: number
  in_progress: number
  submitted: number
  voided: number
  problems_month: number
}

const ENDPOINT = '/api/inspection'
const columns = ["巡检单号", "巡检站点", "巡检人员", "巡检日期", "巡检项目", "发现问题数", "巡检时长", "巡检状态"]
const actions = ["派发巡检", "提交结果", "作废巡检"]
const statuses = ["待派发", "巡检中", "已提交", "已作废"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stats>({
  total: 0,
  pending: 0,
  pending_dispatch: 0,
  in_progress: 0,
  submitted: 0,
  voided: 0,
  problems_month: 0,
})
// 三处同口径：页脚、统计卡与概览看板的待处理都取自后端 /stats 的 pending。
const pendingCount = computed(() => stats.value.pending)
const statCards = computed(() => [
  { label: '待派发巡检', value: stats.value.pending_dispatch },
  { label: '巡检中任务', value: stats.value.in_progress },
  { label: '本月发现问题', value: stats.value.problems_month },
])
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

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
    if (!response.ok) {
      throw new Error('巡检任务动作未生效，请稍后重试')
    }
    const result = (await response.json()) as { ok?: boolean; message?: string }
    // 后端业务拒绝时 HTTP 仍是 200，需按 ok 判定并保留具体原因（含巡检单号与缺失字段）。
    if (!result.ok) {
      errorMessage.value = result.message || '巡检任务操作未生效'
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检任务操作失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('巡检任务统计读取失败')
    }
    stats.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检任务统计读取失败'
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
    // 统计与列表每次都向后端重新汇总，刷新或换人进入看到的口径保持一致。
    await reloadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检任务列表读取失败'
  }
}

onMounted(reload)
</script>
