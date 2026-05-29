// ── Conversations ──────────────────────────────────────

export const mockConversations = [
  { id: 1, thread_id: 'th-001', title: '遥感小目标检测创新方向分析', status: 'active',
    created_at: '2026-05-13T10:00:00Z', updated_at: '2026-05-13T10:05:00Z' },
  { id: 2, thread_id: 'th-002', title: 'Transformer注意力机制综述', status: 'active',
    created_at: '2026-05-12T14:30:00Z', updated_at: '2026-05-12T14:45:00Z' },
  { id: 3, thread_id: 'th-003', title: '小样本学习在医学图像中的应用', status: 'archived',
    created_at: '2026-05-10T09:00:00Z', updated_at: '2026-05-10T09:20:00Z' },
]

// ── Agent trace (simulated workflow) ───────────────────

export const mockAgentTrace = [
  { agent: 'Planner', status: 'completed', duration_ms: 1200,
    output: { task_plan: [
      { id: '1', description: '检索遥感小目标检测最新论文', status: 'done' },
      { id: '2', description: '分析每篇论文的创新方法', status: 'done' },
      { id: '3', description: '横向对比提炼研究方向', status: 'done' },
      { id: '4', description: '生成研究报告', status: 'done' }
    ]}
  },
  { agent: 'Retriever', status: 'completed', duration_ms: 3500,
    tool_calls: [
      { tool: 'arxiv_search', args: { query: 'small object detection remote sensing 2025' }, results_count: 8 },
      { tool: 'rag_retriever', args: { query: '遥感小目标检测 注意力机制' }, results_count: 12 },
    ]
  },
  { agent: 'Analyzer', status: 'completed', duration_ms: 8000,
    output: { key_findings: [
      '多尺度特征融合是当前主流方向，FPN变体占据40%以上论文',
      '注意力机制改进（Spatial-Channel Attention）显著提升小目标召回率',
      '扩散模型在数据增强方面展现出新潜力',
      '轻量化检测头设计成为边缘部署的关键'
    ]}
  },
  { agent: 'Critic', status: 'completed', duration_ms: 2000,
    output: { quality_score: 0.85, revision_needed: false }
  },
  { agent: 'Reporter', status: 'completed', duration_ms: 5000 },
]

// ── Chat messages ───────────────────────────────────────

export const mockMessages = [
  { id: 1, conversation_id: 1, role: 'user',
    content: '帮我分析遥感目标检测中的小目标检测方向',
    created_at: '2026-05-13T10:00:00Z' },
  { id: 2, conversation_id: 1, role: 'assistant',
    content: `## 遥感小目标检测创新方向分析

### 1. 多尺度特征融合

当前遥感小目标检测的核心挑战在于**深层特征图空间分辨率不足**导致小目标特征消失。主要的改进方向包括：

- **FPN变体**：PANet、BiFPN、NAS-FPN等通过跨尺度连接增强小目标特征表达
- **高分辨率特征保持**：HRNet系列保持高分辨率表示贯穿整个网络
- **特征金字塔注意力**：在FPN中嵌入注意力模块，动态调整不同层级的贡献权重

### 2. 注意力机制改进

- **Spatial-Channel Attention**：同时在空间和通道维度建模，增强小目标响应
- **Transformer-based Detector**：DETR及其变体（Deformable DETR、DINO）利用全局注意力捕获小目标
- **Criss-Cross Attention**：在保持计算效率的同时获取全局上下文

### 3. 数据增强与生成

- **扩散模型生成**：利用Stable Diffusion生成小目标样本，缓解类别不平衡
- **Copy-Paste增强**：将小目标实例复制到不同背景中，提升检测器鲁棒性
- **多尺度训练**：动态调整输入分辨率，迫使模型学习尺度不变特征

### 4. 轻量化部署

- **知识蒸馏**：从大型检测器蒸馏小目标检测能力到轻量模型
- **检测头解耦**：分类与回归解耦，减少小目标定位误差
- **动态推理**：根据输入分辨率自适应调整计算图`,
    agent_trace: mockAgentTrace,
    sources: [
      { doc_id: 1, title: 'Multi-Scale Feature Fusion for Tiny Object Detection in UAV Imagery', relevance: 0.92 },
      { doc_id: 2, title: 'Attention Mechanisms Meet Small Object Detection: A Survey', relevance: 0.88 },
      { doc_id: 5, title: 'Diffusion Models for Data Augmentation in Remote Sensing', relevance: 0.85 },
    ],
    token_usage: { prompt_tokens: 3200, completion_tokens: 1500, total_tokens: 4700 },
    created_at: '2026-05-13T10:05:00Z'
  },
]

