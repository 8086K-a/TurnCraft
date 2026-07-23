<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const senderId = ref('3251')
const draftMessage = ref('')
const isSending = ref(false)
const errorMessage = ref('')
const messages = ref([])
const messagesContainer = ref(null)

const orders = ref([])
const products = ref([])
const cohorts = ref([])
const isLoadingSidebar = ref(false)
const sidebarError = ref('')
const activeTab = ref('orders')
const traceData = ref(null)
const expandedEventIndex = ref(null)
const traceVisible = ref(true)
const showFullState = ref(false)

const latestFullState = computed(() => {
  if (!traceData.value) return null
  for (let i = traceData.value.length - 1; i >= 0; i--) {
    if (traceData.value[i].event === 'state_full') {
      return traceData.value[i].state
    }
  }
  return null
})

function toggleLatestState() {
  showFullState.value = !showFullState.value
}

const traceEventLabels = {
  turn_start: '开始处理',
  plan: '规划结果',
  track_selected: '选择轨道',
  command: '执行指令',
  state_change: '状态变更',
  state_full: '完整 State',
  flow_enter: '进入流程',
  step_enter: '进入步骤',
  branch: '条件分支',
  action_execute: '执行动作',
  action_result: '动作结果',
  step_result: '步骤结果',
  task_lifecycle: '任务生命周期',
  knowledge: '知识问答',
  chitchat: '闲聊',
  turn_end: '处理结束',
  error: '错误',
}

const traceEventColors = {
  turn_start: '#3b82f6',
  plan: '#8b5cf6',
  track_selected: '#f59e0b',
  command: '#06b6d4',
  state_change: '#6b7280',
  state_full: '#374151',
  flow_enter: '#10b981',
  step_enter: '#14b8a6',
  branch: '#f97316',
  action_execute: '#ef4444',
  action_result: '#ec4899',
  step_result: '#6366f1',
  task_lifecycle: '#84cc16',
  knowledge: '#a855f7',
  chitchat: '#ec4899',
  turn_end: '#6b7280',
  error: '#dc2626',
}

function formatEventSummary(event) {
  switch (event.event) {
    case 'turn_start':
      return `收到 ${event.sender_id} 的消息：${event.message_text || '(对象消息)'}`
    case 'plan':
      return 'LLM 返回规划结果'
    case 'track_selected':
      return `进入「${event.track}」轨道`
    case 'command':
      return `指令：${event.command_name}`
    case 'state_change': {
      const parts = []
      if (event.active_task) parts.push(`活动任务: ${event.active_task.flow_id}`)
      if (event.active_system_flow) parts.push(`系统流程: ${event.active_system_flow.flow_id}`)
      if (event.paused_tasks?.length) parts.push(`暂停任务: ${event.paused_tasks.length}个`)
      return parts.length ? parts.join(' | ') : '状态已更新'
    }
    case 'flow_enter':
      return `进入${event.flow_type === 'system' ? '系统' : '用户'}流程：${event.flow_name || event.flow_id}`
    case 'step_enter':
      return `步骤：${event.step_id} (${event.step_type})${event.description ? ' - ' + event.description : ''}`
    case 'branch':
      return `分支 #${event.branch_index}: ${event.condition || 'fallback'} → ${event.result}`
    case 'action_execute':
      return `动作：${event.action_name}`
    case 'action_result':
      return `动作完成${event.next_step_id ? ' → ' + event.next_step_id : ''}${event.end_flow ? ' [结束流程]' : ''}`
    case 'step_result':
      return `步骤完成${event.next_step_id ? ' → ' + event.next_step_id : ''}${event.end_flow ? ' [结束]' : ''}${event.completed ? ' [完成]' : ''}`
    case 'task_lifecycle':
      return `任务${event.action}：${event.flow_name || event.flow_id}`
    case 'knowledge':
      return `知识问答：${event.intents?.join(', ') || ''}`
    case 'chitchat':
      return '闲聊回复'
    case 'state_full': {
      const s = event.state || {}
      const parts = []
      if (s.active_task) parts.push(`活动任务: ${s.active_task.flow_id} [${s.active_task.step_id}]`)
      if (s.active_system_flow) parts.push(`系统流程: ${s.active_system_flow.flow_id}`)
      if (s.paused_tasks?.length) parts.push(`暂停任务: ${s.paused_tasks.length}个`)
      if (s.focused_object) parts.push(`焦点对象: ${s.focused_object.type}(${s.focused_object.id})`)
      if (s.current_session_id) parts.push(`会话: ${s.current_session_id.slice(0, 8)}...`)
      parts.push(`slots: ${Object.keys(s.active_task?.slots || {}).length}个`)
      return parts.length ? parts.join(' | ') : 'State 已更新'
    }
    case 'turn_end':
      return `处理完成，返回 ${event.message_count} 条消息`
    case 'error':
      return `错误：${event.message}`
    default:
      return event.event
  }
}

