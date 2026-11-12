<script setup>
import { onMounted, reactive, ref } from 'vue'
import { getJSON, patchJSON, putJSON } from '../api'
const rows = ref([])
const msg = ref('')
const err = ref('')
const editing = reactive({})

async function refresh() { rows.value = await getJSON('/api/jobs') }
async function saveAttempts(row) {
  err.value = ''; msg.value = ''
  try {
    await patchJSON(`/api/jobs/${row.id}/max-attempts`, { max_attempts: Number(row.max_attempts) || 1 })
    msg.value = `已保存 ${row.name} 的 max_attempts`
    await refresh()
  } catch (e) { err.value = String(e.message || e) }
}

function startEdit(row) {
  editing[row.id] = {
    conditions: JSON.stringify(row.branch_conditions || [], null, 2),
    mutex_group: row.mutex_group || '',
  }
}
function cancelEdit(row) { delete editing[row.id] }

async function saveBranch(row) {
  err.value = ''; msg.value = ''
  const draft = editing[row.id]
  let conditions
  try {
    conditions = JSON.parse(draft.conditions)
  } catch (e) {
    err.value = `${row.name} 分支条件不是合法 JSON：${e.message}`
    return
  }
  if (!Array.isArray(conditions)) {
    err.value = `${row.name} 分支条件必须是数组`
    return
  }
  const mutexGroup = draft.mutex_group.trim() ? draft.mutex_group.trim() : null
  try {
    const saved = await putJSON(`/api/jobs/${row.id}/branch-config`, {
      branch_conditions: conditions,
      mutex_group: mutexGroup,
    })
    msg.value = `已保存 ${row.name} 的分支配置`
    delete editing[row.id]
    await refresh()
    return saved
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function conditionText(cond) {
  if (cond.type === 'rows') {
    return `行数 ${cond.upstream}.artifact_rows ${cond.op} ${cond.value}`
  }
  return `标志 ${cond.upstream}.flags.${cond.flag} ${cond.op} ${String(cond.value)}`
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>作业</h1>
    <p class="muted">
      依赖边（depends_on）只表达“能不能跑”；分支条件表达“上游产出后该不该跑”。
      条件不命中记 <span class="tag warn">skipped_branch</span> 旁路，不跑夹具；
      同一互斥组一趟只允许一个下游执行，其余记 <span class="tag warn">skipped_mutex</span>。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag ok">{{ msg }}</p>
    <div class="panel" v-for="j in rows" :key="j.id">
      <table>
        <thead><tr><th>ID</th><th>名称</th><th>依赖</th><th>max_attempts</th><th>互斥组</th><th>夹具</th><th></th></tr></thead>
        <tbody>
          <tr>
            <td>{{ j.id }}</td>
            <td class="mono">{{ j.name }}</td>
            <td class="mono">{{ j.depends_on.join(', ') || '—' }}</td>
            <td><input type="number" min="1" max="10" v-model.number="j.max_attempts" style="width:4.5rem" /></td>
            <td class="mono">{{ j.mutex_group || '—' }}</td>
            <td class="mono">{{ j.fixture_path }}</td>
            <td style="white-space:nowrap">
              <button class="secondary" @click="saveAttempts(j)">保存次数</button>
              <button class="secondary" @click="startEdit(j)" v-if="!editing[j.id]">分支配置</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div style="margin-top:0.5rem">
        <strong>分支条件：</strong>
        <span v-if="!(j.branch_conditions || []).length" class="muted">无条件（依赖就绪即执行）</span>
        <span v-else>
          <span class="tag" v-for="(c, i) in j.branch_conditions" :key="i" style="margin-right:0.35rem">{{ conditionText(c) }}</span>
        </span>
      </div>
      <div v-if="editing[j.id]" class="branch-editor">
        <p class="muted" style="margin-bottom:0.35rem">
          条件为 AND 组合；rows 条件 value 为整数阈值，flag 条件 value 为布尔值；upstream 必须在依赖列表中。
        </p>
        <label>
          分支条件 JSON
          <textarea v-model="editing[j.id].conditions" rows="7" class="mono"></textarea>
        </label>
        <label style="margin-top:0.5rem">
          互斥组（留空表示不参与互斥）
          <input v-model="editing[j.id].mutex_group" placeholder="例如 fact_volume" />
        </label>
        <div style="margin-top:0.5rem">
          <button @click="saveBranch(j)">保存分支配置</button>
          <button class="secondary" @click="cancelEdit(j)" style="margin-left:0.5rem">取消</button>
        </div>
      </div>
      <p class="muted" style="margin-bottom:0">{{ j.note }}</p>
    </div>
  </div>
</template>
<style scoped>
.branch-editor {
  margin-top: 0.6rem;
  padding: 0.75rem;
  border: 1px dashed var(--line);
  border-radius: 8px;
  background: #faf7ef;
}
.branch-editor label { display: block; font-size: 0.9rem; }
.branch-editor textarea {
  width: 100%;
  margin-top: 0.3rem;
  font-family: ui-monospace, Consolas, monospace;
  padding: 0.45rem;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.branch-editor input { margin-top: 0.3rem; min-width: 12rem; }
</style>
