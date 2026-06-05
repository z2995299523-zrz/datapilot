/**
 * 需求分析页 — 全链路: 概念提取 → 检索 → 伪代码 → SQL
 */

import { useState } from 'react';
import {
  Typography,
  Input,
  Button,
  Collapse,
  Tag,
  Spin,
  Alert,
  Checkbox,
  Upload,
  Space,
  message,
} from 'antd';
import {
  RocketOutlined,
  DownloadOutlined,
  UploadOutlined,
} from '@ant-design/icons';

import { analysisApi, type AnalysisResult } from '../api/analysis';
import SqlCodeBlock from '../components/SqlCodeBlock';

const { Title, Text } = Typography;
const { TextArea } = Input;

// ---------- concept type colors ----------
const typeColors: Record<string, string> = {
  entity: 'volcano',
  dimension: 'blue',
  time_range: 'purple',
  metric: 'green',
  condition: 'orange',
};

export default function AnalysisPage() {
  const [reqText, setReqText] = useState('');
  const [generateSql, setGenerateSql] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const handleRun = async () => {
    if (!reqText.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const cached = sessionStorage.getItem('data_dict_path') || undefined;
      const res = await analysisApi.full(reqText, generateSql, cached);
      setResult(res);
      if (res.error) {
        message.warning(res.error);
      } else {
        message.success('分析完成');
      }
    } catch (e: unknown) {
      message.error(`分析失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLoading(false);
  };

  // ---------- Extract display helpers ----------
  const extraction = result?.extraction as Record<string, unknown> | null;
  const concepts = (extraction?.concepts as Array<Record<string, unknown>>) || [];
  const retrieval = result?.retrieval as Record<string, unknown> | null;
  const matches = (retrieval?.matches as Array<Record<string, unknown>>) || [];
  const unmatched = (retrieval?.unmatched_concepts as string[]) || [];
  const pseudocode = result?.pseudocode as Record<string, unknown> | null;
  const steps = (pseudocode?.steps as Array<Record<string, unknown>>) || [];
  const todos = (pseudocode?.todo_items as string[]) || [];
  const notes = (pseudocode?.notes as string[]) || [];

  return (
    <div>
      <Title level={3} style={{ color: '#E0E3E8', marginBottom: 8 }}>
        需求分析
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
        输入业务需求文档，自动完成概念提取 → 分层检索 → 伪代码生成 → SQL 生成
      </Text>

      {/* Input */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
        <TextArea
          rows={6}
          placeholder="例如：统计近6个月各渠道的活跃客户数及交易金额，按渠道类型分组展示..."
          value={reqText}
          onChange={(e) => setReqText(e.target.value)}
          style={{ flex: 1 }}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 180 }}>
          <Upload accept=".txt,.md,.docx" maxCount={1} showUploadList={false}
            beforeUpload={(file) => {
              const reader = new FileReader();
              reader.onload = (e) => setReqText(e.target?.result as string);
              reader.readAsText(file, 'UTF-8');
              return false;
            }}
          >
            <Button icon={<UploadOutlined />} block>上传需求文档</Button>
          </Upload>
          <Checkbox checked={generateSql} onChange={(e) => setGenerateSql(e.target.checked)}>
            生成 SQL 脚本
          </Checkbox>
          <Button
            type="primary"
            icon={<RocketOutlined />}
            onClick={handleRun}
            loading={loading}
            disabled={!reqText.trim()}
            size="large"
            block
          >
            开始分析
          </Button>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="正在分析中，LLM 可能需要 10-30 秒..." />
        </div>
      )}

      {result?.error && !result.extraction && (
        <Alert type="error" title={result.error} style={{ marginBottom: 16 }} showIcon />
      )}

      {/* Results */}
      {extraction && (
        <Collapse
          defaultActiveKey={['step1', 'step2', 'step3', 'step4']}
          style={{ marginTop: 8 }}
          items={[
            // Step 1: Concepts
            {
              key: 'step1',
              label: (
                <span>
                  📊 步骤 1/3: 提取到 <Tag>{concepts.length}</Tag> 个业务概念
                </span>
              ),
              children: (
                <div>
                  {concepts.map((c, i) => (
                    <div key={i} style={{ marginBottom: 8 }}>
                      <Tag color={typeColors[c.type as string] || 'default'}>
                        {(c.type as string)?.toUpperCase()}
                      </Tag>
                      <Text strong>{c.concept as string}</Text>
                      {(c.qualifier as string) && (
                        <Text type="secondary" style={{ marginLeft: 8 }}>
                          限定: {c.qualifier as string}
                        </Text>
                      )}
                      {(c.candidates as string[])?.length > 0 && (
                        <Text type="secondary" style={{ marginLeft: 8 }}>
                          → {(c.candidates as string[]).join(', ')}
                        </Text>
                      )}
                    </div>
                  ))}
                  {concepts.length === 0 && <Text type="secondary">无概念提取</Text>}
                </div>
              ),
            },
            // Step 2: Retrieval
            {
              key: 'step2',
              label: (
                <span>
                  🔍 步骤 2/3: 匹配{' '}
                  <Tag>{matches.filter((m) => m.matched).length}</Tag> / {matches.length}
                  {unmatched.length > 0 && (
                    <Tag color="error">{unmatched.length} 未匹配</Tag>
                  )}
                </span>
              ),
              children: (
                <div>
                  {matches.map((m, i) => (
                    <Alert
                      key={i}
                      type={m.matched ? 'success' : 'warning'}
                      message={
                        <span>
                          {m.matched ? (
                            <>
                              <Tag>{(m.layer as string) || '?'}层</Tag>
                              <Text strong>{m.table_name as string}</Text>
                              <Text type="secondary">
                                {' '}
                                (score={(m.score as number)?.toFixed(2)})
                              </Text>
                            </>
                          ) : (
                            <>
                              未匹配: <Text strong>{m.concept as string}</Text> — {m.message as string}
                            </>
                          )}
                        </span>
                      }
                      style={{ marginBottom: 4 }}
                    />
                  ))}
                  {unmatched.length > 0 && (
                    <Alert
                      type="error"
                      message={`待确认: ${unmatched.join(', ')}`}
                      style={{ marginTop: 8 }}
                    />
                  )}
                </div>
              ),
            },
            // Step 3: Pseudocode
            {
              key: 'step3',
              label: (
                <span>
                  📝 步骤 3/3: {pseudocode?.title as string || '分析伪代码'}
                </span>
              ),
              children: (
                <div>
                  {steps.map((step, i) => (
                    <div key={i} style={{ marginBottom: 12 }}>
                      <Text strong>
                        步骤 {(step.step_number as number) || i + 1}:{' '}
                        {step.description as string}
                      </Text>
                      <div style={{ marginLeft: 16, marginTop: 4 }}>
                        {(step.source_table as string) && (
                          <div>
                            <Text type="secondary">源表: </Text>
                            <Tag>{step.source_table as string}</Tag>
                          </div>
                        )}
                        {(step.conditions as string[])?.map((c, j) => (
                          <div key={j}>
                            <Text type="secondary">条件: </Text>
                            <Text code>{c}</Text>
                          </div>
                        ))}
                        {(step.joins as string[])?.map((j, k) => (
                          <div key={k}>
                            <Text type="secondary">关联: </Text>
                            <Text code>{j}</Text>
                          </div>
                        ))}
                        {(step.aggregations as string[])?.map((a, l) => (
                          <div key={l}>
                            <Text type="secondary">聚合: </Text>
                            <Text code>{a}</Text>
                          </div>
                        ))}
                        {(step.output as string) && (
                          <div>
                            <Text type="secondary">输出: </Text>
                            {step.output as string}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {todos.length > 0 && (
                    <Alert
                      type="warning"
                      message="待确认"
                      description={todos.map((t, i) => <div key={i}>• {t}</div>)}
                      style={{ marginTop: 8 }}
                    />
                  )}
                  {notes.length > 0 && (
                    <Alert
                      type="info"
                      message="备注"
                      description={notes.map((n, i) => <div key={i}>• {n}</div>)}
                      style={{ marginTop: 8 }}
                    />
                  )}
                </div>
              ),
            },
            // Step 4: SQL
            ...(result?.sql
              ? [
                  {
                    key: 'step4',
                    label: <span>💾 SQL 脚本（CTE 链式）</span>,
                    children: (
                      <div>
                        <SqlCodeBlock sql={result.sql} />
                        <div style={{ marginTop: 12 }}>
                          <Space>
                            <Button
                              icon={<DownloadOutlined />}
                              onClick={() => {
                                const blob = new Blob([result.sql], { type: 'text/plain' });
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = 'analysis.sql';
                                a.click();
                                URL.revokeObjectURL(url);
                              }}
                            >
                              下载 SQL 脚本
                            </Button>
                          </Space>
                        </div>
                      </div>
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}
    </div>
  );
}