function toggleEvent(index) {
  expandedEventIndex.value = expandedEventIndex.value === index ? null : index
}

function formatTimestamp(ts) {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

const hasTrace = computed(() => traceData.value && traceData.value.length > 0)

const quickScenarios = [
  { label: '闲聊问候', text: '你好', tone: 'chat' },
  { label: '课程咨询', text: '我想了解 Python 全栈课程', tone: 'course' },
  { label: '订单查询', text: '帮我查订单 ORD0000000001', tone: 'order' },
  { label: '学习进度', text: '查询 Python 全栈第5期的学习进度', tone: 'progress' },
  { label: '退款申请', text: '我要退款', tone: 'refund' },
  { label: '提交工单', text: '我要投诉视频无法播放', tone: 'ticket' },
]

const chatEndpoint = computed(() => '/api/chat')
const chatHistoryEndpoint = computed(
  () => `/api/chat/history?sender_id=${encodeURIComponent(senderId.value.trim())}`
)
const commerceOrdersEndpoint = computed(
  () => '/edu-api/api/v1/orders?pageNo=1&pageSize=20'
)
const commerceProductsEndpoint = computed(
  () => '/edu-api/api/v1/series?pageNo=1&pageSize=20'
)
const commerceCohortsEndpoint = computed(
  () => `/edu-api/api/v1/me/cohorts?pageNo=1&pageSize=20`
)

const orderStatusLabels = {
  pending: '待支付',
  paid: '已支付',
  completed: '已完成',
  cancelled: '已取消',
  partial_refunded: '部分退款',
  refunded: '已退款',
}

function createBaseMessage(role) {
  return {
    id: crypto.randomUUID(),
    role,
    buttons: [],
  }
}

function appendUserText(text) {
  messages.value.push({
    ...createBaseMessage('user'),
    type: 'text',
    text,
  })
}

function appendUserObject(objectType, payload) {
  messages.value.push({
    ...createBaseMessage('user'),
    type: 'object',
    objectType,
    payload,
  })
}

function appendBotMessages(botMessages) {
  for (const message of botMessages) {
    appendMessage('bot', message)
  }
}

function appendMessage(role, message) {
  if (role === 'divider') {
    messages.value.push({
      ...createBaseMessage('divider'),
      type: 'divider',
      text: message.text ?? '以上为历史消息',
    })
    return
  }

  if (message.object) {
    messages.value.push({
      ...createBaseMessage(role),
      type: 'object',
      objectType: message.object.type,
      payload: message.object,
    })
  } else {
    messages.value.push({
      ...createBaseMessage(role),
      type: 'text',
      text: message.text ?? '',
    })
  }
}

function setHistoryMessages(historyMessages) {
  messages.value = []
  for (const message of historyMessages) {
    const role = ['user', 'bot', 'divider'].includes(message.role) ? message.role : 'bot'
    appendMessage(role, message)
  }
}

async function scrollToBottom() {
  await nextTick()
  const container = messagesContainer.value
  if (!container) {
    return
  }
  container.scrollTop = container.scrollHeight
}

watch(
  () => messages.value.length,
  async () => {
    await scrollToBottom()
  }
)

function resetConversation() {
  messages.value = []
  errorMessage.value = ''
}

async function sendQuickScenario(scenario) {
  draftMessage.value = scenario.text
  await sendTextMessage()
}

function formatAmount(amount) {
  const numericAmount = Number(amount)
  if (Number.isNaN(numericAmount) || amount === null || amount === undefined || amount === '') {
    return ''
  }
  return `￥${numericAmount.toFixed(2)}`
}

const OBJECT_LABELS = {
  order: '订单对象',
  product: '商品对象',
  course: '课程对象',
  cohort: '班次对象',
}

const OBJECT_ID_LABELS = {
  order: '订单号',
  product: '商品号',
  course: '课程号',
  cohort: '班次号',
}

function getObjectTitle(message) {
  const payload = message.payload ?? {}
  if (payload.title) {
    return payload.title
  }
  return OBJECT_LABELS[message.objectType] || '业务对象'
}

function getObjectIdentifier(message) {
  const payload = message.payload ?? {}
  const id = payload.id ?? payload.order_id ?? payload.product_id ?? payload.course_id ?? payload.cohort_id
  const label = OBJECT_ID_LABELS[message.objectType] || '编号'
  return id ? `${label}：${id}` : label
}

function getObjectSummary(message) {
  const payload = message.payload ?? {}
  const type = message.objectType
  if (type === 'order') {
    const status = payload.status ?? payload.attributes?.status
    return status ? `订单状态：${status}` : '订单'
  }
  if (type === 'course') {
    const desc = payload.description ?? payload.attributes?.description
    const teacher = payload.teacher ?? payload.attributes?.teacher
    return teacher ? `讲师：${teacher}` : (desc || '课程信息')
  }
  if (type === 'cohort') {
    const period = payload.period ?? payload.attributes?.period
    return period ? `期数：${period}` : '班次信息'
  }
  const desc = payload.description ?? payload.attributes?.description
  return desc || '商品信息'
}

function getObjectAmount(message) {
  const payload = message.payload ?? {}
  const type = message.objectType
  if (type === 'order') {
    return formatAmount(payload.amount ?? payload.attributes?.amount)
  }
  if (type === 'course') {
    return formatAmount(payload.price ?? payload.attributes?.price)
  }
  if (type === 'cohort') {
    return ''
  }
  return formatAmount(payload.price ?? payload.attributes?.price)
}

async function fetchSidebarData() {
  const currentSenderId = senderId.value.trim()
  orders.value = []
  products.value = []
  cohorts.value = []
  sidebarError.value = ''

  if (!currentSenderId) {
    return
  }

  isLoadingSidebar.value = true
  try {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 1800)
    const [ordersResponse, productsResponse, cohortsResponse] = await Promise.all([
      fetch(commerceOrdersEndpoint.value, {
        signal: controller.signal,
        headers: { 'X-User-Id': currentSenderId },
      }),
      fetch(commerceProductsEndpoint.value, {
        signal: controller.signal,
        headers: { 'X-User-Id': currentSenderId },
      }),
      fetch(commerceCohortsEndpoint.value, {
        signal: controller.signal,
        headers: { 'X-User-Id': currentSenderId },
      }),
    ])
    window.clearTimeout(timeout)

    const [ordersPayload, productsPayload, cohortsPayload] = await Promise.all([
      ordersResponse.json(),
      productsResponse.json(),
      cohortsResponse.json(),
    ])

    if (!ordersResponse.ok || ordersPayload?.code !== 0) {
      throw new Error(ordersPayload.detail || ordersPayload.message || '加载订单列表失败。')
    }
    if (!productsResponse.ok || productsPayload?.code !== 0) {
      throw new Error(productsPayload.detail || productsPayload.message || '加载商品列表失败。')
    }

    const orderList = Array.isArray(ordersPayload?.data?.list) ? ordersPayload.data.list : []
    orders.value = orderList.map((order) => ({
      order_id: String(order.orderId ?? ''),
      title: order.orderNo || `订单 ${order.orderId ?? ''}`,
      status: orderStatusLabels[order.orderStatusCode] || order.orderStatusCode || '',
      amount: Number(order.payableAmount ?? 0),
      created_at: order.createdAt || '',
    }))

    const seriesList = Array.isArray(productsPayload?.data?.list) ? productsPayload.data.list : []
    products.value = seriesList.map((series) => ({
      product_id: String(series.seriesId ?? ''),
      title: series.seriesName || '课程',
      price: series.salePrice ?? series.price ?? null,
      description: series.description || `${series.deliveryModeCode || ''} ${series.saleStatusCode || ''}`.trim(),
      cover_url: series.coverUrl || '',
    }))

    const cohortList = Array.isArray(cohortsPayload?.data?.list) ? cohortsPayload.data.list : []
    cohorts.value = cohortList.map((cohort) => ({
      cohort_id: String(cohort.cohortId ?? cohort.id ?? ''),
      title: cohort.cohortName || cohort.name || `班次 ${cohort.cohortId ?? ''}`,
      period: cohort.period || cohort.cohortPeriod || '',
      status: cohort.status || cohort.cohortStatus || '',
      course_name: cohort.seriesName || '',
    }))
  } catch (error) {
    // Commerce is optional in the local demo; chat remains usable without it.
    sidebarError.value = '业务数据服务未连接，仍可使用下方测试场景。'
  } finally {
    isLoadingSidebar.value = false
  }
}