// ── Knowledge Bases ─────────────────────────────────────

export const mockKnowledgeBases = [
  { id: 1, name: '遥感目标检测论文库', description: '收集遥感图像目标检测相关论文，涵盖SAR、光学、多光谱等方向',
    collection_name: 'kb_1', doc_count: 156, chunk_count: 4820, created_at: '2026-04-15T08:00:00Z' },
  { id: 2, name: 'Transformer架构文献', description: 'Transformer、注意力机制在CV领域应用的经典与前沿论文',
    collection_name: 'kb_2', doc_count: 89, chunk_count: 3120, created_at: '2026-04-20T10:00:00Z' },
  { id: 3, name: '小样本学习研究', description: 'Few-shot、Zero-shot学习在医学图像、遥感等领域的应用',
    collection_name: 'kb_3', doc_count: 45, chunk_count: 1680, created_at: '2026-05-01T14:00:00Z' },
]

export const mockDocuments = {
  1: [
    { id: 1, filename: 'towards-tiny-object-detection-2025.pdf', file_type: 'pdf',
      file_size_bytes: 3200000, ingestion_status: 'done', created_at: '2026-04-15T09:00:00Z' },
    { id: 2, filename: 'attention-survey-2024.pdf', file_type: 'pdf',
      file_size_bytes: 5600000, ingestion_status: 'done', created_at: '2026-04-16T11:00:00Z' },
    { id: 3, filename: 'diffusion-augmentation-2025.pdf', file_type: 'pdf',
      file_size_bytes: 4100000, ingestion_status: 'embedding', created_at: '2026-05-12T15:00:00Z' },
    { id: 4, filename: 'lightweight-detector-design.docx', file_type: 'docx',
      file_size_bytes: 1800000, ingestion_status: 'parsing', created_at: '2026-05-13T08:00:00Z' },
    { id: 5, filename: 'sar-ship-detection-2025.pdf', file_type: 'pdf',
      file_size_bytes: 7200000, ingestion_status: 'pending', created_at: '2026-05-13T09:30:00Z' },
    { id: 6, filename: 'failed-paper-corrupted.pdf', file_type: 'pdf',
      file_size_bytes: 500000, ingestion_status: 'failed', ingestion_error: 'PDF解析失败：文件损坏或加密',
      created_at: '2026-05-10T12:00:00Z' },
  ],
  2: [
    { id: 10, filename: 'transformer-is-all-you-need.pdf', file_type: 'pdf',
      file_size_bytes: 2100000, ingestion_status: 'done', created_at: '2026-04-20T10:30:00Z' },
    { id: 11, filename: 'swin-transformer-v2.pdf', file_type: 'pdf',
      file_size_bytes: 4500000, ingestion_status: 'done', created_at: '2026-04-21T09:00:00Z' },
  ],
  3: [
    { id: 20, filename: 'few-shot-medical-image-2025.pdf', file_type: 'pdf',
      file_size_bytes: 3800000, ingestion_status: 'done', created_at: '2026-05-01T15:00:00Z' },
  ]
}

// ── Reports ─────────────────────────────────────────────

