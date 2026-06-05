/**
 * 数仓建模页 — 从业务 DB schema 自动搭建分层数仓模型
 *
 * 4 步骤: 上传 Schema → 分类分层 → 关系与码值 → 质检报告
 */

import { useState } from 'react';
import {
  Typography, Steps, Upload, Button, Card, Table, Tag, Collapse,
  Row, Col, Statistic, Alert, Progress, Space, Spin, message,
  Badge, List, Tooltip,
} from 'antd';
import {
  CloudUploadOutlined, RocketOutlined,
  CloseCircleOutlined, WarningOutlined, InfoCircleOutlined,
  TableOutlined, ApartmentOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons';

import { modelingApi, type ModelingResult, type SchemaUploadResult } from '../api/modeling';

const { Title, Text } = Typography;

// ---------- role colors ----------
const roleColors: Record<string, string> = {
  fact: 'volcano', dimension: 'blue', bridge: 'purple', aggregate: 'green', unknown: 'default',
};
const layerColors: Record<string, string> = {
  ODS: 'blue', DWS: 'volcano', ADS: 'green', DM: 'purple',
};
const severityColors: Record<string, string> = {
  error: 'red', warning: 'orange', info: 'blue',
};

export default function ModelingPage() {
  const [current, setCurrent] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<SchemaUploadResult | null>(null);
  const [modelingResult, setModelingResult] = useState<ModelingResult | null>(null);
  const [loading, setLoading] = useState(false);

  // Step 1: Upload
  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const res = await modelingApi.upload(file);
      if (res.success) {
        setUploadResult(res);
        message.success(`检测到 ${res.tables_detected} 张表，${res.columns_detected} 个字段`);
        setCurrent(1);
      } else {
        message.error(res.error || '上传失败');
      }
    } catch (e: unknown) {
      message.error(`上传失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLoading(false);
  };

  // Step 2: Run modeling
  const handleModel = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const text = await file.text();
      const lines = text.split('\n').filter(Boolean);
      const headers = lines[0].split(',');
      const tables: Record<string, unknown>[] = [];
      // Build minimal table info from CSV rows
      const tableMap = new Map<string, { columns: { name: string; data_type: string; comment: string }[] }>();
      for (let i = 1; i < lines.length; i++) {
        const row = lines[i].split(',');
        const tname = row[headers.indexOf('表名')] || row[1] || '';
        const cname = row[headers.indexOf('字段名')] || row[3] || '';
        const ctype = row[headers.indexOf('字段类型')] || row[4] || '';
        const ccomment = row[headers.indexOf('字段注释')] || row[5] || '';
        if (tname && cname) {
          if (!tableMap.has(tname)) tableMap.set(tname, { columns: [] });
          tableMap.get(tname)!.columns.push({ name: cname, data_type: ctype, comment: ccomment });
        }
      }
      tableMap.forEach((v, k) => {
        tables.push({ table_name: k, table_comment: '', layer: 'ODS', columns: v.columns });
      });

      const res = await modelingApi.analyze({
        source_name: file.name,
        tables,
        enable_llm: false,
        detect_codes: true,
        validate_quality: true,
      });
      setModelingResult(res);
      setCurrent(2);
      message.success('数仓建模完成');
    } catch (e: unknown) {
      message.error(`建模失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLoading(false);
  };

  const result = modelingResult;

  // Stats
  const factCount = Object.values(result?.classifications || {}).filter(c => c.role === 'fact').length;
  const dimCount = Object.values(result?.classifications || {}).filter(c => c.role === 'dimension').length;
  const aggCount = Object.values(result?.classifications || {}).filter(c => c.role === 'aggregate').length;
  const errorCount = (result?.quality_issues || []).filter(q => q.severity === 'error').length;
  const warnCount = (result?.quality_issues || []).filter(q => q.severity === 'warning').length;
  const codeCount = (result?.code_columns || []).length;

  return (
    <div>
      <Title level={3} style={{ color: '#E0E3E8', marginBottom: 8 }}>
        数仓建模
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
        从业务数据库 Schema 自动搭建分层数仓模型（ODS → DWS → ADS → DM）
      </Text>

      <Steps
        current={current}
        size="small"
        style={{ marginBottom: 24 }}
        items={[
          { title: '上传 Schema', icon: <CloudUploadOutlined /> },
          { title: '分类与分层', icon: <TableOutlined /> },
          { title: '建模结果', icon: <ApartmentOutlined /> },
          { title: '质检报告', icon: <SafetyCertificateOutlined /> },
        ]}
      />

      {/* Step 1: Upload */}
      {current === 0 && (
        <Card>
          <Upload.Dragger
            accept=".csv,.xlsx"
            maxCount={1}
            showUploadList={false}
            beforeUpload={(f) => { setFile(f); return false; }}
            style={{ background: '#0B0E14', borderColor: '#2D333B' }}
          >
            <p className="ant-upload-drag-icon">
              <CloudUploadOutlined style={{ fontSize: 36, color: '#B34141' }} />
            </p>
            <p style={{ color: '#E0E3E8' }}>拖拽或点击上传业务数据库 Schema 文件</p>
            <p style={{ color: '#6E7681', fontSize: 13 }}>支持 .csv / .xlsx，需含 表名、字段名、字段类型、字段注释 等列</p>
          </Upload.Dragger>
          {file && (
            <Alert
              type="info"
              message={`已选择: ${file.name}`}
              style={{ marginTop: 12 }}
              showIcon
            />
          )}
          <Button type="primary" icon={<RocketOutlined />} onClick={handleUpload}
                  loading={loading} disabled={!file} size="large"
                  style={{ marginTop: 16 }} block>
            解析 Schema
          </Button>
        </Card>
      )}

      {/* Step 1→2 transition */}
      {current === 1 && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Title level={4}>
            Schema 已解析：{uploadResult?.tables_detected} 张表 · {uploadResult?.columns_detected} 个字段
          </Title>
          <Space size="large">
            <Button size="large" onClick={() => setCurrent(0)}>重新上传</Button>
            <Button type="primary" size="large" icon={<RocketOutlined />}
                    onClick={handleModel} loading={loading}>
              开始建模
            </Button>
          </Space>
        </div>
      )}

      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="正在分析..." />
        </div>
      )}

      {/* Step 2: Classifications & Layers */}
      {current >= 2 && result && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card><Statistic title="总表数" value={result.total_tables} /></Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="事实表" value={factCount}
                  suffix={<Badge color="volcano" />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="维表" value={dimCount}
                  suffix={<Badge color="blue" />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="模式类型" value={0}
                  suffix={null}
                  prefix={<Tag color="purple">{result.schemas[0]?.schema_type || '?'}</Tag>} />
              </Card>
            </Col>
          </Row>

          <Collapse defaultActiveKey={['classify', 'layers', 'relations', 'codes', 'quality']}
            items={[
              {
                key: 'classify',
                label: <span>📊 表角色分类 ({factCount}F · {dimCount}D · {aggCount}A)</span>,
                children: (
                  <Table
                    dataSource={Object.entries(result.classifications).map(([k, v]) => ({
                      ...v, _key: k,
                    }))}
                    columns={[
                      { title: '表名', dataIndex: 'table_name', key: 'name', width: 200 },
                      { title: '角色', dataIndex: 'role', key: 'role', width: 100,
                        render: (r: string) => <Tag color={roleColors[r]}>{r}</Tag> },
                      { title: '置信度', dataIndex: 'confidence', key: 'conf', width: 120,
                        render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" /> },
                      { title: '分层', dataIndex: 'layer', key: 'layer', width: 80,
                        render: (l: string) => l ? <Tag color={layerColors[l]}>{l}</Tag> : '-' },
                      { title: '分析依据', dataIndex: 'reasoning', key: 'reason',
                        ellipsis: true },
                    ]}
                    size="small" pagination={false} rowKey="_key"
                  />
                ),
              },
              {
                key: 'layers',
                label: <span>🏗 分层结构 (ODS → DWS → ADS → DM)</span>,
                children: (
                  <Row gutter={16}>
                    {['ODS', 'DWS', 'ADS', 'DM'].map(layer => (
                      <Col span={6} key={layer}>
                        <Card size="small" title={<Tag color={layerColors[layer]}>{layer}</Tag>}
                          style={{ minHeight: 140 }}>
                          {(result.layers[layer] || []).length === 0 ? (
                            <Text type="secondary">空</Text>
                          ) : (
                            <List size="small"
                              dataSource={result.layers[layer] || []}
                              renderItem={(t: string) => (
                                <List.Item>
                                  <Text>{t}</Text>
                                  {result.classifications[t] && (
                                    <Tag color={roleColors[result.classifications[t].role]}>
                                      {result.classifications[t].role}
                                    </Tag>
                                  )}
                                </List.Item>
                              )}
                            />
                          )}
                        </Card>
                      </Col>
                    ))}
                  </Row>
                ),
              },
              {
                key: 'relations',
                label: <span>🔗 FK-PK 关系 ({result.relationships.length})</span>,
                children: (
                  <Table
                    dataSource={result.relationships.map((r, i) => ({ ...r, _key: i }))}
                    columns={[
                      { title: '源表', dataIndex: 'source_table', key: 'src', width: 180 },
                      { title: '源列', dataIndex: 'source_column', key: 'scol', width: 150 },
                      { title: '→', key: 'arrow', width: 40, render: () => '→' },
                      { title: '目标表', dataIndex: 'target_table', key: 'tgt', width: 180 },
                      { title: '目标列', dataIndex: 'target_column', key: 'tcol', width: 150 },
                      { title: '检测方式', dataIndex: 'detection_method', key: 'method', width: 110,
                        render: (m: string) => <Tag>{m}</Tag> },
                      { title: '置信度', dataIndex: 'confidence', key: 'conf', width: 100,
                        render: (v: number) => `${(v * 100).toFixed(0)}%` },
                    ]}
                    size="small" pagination={false} rowKey="_key"
                    scroll={{ x: 'max-content' }}
                  />
                ),
              },
              {
                key: 'codes',
                label: <span>🏷 码值列 ({codeCount})</span>,
                children: codeCount === 0 ? (
                  <Text type="secondary">未检测到码值列</Text>
                ) : (
                  <Table
                    dataSource={result.code_columns.map((c, i) => ({ ...c, _key: i }))}
                    columns={[
                      { title: '表名', dataIndex: 'table_name', key: 'tbl', width: 200 },
                      { title: '列名', dataIndex: 'column_name', key: 'col', width: 150 },
                      { title: '置信度', dataIndex: 'confidence', key: 'conf', width: 100,
                        render: (v: number) => `${(v * 100).toFixed(0)}%` },
                      { title: '检测依据', dataIndex: 'detection_reason', key: 'reason' },
                    ]}
                    size="small" pagination={false} rowKey="_key"
                  />
                ),
              },
              {
                key: 'quality',
                label: (
                  <span>
                    ✅ 质检报告
                    {errorCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{errorCount} ERR</Tag>}
                    {warnCount > 0 && <Tag color="warning">{warnCount} WARN</Tag>}
                  </span>
                ),
                children: result.quality_issues.length === 0 ? (
                  <Alert type="success" message="所有质量规则通过" showIcon />
                ) : (
                  <Table
                    dataSource={result.quality_issues.map((q, i) => ({ ...q, _key: i }))}
                    columns={[
                      { title: '严重度', dataIndex: 'severity', key: 'sev', width: 80,
                        render: (s: string) => (
                          <Tag color={severityColors[s]}
                            icon={s === 'error' ? <CloseCircleOutlined /> : <WarningOutlined />}>
                            {s}
                          </Tag>
                        ) },
                      { title: '规则', dataIndex: 'rule', key: 'rule', width: 160, ellipsis: true },
                      { title: '表', dataIndex: 'table', key: 'tbl', width: 160 },
                      { title: '列', dataIndex: 'column', key: 'col', width: 120 },
                      { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true },
                      { title: '建议', dataIndex: 'suggestion', key: 'sug', ellipsis: true,
                        render: (s: string) => (
                          <Tooltip title={s}>
                            <InfoCircleOutlined style={{ color: '#9099A4', cursor: 'help' }} />
                          </Tooltip>
                        ) },
                    ]}
                    size="small" pagination={false} rowKey="_key"
                    scroll={{ x: 'max-content' }}
                  />
                ),
              },
            ]}
          />
        </>
      )}
    </div>
  );
}
