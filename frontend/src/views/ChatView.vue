<script setup>
import { ref, nextTick, watch, computed, onMounted } from 'vue'
import { useChatStore } from '../stores/chat.js'
import { useKnowledgeBaseStore } from '../stores/knowledgeBase.js'

const chatStore = useChatStore()
const kbStore = useKnowledgeBaseStore()

onMounted(async () => {
  await chatStore.loadConversations()
  await kbStore.loadKnowledgeBases()
  selectedKBs.value = kbStore.knowledgeBases.map(kb => kb.id)
})

const inputText = ref('')
const selectedKBs = ref([])
const useReact = ref(true)
const messagesEl = ref(null)
const showKbSelector = ref(false)

const expandedSource = ref(null)
const sourcesShowAll = ref(new Set())

function toggleSource(msgId, idx) {
  const key = `${msgId}-${idx}`
  expandedSource.value = expandedSource.value === key ? null : key
}

function isSourceExpanded(msgId, idx) {
  return expandedSource.value === `${msgId}-${idx}`
}

function toggleShowAll(msgId) {
  const s = new Set(sourcesShowAll.value)
  s.has(msgId) ? s.delete(msgId) : s.add(msgId)
  sourcesShowAll.value = s
}

function renderMarkdown(text) {
  let t = text.trim()
  t = t.replace(/^```\w*\n?/, '').replace(/\n?```$/, '')
  let html = t
    .replace(/### /g, '<h3>').replace(/## /g, '<h2>').replace(/# /g, '<h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n- (.+)/g, '\n<li>$1</li>')
    .replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
    .replace(/\n\n/g, '</p><p>')
  html = '<p>' + html + '</p>'
  html = html
    .replace(/<ul>\n<li>/g, '<ul><li>').replace(/<\/li>\n<\/ul>/g, '</li></ul>')
    .replace(/\n/g, '<br>')
  return html
}

const agentNames = { planner: '规划', retriever: '检索', analyzer: '分析', critic: '评估', reporter: '生成' }

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || chatStore.isStreaming) return
  inputText.value = ''
  await chatStore.sendMessage(text, { knowledge_base_ids: selectedKBs.value, use_react: useReact.value })
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

function handleNewChat() {
  chatStore.startNewConversation()
}

async function handleDeleteConv(id, event) {
  event.stopPropagation()
  if (!confirm('确定要删除该对话吗？')) return
  await chatStore.deleteConversation(id)
}

function statusBadge(status) {
  return status === 'completed' ? 'badge-success' : status === 'failed' ? 'badge-danger' : 'badge-info'
}

function statusText(status) {
  return status === 'completed' ? '完成' : status === 'failed' ? '失败' : '进行中'
}
</script>

