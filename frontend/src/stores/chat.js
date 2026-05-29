import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatApi } from '../api/index.js'
import { normalizeAgentTrace, normalizeChatMessage } from './chatTrace.js'

let nextMsgId = 100
let nextTempId = 0

function _tempId() {
  return `__new_${++nextTempId}`
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref([])
  const currentConversationId = ref(null)

  // Per-conversation message cache: convId → Message[]
  const conversationMessages = ref(new Map())

  // Derived: messages for the currently-viewed conversation
  const messages = computed(() => {
    const id = currentConversationId.value
    return conversationMessages.value.get(id) || []
  })

  // Per-conversation streaming state: convId → { content, trace }
  const streamingStates = ref(new Map())
  // Track active SSE readers per conversation (for cancellation)
  const activeStreams = new Map()

  const isStreaming = computed(() => streamingStates.value.has(currentConversationId.value))
  const currentStreamingContent = computed(() => {
    const s = streamingStates.value.get(currentConversationId.value)
    return s?.content || ''
  })
  const currentAgentTrace = computed(() => {
    const s = streamingStates.value.get(currentConversationId.value)
    return s?.trace || null
  })

  const currentConversation = computed(() =>
    conversations.value.find(c => c.id === currentConversationId.value)
  )

  // ── helpers ──

  function _setConvMessages(convId, msgs) {
    conversationMessages.value.set(convId, msgs.map(normalizeChatMessage))
    conversationMessages.value = new Map(conversationMessages.value)
  }

  function _addToConvMessages(convId, msg) {
    const msgs = conversationMessages.value.get(convId) || []
    msgs.push(normalizeChatMessage(msg))
    _setConvMessages(convId, msgs)
  }

  function _setStreamState(convId, state) {
    if (state === null) {
      streamingStates.value.delete(convId)
    } else {
      streamingStates.value.set(convId, state)
    }
    streamingStates.value = new Map(streamingStates.value)
  }

  // ── actions ──

  async function loadConversations() {
    try {
      const data = await chatApi.listConversations()
      conversations.value = data.items || data || []
    } catch (e) { console.error('loadConversations failed:', e.message || e) }
  }

  async function selectConversation(id) {
    currentConversationId.value = id
    if (!id) return
    // If this conversation is actively streaming, use live cache (don't overwrite)
    if (streamingStates.value.has(id)) return
    try {
      const data = await chatApi.getConversation(id)
      _setConvMessages(id, data.messages || data.items || [])
    } catch (e) {
      console.error('selectConversation failed:', e.message || e)
      _setConvMessages(id, [])
    }
  }

  function startNewConversation() {
    currentConversationId.value = null
  }

  async function deleteConversation(id) {
    cancelStream(id)
    try {
      await chatApi.deleteConversation(id)
      conversations.value = conversations.value.filter(c => c.id !== id)
      conversationMessages.value.delete(id)
      conversationMessages.value = new Map(conversationMessages.value)
      if (currentConversationId.value === id) {
        currentConversationId.value = null
      }
    } catch (e) {
      console.error('deleteConversation failed:', e.message || e)
    }
  }

  function cancelStream(convId) {
    const reader = activeStreams.get(convId)
    if (reader) {
      try { reader.cancel() } catch (_) { /* ignore */ }
      activeStreams.delete(convId)
    }
    _setStreamState(convId, null)
  }

  async function sendMessage(content, options = {}) {
    // Use a temp id for new conversations (null is ambiguous as Map key)
    const isNewConversation = !currentConversationId.value
    const convId = currentConversationId.value || _tempId()
    if (isNewConversation) {
      currentConversationId.value = convId
    }
    const userMsg = {
      id: nextMsgId++,
      conversation_id: isNewConversation ? null : currentConversationId.value,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    _addToConvMessages(convId, userMsg)

    // Initialize streaming state for this conversation
    const s = { content: '', trace: null }
    _setStreamState(convId, s)

    const traceMap = new Map()

    try {
      const response = await chatApi.stream({
        message: content,
        conversation_id: isNewConversation ? undefined : currentConversationId.value,
        knowledge_base_ids: options.knowledge_base_ids || undefined,
        use_react: options.use_react ?? true,
      })

      const reader = response.body.getReader()
      activeStreams.set(convId, reader)

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            switch (event.type) {
              case 'token':
                s.content += event.data.content || ''
                _setStreamState(convId, s)
                break
              case 'agent_status': {
                const d = event.data
                if (!traceMap.has(d.agent_name)) {
                  traceMap.set(d.agent_name, {
                    agent: d.agent_name,
                    status: d.status,
                    duration_ms: d.duration_ms,
                    output: d.output_summary,
                  })
                } else {
                  const entry = traceMap.get(d.agent_name)
                  entry.status = d.status
                  entry.duration_ms = d.duration_ms
                  entry.output = d.output_summary
                }
                s.trace = [...traceMap.values()]
                _setStreamState(convId, s)
                break
              }
              case 'tool_call': {
                break
              }
              case 'error': {
                const err = new Error(event.data?.message || 'Stream error')
                err.streamError = true
                throw err
              }
              case 'done': {
                const d = event.data
                const realId = d.conversation_id

                // If this was a new conversation, migrate from temp id to real id
                if (realId && realId !== convId) {
                  const pending = conversationMessages.value.get(convId) || []
                  conversationMessages.value.delete(convId)
                  conversationMessages.value.set(realId, pending)
                  // Migrate streaming state too
                  if (streamingStates.value.has(convId)) {
                    streamingStates.value.set(realId, streamingStates.value.get(convId))
                    streamingStates.value.delete(convId)
                  }
                  // Re-point active stream
                  if (activeStreams.has(convId)) {
                    activeStreams.set(realId, activeStreams.get(convId))
                    activeStreams.delete(convId)
                  }
                  currentConversationId.value = realId
                  conversationMessages.value = new Map(conversationMessages.value)
                }

                const targetId = realId || convId
                const finalTrace = Array.isArray(d.agent_trace) && d.agent_trace.length
                  ? normalizeAgentTrace(d.agent_trace)
                  : normalizeAgentTrace([...traceMap.values()])
                activeStreams.delete(targetId)
                _setStreamState(targetId, null)
                const assistantMsg = {
                  id: nextMsgId++,
                  conversation_id: targetId,
                  role: 'assistant',
                  content: s.content,
                  agent_trace: finalTrace,
                  sources: d.sources || [],
                  token_usage: d.token_usage,
                  quality_score: d.quality_score,
                  created_at: new Date().toISOString(),
                }
                _addToConvMessages(targetId, assistantMsg)
                break
              }
            }
          } catch (e) {
            if (e.streamError) throw e
          }
        }
      }
    } catch (e) {
      const errMsg = {
        id: nextMsgId++,
        conversation_id: currentConversationId.value,
        role: 'assistant',
        content: `请求失败: ${e.message || '未知错误'}`,
        agent_trace: [],
        sources: [],
        created_at: new Date().toISOString(),
      }
      _addToConvMessages(convId, errMsg)
    } finally {
      activeStreams.delete(convId)
      _setStreamState(convId, null)
      // Reload conversation list (title may have changed)
      loadConversations()
    }
  }

  function reset() {
    for (const [convId] of activeStreams) {
      cancelStream(convId)
    }
    conversations.value = []
    currentConversationId.value = null
    conversationMessages.value = new Map()
    streamingStates.value = new Map()
  }

  return {
    conversations, currentConversationId, messages,
    isStreaming, currentStreamingContent, currentAgentTrace, currentConversation,
    loadConversations, selectConversation, startNewConversation,
    deleteConversation, sendMessage, reset,
  }
})