async function fetchChatHistory() {
  const currentSenderId = senderId.value.trim()
  if (!currentSenderId) {
    messages.value = []
    return
  }

  try {
    const response = await fetch(chatHistoryEndpoint.value)
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || '加载历史消息失败。')
    }
    if (currentSenderId === senderId.value.trim()) {
      setHistoryMessages(Array.isArray(data?.messages) ? data.messages : [])
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载历史消息失败。'
  }
}

async function sendPayload(payload) {
  if (isSending.value) {
    return
  }

  errorMessage.value = ''
  isSending.value = true

  try {
    const response = await fetch(chatEndpoint.value, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        sender_id: senderId.value.trim(),
        ...payload,
      }),
    })

    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || '请求失败。')
    }

    appendBotMessages(data.messages ?? [])
    if (data.trace) {
      traceData.value = data.trace
      expandedEventIndex.value = null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '请求失败。'
  } finally {
    isSending.value = false
  }
}

async function sendTextMessage() {
  const text = draftMessage.value.trim()
  const currentSenderId = senderId.value.trim()

  if (!currentSenderId) {
    errorMessage.value = '请先输入 sender_id。'
    return
  }
  if (!text) {
    return
  }

  draftMessage.value = ''
  appendUserText(text)
  await sendPayload({ text })
}