export const mockReports = [
  { id: 1, title: '遥感小目标检测创新方向分析报告', status: 'completed',
    content: `## 遥感小目标检测创新方向分析报告

> 生成时间：2026-05-13 | 分析论文数：20篇 | 质量评分：0.85

### 1. 研究背景

遥感图像中的小目标检测是计算机视觉领域的核心挑战之一。小目标通常指分辨率小于32×32像素的物体，在遥感场景中占比极高但检测准确率远低于大中目标。

### 2. 核心发现

#### 2.1 多尺度特征融合（被引最多的方向）
- FPN变体占据该领域40%以上的近期论文
- BiFPN通过加权双向融合提升小目标AP约3-5个百分点
- HRNet保持高分辨率表示的方式在遥感场景中表现优异

#### 2.2 注意力机制改进
- Spatial-Channel联合注意力是当前最优方案之一
- Deformable DETR在遥感小目标上超越了传统Anchor-based方法
- 计算效率与全局感受野的平衡仍是开放问题

#### 2.3 新兴方向
- 扩散模型数据增强在极端小目标场景中提升显著（+8% AP@S）
- 基于CLIP的开放词汇检测开始进入遥感领域

### 3. 结论与建议

未来12个月最值得关注的方向是多尺度特征融合与注意力机制的结合，以及扩散模型在数据增强中的规模化应用。`,
    sources: [
      { title: 'Multi-Scale Feature Fusion for Tiny Object Detection in UAV Imagery', url: 'https://arxiv.org/abs/2501.01234' },
      { title: 'Attention Mechanisms Meet Small Object Detection: A Survey', url: 'https://arxiv.org/abs/2412.05678' },
    ],
    created_at: '2026-05-13T10:30:00Z' },
  { id: 2, title: 'Transformer在CV领域的应用综述', status: 'completed',
    content: `## Transformer在CV领域的应用综述\n\n### 1. 从ViT到Swin\n\n...`,
    sources: [{ title: 'Swin Transformer V2: Scaling Up Capacity and Resolution', url: 'https://arxiv.org/abs/2111.09883' }],
    created_at: '2026-05-10T14:00:00Z' },
  { id: 3, title: '小样本医学图像分割方法对比', status: 'draft',
    content: `## 小样本医学图像分割\n\n> 状态：撰写中...`,
    sources: [],
    created_at: '2026-05-12T09:00:00Z' },
]

// ── Workflow Tasks ──────────────────────────────────────

export const mockWorkflowTasks = [
  { task_id: 'task-001', task_type: 'parse_document', status: 'processing',
    progress: { step: 'embedding', percent: 65, message: '正在向量化... (chunk 45/70)' },
    created_at: '2026-05-13T10:30:00Z', estimated_remaining_seconds: 12 },
  { task_id: 'task-002', task_type: 'generate_report', status: 'processing',
    progress: { step: 'analyzing', percent: 30, message: 'Analyzer 分析中...' },
    created_at: '2026-05-13T10:32:00Z', estimated_remaining_seconds: 120 },
  { task_id: 'task-003', task_type: 'batch_search', status: 'completed',
    progress: { percent: 100, message: '搜索完成，返回45篇论文' },
    created_at: '2026-05-13T10:28:00Z', estimated_remaining_seconds: 0 },
  { task_id: 'task-004', task_type: 'parse_document', status: 'failed',
    progress: { percent: 12, message: 'PDF解析失败：文件损坏或加密' },
    created_at: '2026-05-13T10:25:00Z', estimated_remaining_seconds: 0 },
]

// ── Agent Executions ────────────────────────────────────

export const mockAgentExecutions = [
  { id: 1, conversation_id: 1, agent_name: 'Planner', status: 'completed',
    duration_ms: 1200, token_usage: { prompt_tokens: 200, completion_tokens: 300, total_tokens: 500 },
    tool_calls: [], created_at: '2026-05-13T10:00:01Z' },
  { id: 2, conversation_id: 1, agent_name: 'Retriever', status: 'completed',
    duration_ms: 3500, token_usage: { prompt_tokens: 500, completion_tokens: 200, total_tokens: 700 },
    tool_calls: ['arxiv_search', 'rag_retriever'], created_at: '2026-05-13T10:00:03Z' },
  { id: 3, conversation_id: 1, agent_name: 'Analyzer', status: 'completed',
    duration_ms: 8000, token_usage: { prompt_tokens: 2000, completion_tokens: 1000, total_tokens: 3000 },
    tool_calls: [], created_at: '2026-05-13T10:00:08Z' },
  { id: 4, conversation_id: 1, agent_name: 'Critic', status: 'completed',
    duration_ms: 2000, token_usage: { prompt_tokens: 1000, completion_tokens: 300, total_tokens: 1300 },
    tool_calls: [], created_at: '2026-05-13T10:00:16Z' },
  { id: 5, conversation_id: 1, agent_name: 'Reporter', status: 'completed',
    duration_ms: 5000, token_usage: { prompt_tokens: 2500, completion_tokens: 1500, total_tokens: 4000 },
    tool_calls: ['report_generator'], created_at: '2026-05-13T10:00:18Z' },
  { id: 6, conversation_id: 2, agent_name: 'Planner', status: 'failed',
    duration_ms: 300, token_usage: { prompt_tokens: 200, completion_tokens: 0, total_tokens: 200 },
    error_message: 'LLM API timeout', created_at: '2026-05-13T09:00:00Z' },
]
