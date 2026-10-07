<template>
  <div>
    <div class="status-bar">
      <span>可借 {{ counts.available ?? 0 }}</span>
      <span>在借 {{ counts.active ?? 0 }}</span>
      <span>逾期 {{ counts.overdue ?? 0 }}</span>
    </div>
    <nav class="topnav">
      <router-link to="/">看板</router-link>
      <router-link to="/list">上架</router-link>
      <router-link to="/loans">借还记录</router-link>
      <router-link to="/owners">物主</router-link>
      <router-link to="/settings">设置</router-link>
    </nav>
    <router-view />
  </div>
</template>
<script setup>
import { ref, onMounted, provide, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api'
// 顶细条计数只问投影接口，不自行拼装、不扫真源
const counts = ref({ available: 0, active: 0, overdue: 0 })
const route = useRoute()
async function loadCounts() {
  counts.value = await api('/proj/counts')
}
provide('reloadCounts', loadCounts)
onMounted(loadCounts)
watch(() => route.fullPath, loadCounts)
</script>