async function sendOrder(order) {
  const currentSenderId = senderId.value.trim()
  if (!currentSenderId) {
    errorMessage.value = '请先输入 sender_id。'
    return
  }

  appendUserObject('order', order)
  await sendPayload({
    object: {
      type: 'order',
      id: order.order_id,
      title: order.title,
      attributes: {
        status: order.status,
        amount: order.amount,
        created_at: order.created_at,
      },
    },
  })
}

async function sendProduct(product) {
  const currentSenderId = senderId.value.trim()
  if (!currentSenderId) {
    errorMessage.value = '请先输入 sender_id。'
    return
  }

  appendUserObject('product', product)
  await sendPayload({
    object: {
      type: 'product',
      id: product.product_id,
      title: product.title,
      attributes: {
        price: product.price,
      },
    },
  })
}

async function sendCohort(cohort) {
  const currentSenderId = senderId.value.trim()
  if (!currentSenderId) {
    errorMessage.value = '请先输入 sender_id。'
    return
  }

  appendUserObject('cohort', cohort)
  await sendPayload({
    object: {
      type: 'cohort',
      id: cohort.cohort_id,
      title: cohort.title,
      attributes: {
        period: cohort.period,
        status: cohort.status,
      },
    },
  })
}

watch(
  () => senderId.value.trim(),
  async (value, previousValue) => {
    if (value === previousValue) {
      return
    }

    resetConversation()
    if (!value) {
      orders.value = []
      products.value = []
      return
    }
    await Promise.all([fetchSidebarData(), fetchChatHistory()])
  }
)

onMounted(async () => {
  await Promise.all([fetchSidebarData(), fetchChatHistory()])
})
</script>

