<template>
  <div class="split">
    <section class="pane">
      <h2>可借物</h2>
      <p v-if="error" class="err">{{ error }}</p>
      <div v-for="i in available" :key="i.item_id" class="item">
        <strong>{{ i.title }}</strong>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <input v-model="forms[i.item_id].borrower" placeholder="借用人" />
        <input v-model="forms[i.item_id].due_date" placeholder="应还日 YYYY-MM-DD" />
        <button @click="lend(i.item_id)">借出通过</button>
      </div>
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...onLoan.overdue, ...onLoan.active]" :key="l.loan_id" class="item" :class="{ overdue: l.overdue }">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <div class="muted">应还 {{ l.due_date }} {{ l.overdue ? '· 逾期' : '' }}</div>
        <button @click="ret(l.loan_id)">归还</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { ref, reactive, watch, onMounted, inject } from 'vue'
import { api } from '../api'
const reloadCounts = inject('reloadCounts')
// 左右两栏只打投影接口，不碰真源接口，也不本地改行
const available = ref([])
const onLoan = ref({ active: [], overdue: [] })
const error = ref('')
const forms = reactive({})
async function loadColumns() {
  const [a, o] = await Promise.all([api('/proj/available'), api('/proj/on-loan')])
  available.value = a.rows
  onLoan.value = o
}
async function reloadAll() {
  await loadColumns()
  await reloadCounts()
}
watch(available, (rows) => {
  for (const i of rows) {
    if (!forms[i.item_id]) forms[i.item_id] = { borrower: '邻居', due_date: '2026-12-31' }
  }
}, { immediate: true })
async function lend(id) {
  error.value = ''
  try {
    await api('/items/' + id + '/lend', { method: 'POST', body: JSON.stringify(forms[id]) })
  } catch (e) {
    // 写失败（含投影刷新失败整体回滚）：亮错误，再从投影重读一致状态
    error.value = '借出失败：' + e.message
  }
  await reloadAll()
}
async function ret(id) {
  error.value = ''
  try {
    await api('/loans/' + id + '/return', { method: 'POST', body: '{}' })
  } catch (e) {
    error.value = '归还失败：' + e.message
  }
  await reloadAll()
}
onMounted(loadColumns)
</script>
