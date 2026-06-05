/**
 * 修复闭环页 — SQL 测试 → 诊断 → 修复 → 重测
 */

import { useState } from 'react';
import {
  Typography,
  Input,
  InputNumber,
  Button,
  Collapse,
  Timeline,
  Tag,
  Spin,
  Alert,
  Space,
  Upload,
  message,
  Card,
  Table,
  Result,
} from 'antd';
import {
  BugOutlined,
  UploadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons';

import { reconciliationApi, type ReconciliationResult } from '../api/reconciliation';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function ReconciliationPage() {
  const [sql, setSql] = useState('');
  const [reqText, setReqText] = useState('');
  const [maxLoops, setMaxLoops] = useState(3);
  const [dbConn, setDbConn] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ReconciliationResult | null>(null);

  const handleRun = async () => {
    if (!sql.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const dictPath = sessionStorage.getItem('data_dict_path') || undefined;
      const res = await reconciliationApi.run({
        original_sql: sql,
        requirement_text: reqText,
        db_conn_str: dbConn,
        max_loops: maxLoops,
        dict_path: dictPath || null,
      });
      setResult(res);

      if (res.status === 'dry_run') {
        message.info('未连接数据库 — 仅展示流程预览');
      } else if (res.status === 'passed') {
        message.success(`全部通过！共执行 ${res.loop_count} 轮修复`);
      } else if (res.status === 'error') {
        message.error(res.error_message);
      } else {
        message.warning(`状态: ${res.status}，共 ${res.loop_count} 轮`);
      }
    } catch (e: unknown) {
      message.error(`执行失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLoading(false);
  };

  const fixHistory = result?.fix_history || [];
  const quality = result?.quality_report as Record<string, unknown> | null;
  const diagnosis = result?.diagnosis_report as Record<string, unknown> | null;

  return (
    <div>
      <Title level={3} style={{ color: '#E0E3E8', marginBottom: 8 }}>
        修复闭环
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
        输入 SQL 查询，运行 L1 数据质量 + L2 逻辑比对 + L3 诊断，自动修复并重测
      </Text>

      {/* Input Section */}
      <Card style={{ marginBottom: 16 }}>
        <TextArea
          rows={4}
          placeholder="SELECT cust_id, channel_type, COUNT(*) as cnt FROM dm_customer_active GROUP BY cust_id, channel_type"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          style={{ marginBottom: 12 }}
        />
        <div style={{ display: 'flex', gap: 12 }}>
          <TextArea
            rows={2}
            placeholder="原始需求文档（可选，提供业务上下文）"
            value={reqText}
            onChange={(e) => setReqText(e.target.value)}
            style={{ flex: 1 }}
          />
          <Upload accept=".txt,.md,.docx" maxCount={1} showUploadList={false}
            beforeUpload={(file) => {
              const reader = new FileReader();
              reader.onload = (e) => setReqText(e.target?.result as string);
              reader.readAsText(file, 'UTF-8');
              return false;
            }}
          >
            <Button icon={<UploadOutlined />}>上传文档</Button>
          </Upload>
        </div>
      </Card>

      {/* Settings */}
      <Space style={{ marginBottom: 16 }} size="middle">
        <div>
          <Text type="secondary">最大重试次数</Text>
          <InputNumber min={1} max={10} value={maxLoops} onChange={(v) => setMaxLoops(v || 3)} style={{ marginLeft: 8, width: 80 }} />
        </div>
        <div>
          <Text type="secondary">数据库连接</Text>
          <Input
            placeholder="sqlite:///test.db"
            value={dbConn}
            onChange={(e) => setDbConn(e.target.value)}
            style={{ marginLeft: 8, width: 280 }}
          />
        </div>
        <Button
          type="primary"
          icon={<BugOutlined />}
          onClick={handleRun}
          loading={loading}
          disabled={!sql.trim()}
          size="large"
        >
          运行测试
        </Button>
      </Space>

      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="正在执行测试与修复闭环..." />
        </div>
      )}

      {/* Dry-run preview */}
      {result?.status === 'dry_run' && (
        <Card title="流程预览" style={{ marginTop: 16 }}>
          <Alert
            type="info"
            message="未连接数据库 — 展示诊断流程"
            description="请填写数据库连接字符串以执行实际测试。"
            showIcon
          />
          <Collapse style={{ marginTop: 12 }}
            items={[
              {
                key: 'l1',
                label: 'L1 基础质量检查（将执行）',
                children: (
                  <ul>
                    <li>✅ 主键唯一性: GROUP BY pk HAVING COUNT(*) &gt; 1</li>
                    <li>✅ 空值率: 对每个字段检查 NULL 比例</li>
                    <li>✅ 字段超长: 对比 varchar(N) 与 MAX(LENGTH(col))</li>
                    <li>✅ 码值合法性: 对比列值与合法码值</li>
                  </ul>
                ),
              },
              {
                key: 'l3',
                label: 'L3 诊断与修复（如检测到失败）',
                children: (
                  <ul>
                    <li>L1: 数据源检查</li>
                    <li>L2: 码值映射检查</li>
                    <li>L3: JOIN 逻辑检查</li>
                    <li>L4: 业务口径检查</li>
                    <li>L5: 概念遗漏检查</li>
                  </ul>
                ),
              },
            ]}
          />
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">
              列数: {String((result as unknown as Record<string, unknown>)?.column_count ?? 'N/A')}
            </Text>
            <br />
            <Text type="secondary">
              主键: {String((result as unknown as Record<string, unknown>)?.pk_columns ?? 'N/A')}
            </Text>
          </div>
        </Card>
      )}

      {/* Results */}
      {result && result.status !== 'dry_run' && (
        <div style={{ marginTop: 16 }}>
          {/* Final status */}
          {result.status === 'passed' ? (
            <Result
              status="success"
              title="全部通过！"
              subTitle={`共执行 ${result.loop_count} 轮修复闭环`}
            />
          ) : (
            <Result
              status={result.status === 'error' ? 'error' : 'warning'}
              title={result.status === 'error' ? '执行失败' : '未完全通过'}
              subTitle={result.error_message || `状态: ${result.status}，共 ${result.loop_count} 轮`}
            />
          )}

          {/* Fix history timeline */}
          {fixHistory.length > 0 && (
            <Card title="修复过程" style={{ marginTop: 16 }}>
              <Timeline
                items={fixHistory.map((entry, i) => ({
                  color: i === fixHistory.length - 1 && result.status === 'passed' ? 'green' : 'red',
                  dot: i === fixHistory.length - 1 && result.status === 'passed' ? (
                    <CheckCircleOutlined />
                  ) : (
                    <CloseCircleOutlined />
                  ),
                  children: (
                    <div>
                      <Tag color="processing">
                        <SyncOutlined /> 第 {i + 1} 轮
                      </Tag>
                      <pre style={{ fontSize: 12, color: '#9099A4', marginTop: 4, maxHeight: 200, overflow: 'auto' }}>
                        {JSON.stringify(entry, null, 2)}
                      </pre>
                    </div>
                  ),
                }))}
              />
            </Card>
          )}

          {/* Detail reports */}
          <Collapse style={{ marginTop: 16 }}
            items={[
              ...(quality
                ? [
                    {
                      key: 'quality',
                      label: (
                        <span>
                          L1 质量报告{' '}
                          <Tag color={quality.overall_passed ? 'success' : 'error'}>
                            {quality.overall_passed ? '通过' : '失败'}
                          </Tag>
                        </span>
                      ),
                      children: (
                        <Table
                          dataSource={(quality.results as Array<Record<string, unknown>>)?.map(
                            (r, i) => ({ ...r, _key: i })
                          ) || []}
                          columns={[
                            { title: '类型', dataIndex: 'check_type', key: 'type', width: 120 },
                            { title: '列', dataIndex: 'column', key: 'col', width: 120 },
                            { title: '详情', dataIndex: 'detail', key: 'detail' },
                            {
                              title: '结果',
                              dataIndex: 'passed',
                              key: 'passed',
                              width: 80,
                              render: (v: boolean) => (v ? <Tag color="success">通过</Tag> : <Tag color="error">失败</Tag>),
                            },
                          ]}
                          size="small"
                          rowKey="_key"
                          pagination={false}
                        />
                      ),
                    },
                  ]
                : []),
              ...(diagnosis
                ? [
                    {
                      key: 'diagnosis',
                      label: (
                        <span>
                          L3 诊断报告{' '}
                          <Tag>{diagnosis.total_failures as number} 项失败</Tag>
                          <Tag color="volcano">{diagnosis.auto_fixable_count as number} 可自动修复</Tag>
                        </span>
                      ),
                      children: (
                        <div>
                          <Text>{diagnosis.summary as string}</Text>
                          {(diagnosis.items as Array<Record<string, unknown>>)?.map((item, i) => (
                            <Alert
                              key={i}
                              type={item.is_auto_fixable ? 'warning' : 'info'}
                              message={`${item.symptom as string} — 根因: ${item.root_cause as string}`}
                              description={`修复: ${item.fix_suggestion as string} | 级别: ${item.severity as string} | ${item.is_auto_fixable ? '可自动修复' : '需人工处理'}`}
                              style={{ marginTop: 8 }}
                              showIcon
                            />
                          ))}
                        </div>
                      ),
                    },
                  ]
                : []),
            ]}
          />
        </div>
      )}
    </div>
  );
}