<template>
  <div class="chat-layout">
    <!-- Conversation Sidebar -->
    <div class="chat-sidebar">
      <button class="btn-primary new-chat-btn" @click="handleNewChat">+ 新建对话</button>
      <div class="conv-list">
        <div
          v-for="conv in chatStore.conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === chatStore.currentConversationId }"
          @click="chatStore.selectConversation(conv.id)"
        >
          <div class="conv-info">
            <div class="conv-title">{{ conv.title }}</div>
            <div class="conv-meta">{{ conv.created_at.slice(0, 10) }}</div>
          </div>
          <button class="conv-delete-btn" @click="handleDeleteConv(conv.id, $event)" title="删除对话">×</button>
        </div>
      </div>
    </div>

    <!-- Chat Area -->
    <div class="chat-main">
      <!-- Messages -->
      <div class="messages-area" ref="messagesEl">
        <div v-if="chatStore.messages.length === 0" class="empty-state">
          <div class="icon">💬</div>
          <div class="text">开始一段新的科研对话</div>
        </div>

        <div v-for="msg in chatStore.messages" :key="msg.id">
          <!-- User message -->
          <div v-if="msg.role === 'user'" class="message-row user-row">
            <div class="message-bubble user-bubble">{{ msg.content }}</div>
          </div>

          <!-- Assistant message -->
          <div v-if="msg.role === 'assistant'" class="message-row assistant-row">
            <!-- Agent Trace -->
            <div v-if="msg.agent_trace" class="agent-trace">
              <div class="trace-header">🔍 Agent 执行过程</div>
              <div class="trace-pipeline">
                <div
                  v-for="(agent, i) in msg.agent_trace"
                  :key="i"
                  class="trace-step"
                >
                  <div class="trace-node">
                    <span class="trace-dot" :class="agent.status"></span>
                    <span class="trace-name">{{ agentNames[agent.agent] || agent.agent }}</span>
                  </div>
                  <span v-if="i < msg.agent_trace.length - 1" class="trace-arrow">→</span>
                </div>
              </div>
              <div class="trace-details">
                <div v-for="agent in msg.agent_trace" :key="agent.agent" class="trace-detail-row">
                  <span :class="'badge ' + statusBadge(agent.status)">{{ statusText(agent.status) }}</span>
                  <span class="trace-agent-label">{{ agentNames[agent.agent] || agent.agent }}</span>
                  <span v-if="agent.duration_ms" class="trace-duration">{{ (agent.duration_ms / 1000).toFixed(1) }}s</span>
                </div>
              </div>
            </div>

            <!-- Message Content -->
            <div class="message-bubble assistant-bubble">
              <div class="markdown-content" v-html="renderMarkdown(msg.content)"></div>

              <!-- Sources -->
              <div v-if="msg.sources && msg.sources.length" class="sources-section">
                <div class="sources-title">引用来源 ({{ msg.sources.length }} 条)</div>
                <template v-for="(src, idx) in msg.sources" :key="src.doc_id">
                  <div v-if="idx < 8 || sourcesShowAll.has(msg.id)" class="source-item" @click="toggleSource(msg.id, idx)">
                    <div class="source-header">
                      <span class="source-relevance">{{ ((src.relevance_score ?? src.relevance ?? 0) * 100).toFixed(0) }}%</span>
                      <span class="source-title">{{ src.title }}</span>
                      <span class="source-expand-icon">{{ isSourceExpanded(msg.id, idx) ? '▾' : '▸' }}</span>
                    </div>
                    <div v-if="isSourceExpanded(msg.id, idx) && src.content" class="source-full">{{ src.content }}</div>
                    <div v-else-if="src.content" class="source-preview">{{ src.content.slice(0, 120) }}{{ src.content.length > 120 ? '...' : '' }}</div>
                  </div>
                </template>
                <button v-if="msg.sources.length > 8" class="source-toggle-btn" @click="toggleShowAll(msg.id)">
                  {{ sourcesShowAll.has(msg.id) ? '收起' : '展示全部 ' + msg.sources.length + ' 条引用' }}
                </button>
              </div>

              <!-- Token usage -->
              <div v-if="msg.token_usage?.total_tokens" class="token-usage">
                消耗 {{ msg.token_usage.total_tokens?.toLocaleString() ?? '0' }} tokens
                (输入 {{ msg.token_usage.prompt_tokens?.toLocaleString() ?? '0' }} + 输出 {{ msg.token_usage.completion_tokens?.toLocaleString() ?? '0' }})
              </div>
            </div>
          </div>
        </div>

        <!-- Streaming indicator -->
        <div v-if="chatStore.isStreaming" class="message-row assistant-row">
          <div class="message-bubble assistant-bubble">
            <div class="markdown-content">{{ chatStore.currentStreamingContent }}<span class="cursor-blink">▌</span></div>
          </div>
        </div>
      </div>

      <!-- Input Area -->
      <div class="input-area">
        <div v-if="showKbSelector" class="kb-selector">
          <span class="kb-select-label">知识库（默认全选，可取消排除）：</span>
          <label v-for="kb in kbStore.knowledgeBases" :key="kb.id" class="kb-checkbox">
            <input type="checkbox" :value="kb.id" v-model="selectedKBs" />
            {{ kb.name }}
          </label>
        </div>
        <div class="input-row">
          <button class="btn-ghost btn-sm" @click="showKbSelector = !showKbSelector" :title="kbStore.knowledgeBases.length ? '默认全选 ' + kbStore.knowledgeBases.length + ' 个知识库' : '暂无知识库'">
            📚 {{ selectedKBs.length === kbStore.knowledgeBases.length && kbStore.knowledgeBases.length > 0 ? '全部' : selectedKBs.length || '' }}
          </button>
          <label class="react-toggle" title="启用 ReAct 模式，LLM 可自主决定调用哪些搜索工具">
            <input type="checkbox" v-model="useReact" />
            <span class="react-label">🤖 ReAct</span>
          </label>
          <input
            v-model="inputText"
            class="chat-input"
            placeholder="输入科研问题，例如：帮我分析遥感小目标检测的最近进展..."
            @keydown.enter="handleSend"
            :disabled="chatStore.isStreaming"
          />
          <button class="btn-primary" @click="handleSend" :disabled="chatStore.isStreaming || !inputText.trim()">
            {{ chatStore.isStreaming ? '生成中...' : '发送' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-layout { display: flex; height: 100%; }

/* Sidebar */
.chat-sidebar {
  width: 260px; background: var(--bg-sidebar); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; flex-shrink: 0;
}
.new-chat-btn { margin: 12px; }
.conv-list { flex: 1; overflow-y: auto; }
.conv-item {
  padding: 12px 16px; cursor: pointer; border-bottom: 1px solid var(--border);
  transition: background 0.1s; display: flex; align-items: center;
  justify-content: space-between; gap: 8px;
}
.conv-item:hover { background: var(--bg-hover); }
.conv-item.active { background: var(--accent-bg); border-left: 3px solid var(--accent); }
.conv-info { min-width: 0; flex: 1; }
.conv-title { font-size: 13px; font-weight: 500; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.conv-delete-btn {
  flex-shrink: 0; width: 22px; height: 22px; padding: 0;
  border-radius: 50%; border: none; background: transparent;
  color: var(--text-muted); font-size: 16px; line-height: 1;
  cursor: pointer; transition: all 0.1s; display: none;
}
.conv-item:hover .conv-delete-btn { display: block; }
.conv-delete-btn:hover { background: #fee2e2; color: #dc2626; }

/* Main */
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.messages-area { flex: 1; overflow-y: auto; padding: 20px 24px; }

.message-row { margin-bottom: 20px; display: flex; }
.user-row { justify-content: flex-end; }
.assistant-row { flex-direction: column; }

.message-bubble {
  max-width: 85%; padding: 14px 18px; border-radius: 12px; line-height: 1.7;
}
.user-bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.assistant-bubble {
  background: var(--bg-card); border: 1px solid var(--border);
  border-bottom-left-radius: 4px; font-size: 14px;
}

/* Agent Trace */
.agent-trace { margin-bottom: 12px; }
.trace-header { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; }
.trace-pipeline { display: flex; align-items: center; gap: 4px; margin-bottom: 10px; flex-wrap: wrap; }
.trace-step { display: flex; align-items: center; gap: 4px; }
.trace-node {
  display: flex; align-items: center; gap: 4px; padding: 3px 8px;
  background: var(--bg-hover); border-radius: 6px; font-size: 11px;
}
.trace-dot { width: 6px; height: 6px; border-radius: 50%; }
.trace-dot.completed { background: var(--success); }
.trace-dot.failed { background: var(--danger); }
.trace-dot.started { background: var(--warning); animation: pulse 1s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.trace-name { color: var(--text-secondary); }
.trace-arrow { color: var(--text-muted); font-size: 10px; }
.trace-details { display: flex; gap: 12px; flex-wrap: wrap; }
.trace-detail-row { display: flex; align-items: center; gap: 4px; font-size: 11px; }
.trace-agent-label { color: var(--text-muted); }
.trace-duration { color: var(--text-muted); }

/* Sources */
.sources-section { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
.sources-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; }
.source-item {
  font-size: 12px; color: var(--text-secondary); margin: 6px 0;
  padding: 6px 8px; background: var(--bg-hover); border-radius: 6px;
  cursor: pointer; transition: background 0.1s;
}
.source-item:hover { background: var(--accent-bg); }
.source-header { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }
.source-relevance {
  color: var(--accent); font-weight: 600; font-size: 11px;
  background: var(--accent-bg); padding: 1px 5px; border-radius: 4px; white-space: nowrap;
}
.source-title { font-size: 11px; color: var(--text-primary); font-weight: 500; flex: 1; }
.source-expand-icon { font-size: 10px; color: var(--text-muted); flex-shrink: 0; }
.source-preview {
  font-size: 11px; color: var(--text-muted); line-height: 1.4;
  padding-left: 2px; margin-top: 2px;
}
.source-full {
  font-size: 11px; color: var(--text-secondary); line-height: 1.5;
  padding: 6px 0 2px 2px; white-space: pre-wrap; word-break: break-word;
  max-height: 200px; overflow-y: auto;
}
.source-toggle-btn {
  display: block; width: 100%; margin-top: 6px; padding: 4px 0;
  font-size: 11px; color: var(--accent); background: none; border: none;
  cursor: pointer; text-align: center;
}
.source-toggle-btn:hover { text-decoration: underline; }

/* Token usage */
.token-usage { margin-top: 10px; font-size: 11px; color: var(--text-muted); }

/* Input */
.input-area { padding: 12px 24px 16px; border-top: 1px solid var(--border); background: var(--bg-card); }
.kb-selector {
  display: flex; align-items: center; gap: 12px; padding: 6px 0;
  font-size: 12px; color: var(--text-secondary);
}
.kb-select-label { font-weight: 600; }
.kb-checkbox { display: flex; align-items: center; gap: 4px; cursor: pointer; }
.input-row { display: flex; gap: 8px; align-items: center; }
.react-toggle {
  display: flex; align-items: center; gap: 4px; cursor: pointer;
  font-size: 12px; color: var(--text-secondary); white-space: nowrap;
  user-select: none;
}
.react-toggle input { cursor: pointer; }
.react-label { opacity: 0.7; }
.react-toggle:has(input:checked) .react-label { opacity: 1; color: var(--accent); }
.chat-input {
  flex: 1; padding: 10px 14px; font-size: 14px;
  border-radius: 20px; border: 1px solid var(--border);
}

.cursor-blink { animation: blink 1s step-end infinite; color: var(--accent); }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
</style>