<template>
  <div class="app-shell">
    <div class="workspace">
      <div class="chat-card">
        <header class="chat-header">
          <div>
            <p class="eyebrow">EDU CUSTOMER / CHAT</p>
            <h1>教育智能客服</h1>
          </div>
        </header>

        <section class="controls">
          <label class="field">
            <span>sender_id</span>
            <div class="field-row">
              <input v-model="senderId" type="text" placeholder="3251" />
              <button
                type="button"
                class="secondary-button"
                :disabled="isLoadingSidebar"
                @click="fetchSidebarData"
              >
                {{ isLoadingSidebar ? '加载中...' : '刷新对象列表' }}
              </button>
            </div>
          </label>
        </section>

        <section ref="messagesContainer" class="messages">
          <div v-if="messages.length === 0" class="empty-state">
            可以先发一句 <code>你好</code>、<code>我要退款</code>、<code>这件衣服适合什么季节</code>，
            也可以直接点击右侧订单或商品，把业务对象送入后端会话。
          </div>

          <article
            v-for="message in messages"
            :key="message.id"
            class="message"
            :class="message.role"
          >
            <template v-if="message.type === 'divider'">
              <div class="history-divider">
                <span>{{ message.text }}</span>
              </div>
            </template>

            <template v-else>
            <div class="meta">
              {{ message.role === 'user' ? '你' : '客服 Bot' }}
            </div>

            <div class="bubble">
              <template v-if="message.type === 'object'">
                <div class="object-card" :class="`object-card-${message.objectType}`">
                  <div class="object-card-badge">
                    {{ OBJECT_LABELS[message.objectType] || '业务对象' }}
                  </div>
                  <div class="object-card-title">{{ getObjectTitle(message) }}</div>
                  <div class="object-card-meta">{{ getObjectIdentifier(message) }}</div>
                  <div class="object-card-meta">{{ getObjectSummary(message) }}</div>
                  <div class="object-card-price">{{ getObjectAmount(message) }}</div>
                </div>
              </template>

              <template v-else>
                <p>{{ message.text }}</p>
              </template>
            </div>
            </template>
          </article>
        </section>

        <aside class="trace-inline">
          <header class="trace-inline-header">
            <span class="trace-inline-title" @click="traceVisible = !traceVisible" style="cursor:pointer;flex:1">工作流日志</span>
            <button v-if="hasTrace" class="trace-state-btn" @click="toggleLatestState">完整 State</button>
            <span class="trace-inline-count" v-if="hasTrace">{{ traceData.length }} 条</span>
            <span class="trace-toggle" @click="traceVisible = !traceVisible" style="cursor:pointer">{{ traceVisible ? '▼' : '▶' }}</span>
          </header>

          <div v-if="showFullState && latestFullState" class="trace-full-state">
            <div class="trace-full-state-header">
              <span>完整 DialogueState</span>
              <button class="trace-state-btn" @click="showFullState = false">关闭</button>
            </div>
            <pre>{{ JSON.stringify(latestFullState, null, 2) }}</pre>
          </div>

          <template v-if="traceVisible">
            <p v-if="!hasTrace" class="trace-empty">暂无工作流日志（发送消息后显示）</p>

            <div v-else class="trace-list">
              <div
                v-for="(event, index) in traceData"
                :key="index"
                class="trace-item"
                :class="{ expanded: expandedEventIndex === index }"
              >
                <div class="trace-marker">
                  <span class="trace-dot" :style="{ background: traceEventColors[event.event] || '#6b7280' }"></span>
                  <div class="trace-connector"></div>
                </div>
                <div class="trace-content" @click="toggleEvent(index)">
                  <div class="trace-head">
                    <span class="trace-badge" :style="{ background: traceEventColors[event.event] || '#6b7280' }">
                      {{ traceEventLabels[event.event] || event.event }}
                    </span>
                    <span class="trace-time">{{ formatTimestamp(event.timestamp) }}</span>
                    <span v-if="expandedEventIndex === index" class="trace-expand-icon">−</span>
                    <span v-else class="trace-expand-icon">+</span>
                  </div>
                  <div class="trace-summary">{{ formatEventSummary(event) }}</div>
                  <div v-if="expandedEventIndex === index" class="trace-detail">
                    <pre>{{ JSON.stringify(event, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </aside>

        <p v-if="errorMessage" class="error-message">
          {{ errorMessage }}
        </p>

        <form class="composer" @submit.prevent="sendTextMessage">
          <input
            v-model="draftMessage"
            type="text"
            placeholder="请输入咨询内容..."
            :disabled="isSending"
          />
          <button type="submit" :disabled="isSending || !draftMessage.trim()">
            {{ isSending ? '发送中...' : '发送' }}
          </button>
        </form>
      </div>

      <aside class="sidebar">
        <div class="sidebar-header">
          <p class="eyebrow">EDU CUSTOMER</p>
          <h2>测试工作台</h2>
        </div>

        <section class="quick-panel" aria-labelledby="quick-title">
          <div class="section-heading">
            <span id="quick-title">快速场景</span>
            <span class="section-count">{{ quickScenarios.length }}</span>
          </div>
          <div class="scenario-list">
            <button
              v-for="scenario in quickScenarios"
              :key="scenario.tone"
              type="button"
              class="scenario-button"
              :class="`scenario-${scenario.tone}`"
              :disabled="isSending"
              @click="sendQuickScenario(scenario)"
            >
              <span class="scenario-dot" aria-hidden="true"></span>
              <span>{{ scenario.label }}</span>
            </button>
          </div>
        </section>

        <div class="tabs">
          <button
            type="button"
            class="tab-button"
            :class="{ active: activeTab === 'orders' }"
            @click="activeTab = 'orders'"
          >
            订单
          </button>
          <button
            type="button"
            class="tab-button"
            :class="{ active: activeTab === 'products' }"
            @click="activeTab = 'products'"
          >
            商品
          </button>
          <button
            type="button"
            class="tab-button"
            :class="{ active: activeTab === 'cohorts' }"
            @click="activeTab = 'cohorts'"
          >
            班次
          </button>
        </div>

        <p v-if="sidebarError" class="sidebar-error">{{ sidebarError }}</p>

        <div v-if="activeTab === 'orders'" class="sidebar-list">
          <div v-if="!orders.length && !isLoadingSidebar" class="sidebar-empty">
            暂无订单数据
          </div>

          <article v-for="order in orders" :key="order.order_id" class="sidebar-card">
            <div class="card-top">
              <div class="card-title">{{ order.title }}</div>
              <div class="card-amount">{{ formatAmount(order.amount) }}</div>
            </div>
            <div class="card-meta">订单号：{{ order.order_id }}</div>
            <div class="card-meta">订单状态：{{ order.status }}</div>
            <button
              type="button"
              class="secondary-button full-width"
              :disabled="isSending"
              @click="sendOrder(order)"
            >
              发送订单
            </button>
          </article>
        </div>

        <div v-else-if="activeTab === 'products'" class="sidebar-list">
          <div v-if="!products.length && !isLoadingSidebar" class="sidebar-empty">
            暂无商品数据
          </div>

          <article v-for="product in products" :key="product.product_id" class="sidebar-card">
            <div class="card-top">
              <div class="card-title">{{ product.title }}</div>
              <div class="card-amount" v-if="formatAmount(product.price)">{{ formatAmount(product.price) }}</div>
            </div>
            <div class="card-meta">商品号：{{ product.product_id }}</div>
            <div class="card-meta">商品信息：最近浏览 / 购买商品</div>
            <button
              type="button"
              class="secondary-button full-width"
              :disabled="isSending"
              @click="sendProduct(product)"
            >
              发送商品
            </button>
          </article>
        </div>

        <div v-else class="sidebar-list">
          <div v-if="!cohorts.length && !isLoadingSidebar" class="sidebar-empty">
            暂无班次数据
          </div>

          <article v-for="cohort in cohorts" :key="cohort.cohort_id" class="sidebar-card">
            <div class="card-top">
              <div class="card-title">{{ cohort.title }}</div>
              <div class="card-meta" v-if="cohort.course_name">{{ cohort.course_name }}</div>
            </div>
            <div class="card-meta">班次号：{{ cohort.cohort_id }}</div>
            <div class="card-meta" v-if="cohort.period">期数：{{ cohort.period }}</div>
            <button
              type="button"
              class="secondary-button full-width"
              :disabled="isSending"
              @click="sendCohort(cohort)"
            >
              发送班次
            </button>
          </article>
        </div>
      </aside>
    </div>
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: linear-gradient(180deg, #eef4ff 0%, #e6edf8 100%);
  color: #142033;
}

button,
input {
  font: inherit;
}

#app {
  min-height: 100vh;
}
</style>

<style scoped>
.app-shell {
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(28, 100, 242, 0.12), transparent 30%),
    radial-gradient(circle at bottom right, rgba(14, 165, 140, 0.12), transparent 28%),
    linear-gradient(180deg, #edf3fb 0%, #e7eef8 100%);
}

.workspace {
  width: min(1760px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 20px;
}

.chat-card,
.sidebar {
  min-height: calc(100vh - 48px);
  height: calc(100vh - 48px);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
}

.chat-card {
  display: flex;
  flex-direction: column;
}

.chat-header,
.sidebar-header {
  padding: 24px 24px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.chat-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
}

.chat-header h1,
.sidebar-header h2 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.sidebar-header h2 {
  font-size: 22px;
}

.controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field span {
  color: #4f5f77;
  font-size: 14px;
}

.field-row {
  display: flex;
  gap: 12px;
}

.field input,
.composer input {
  width: 100%;
  min-width: 0;
  min-height: 46px;
  padding: 11px 14px;
  border: 1px solid rgba(148, 163, 184, 0.4);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.86);
  color: #142033;
  font-size: 15px;
  line-height: 1.4;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-state,
.sidebar-empty {
  margin: auto;
  max-width: 420px;
  color: #61718a;
  text-align: center;
  line-height: 1.7;
}

.message {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: min(78%, 720px);
}

.message.user {
  align-self: flex-end;
}

.message.bot {
  align-self: flex-start;
}

.message.divider {
  align-self: stretch;
  max-width: none;
}

.history-divider {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #7a8aa3;
  font-size: 13px;
}

.history-divider::before,
.history-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: rgba(148, 163, 184, 0.36);
}

.history-divider span {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.meta {
  font-size: 13px;
  color: #71829a;
}

.bubble {
  padding: 15px 17px;
  border-radius: 20px;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.message.user .bubble {
  background: linear-gradient(135deg, #1d4ed8, #2563eb);
  border-color: transparent;
  color: #eff6ff;
  box-shadow: 0 12px 30px rgba(37, 99, 235, 0.22);
}

.message.bot .bubble {
  background: rgba(255, 255, 255, 0.94);
  color: #1b2a40;
}

.bubble p {
  margin: 0;
  font-size: 15px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.object-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 240px;
}

.object-card-badge {
  width: fit-content;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(20, 32, 51, 0.08);
  color: #27415f;
  font-size: 12px;
  line-height: 1;
}

.message.user .object-card-badge {
  background: rgba(255, 255, 255, 0.18);
  color: #eff6ff;
}

.object-card-title {
  font-size: 16px;
  line-height: 1.5;
  font-weight: 600;
}

.object-card-meta {
  font-size: 14px;
  color: inherit;
  opacity: 0.86;
}

.object-card-price {
  font-size: 15px;
  font-weight: 600;
}

.composer button,
.secondary-button,
.tab-button {
  min-height: 40px;
  padding: 9px 14px;
  border: 1px solid rgba(148, 163, 184, 0.36);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  color: #1b2a40;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.2;
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    background 0.16s ease;
}

.composer button:hover,
.secondary-button:hover,
.tab-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
}

.composer button:disabled,
.secondary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.error-message,
.sidebar-error {
  margin: 0;
  padding: 0 24px 14px;
  color: #c2410c;
}

.composer {
  flex-shrink: 0;
  display: flex;
  align-items: stretch;
  gap: 12px;
  padding: 16px 24px 24px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.72);
}

.composer button {
  min-width: 96px;
  padding-inline: 18px;
  background: linear-gradient(135deg, #0f766e, #0ea5a3);
  border-color: transparent;
  color: #f0fdfa;
  box-shadow: 0 14px 28px rgba(13, 148, 136, 0.2);
}

.sidebar {
  display: flex;
  flex-direction: column;
}

.tabs {
  display: flex;
  gap: 8px;
  padding: 16px 24px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.tab-button {
  min-width: 80px;
}

.tab-button.active {
  background: linear-gradient(135deg, #1d4ed8, #2563eb);
  border-color: transparent;
  color: #eff6ff;
}

.sidebar-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sidebar-card {
  padding: 16px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.76);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card-top {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: flex-start;
}

.card-title {
  font-size: 15px;
  line-height: 1.5;
  color: #18283f;
  font-weight: 600;
}

.card-amount {
  flex-shrink: 0;
  color: #10233f;
  font-weight: 700;
}

.card-meta {
  font-size: 14px;
  color: #607189;
}

.full-width {
  width: 100%;
}

.sidebar .secondary-button.full-width {
  min-height: 40px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #6b7b8d;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.quick-panel {
  padding: 16px 24px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  color: #324258;
  font-size: 13px;
  font-weight: 700;
}

.section-count {
  color: #8090a4;
  font-size: 12px;
  font-weight: 600;
}

.scenario-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.scenario-button {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid #d9e1e8;
  border-radius: 6px;
  background: #f8fafb;
  color: #34465b;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}

.scenario-button:hover {
  border-color: #9bb5c8;
  background: #ffffff;
}

.scenario-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.scenario-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #5b7288;
}

.scenario-course .scenario-dot,
.scenario-progress .scenario-dot {
  background: #2b7a78;
}

.scenario-order .scenario-dot,
.scenario-refund .scenario-dot {
  background: #c47a32;
}

.scenario-ticket .scenario-dot {
  background: #8c5d8d;
}

.chat-card,
.sidebar {
  border-radius: 8px;
}

.bubble,
.field input,
.composer input,
.sidebar-card {
  border-radius: 8px;
}

.trace-inline {
  flex-shrink: 0;
  max-height: 40vh;
  display: flex;
  flex-direction: column;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(248, 250, 252, 0.7);
}

.trace-inline-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.trace-inline-title {
  font-size: 12px;
  font-weight: 700;
  color: #4d677e;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.trace-inline-count {
  font-size: 11px;
  color: #8b9bb0;
}

.trace-toggle {
  margin-left: auto;
  font-size: 10px;
  color: #8b9bb0;
}

.trace-empty {
  padding: 16px 24px;
  color: #8b9bb0;
  font-size: 13px;
  text-align: center;
}

.trace-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 0;
}

.trace-item {
  display: flex;
  gap: 8px;
  padding: 0 24px;
  transition: background 0.1s ease;
}

.trace-item:hover {
  background: rgba(0, 0, 0, 0.02);
}

.trace-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 14px;
  flex-shrink: 0;
  padding-top: 8px;
}

.trace-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  z-index: 1;
}

.trace-connector {
  width: 1px;
  flex: 1;
  min-height: 10px;
  background: rgba(148, 163, 184, 0.25);
}

.trace-item:last-child .trace-connector {
  display: none;
}

.trace-content {
  flex: 1;
  min-width: 0;
  padding-bottom: 10px;
  cursor: pointer;
}

.trace-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.trace-badge {
  padding: 1px 7px;
  border-radius: 999px;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.5;
  white-space: nowrap;
}

.trace-time {
  font-size: 10px;
  color: #8b9bb0;
}

.trace-expand-icon {
  margin-left: auto;
  font-size: 12px;
  color: #8b9bb0;
  font-weight: 700;
}

.trace-summary {
  font-size: 12px;
  color: #3f5670;
  line-height: 1.5;
  word-break: break-word;
}

.trace-detail {
  margin-top: 6px;
  padding: 8px 10px;
  background: rgba(241, 245, 249, 0.85);
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  overflow-x: auto;
}

.trace-detail pre {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: #2c405a;
  white-space: pre-wrap;
  word-break: break-all;
}

.trace-state-btn {
  padding: 2px 10px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.7);
  color: #3f5670;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.trace-state-btn:hover {
  background: rgba(255, 255, 255, 0.95);
  border-color: #94a3b8;
}

.trace-full-state {
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  max-height: 300px;
  overflow-y: auto;
}

.trace-full-state-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 24px;
  font-size: 11px;
  font-weight: 700;
  color: #4d677e;
  background: rgba(241, 245, 249, 0.5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.trace-full-state pre {
  margin: 0;
  padding: 12px 24px;
  font-size: 11px;
  line-height: 1.5;
  color: #1e293b;
  white-space: pre-wrap;
  word-break: break-all;
}

@media (max-width: 1180px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .chat-header {
    flex-direction: column;
  }

  .sidebar {
    min-height: auto;
    height: auto;
  }
}

@media (max-width: 720px) {
  .app-shell {
    padding: 0;
  }

  .workspace {
    gap: 0;
  }

  .chat-card,
  .sidebar {
    min-height: auto;
    height: auto;
    border-radius: 0;
    border-left: none;
    border-right: none;
  }

  .chat-card {
    min-height: 100vh;
  }

  .message {
    max-width: 100%;
  }

  .composer,
  .field-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
