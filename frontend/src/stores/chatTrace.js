export function normalizeAgentTrace(trace) {
  if (!Array.isArray(trace)) return trace

  return trace.map((item) => {
    const agent = item.agent || item.agent_name || 'unknown'
    const error = item.error || item.error_message
    const status = item.status || (error ? 'failed' : 'completed')
    const output = item.output ?? item.output_summary ?? item.output_state?.summary

    return {
      agent,
      status,
      duration_ms: item.duration_ms,
      output,
      error,
    }
  })
}

export function normalizeChatMessage(message) {
  if (!message || !Array.isArray(message.agent_trace)) return message
  return {
    ...message,
    agent_trace: normalizeAgentTrace(message.agent_trace),
  }
}
