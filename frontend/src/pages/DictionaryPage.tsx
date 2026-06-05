/**
 * 数据字典管理页 — 上传 CSV/XLSX，构建 ChromaDB 索引
 */

import { useState, useEffect } from 'react';
import {
  Typography,
  Upload,
  Button,
  Table,
  Card,
  Alert,
  Space,
  message,
  Spin,
  Tag,
} from 'antd';
import { UploadOutlined, ReloadOutlined, CloudUploadOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload';

import { dictionaryApi, type IndexStatus } from '../api/dictionary';

const { Title, Text } = Typography;
const { Dragger } = Upload;

export default function DictionaryPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<{ columns: string[]; rows: unknown[][]; total_rows: number } | null>(null);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [loading, setLoading] = useState(false);

  // Load index status on mount
  useEffect(() => {
    dictionaryApi.status().then(setIndexStatus);
  }, []);

  const handleFileSelect = (info: { file: UploadFile }) => {
    const f = info.file.originFileObj;
    if (f) {
      setFile(f);
      // Preview locally
      const reader = new FileReader();
      reader.onload = (e) => {
        const text = e.target?.result as string;
        const lines = text.split('\n').filter(Boolean);
        if (lines.length > 1) {
          const cols = lines[0].split(',');
          const rows = lines.slice(1, 21).map((l) => l.split(','));
          setPreview({ columns: cols, rows, total_rows: lines.length - 1 });
        }
      };
      reader.readAsText(f, 'UTF-8');
    }
  };

  const handleBuild = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const result = await dictionaryApi.upload(file);
      if (result.success) {
        message.success(`索引构建完成！${result.collection_count} 条记录，${result.layers.length} 个数据层`);
        setIndexStatus({ ready: true, count: result.collection_count, collection: '', error: '' });
      } else {
        message.error(result.error || '构建失败');
      }
    } catch (e: unknown) {
      message.error(`请求失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLoading(false);
  };

  return (
    <div>
      <Title level={3} style={{ color: '#E0E3E8', marginBottom: 8 }}>
        数据字典管理
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
        上传数据字典文件（CSV 或 Excel），构建 ChromaDB 向量索引
      </Text>

      {/* Upload */}
      <Card style={{ marginBottom: 16 }}>
        <Dragger
          accept=".csv,.xlsx"
          maxCount={1}
          showUploadList={false}
          beforeUpload={() => false} // prevent auto upload
          onChange={handleFileSelect}
          style={{ background: '#0B0E14', borderColor: '#2D333B' }}
        >
          <p className="ant-upload-drag-icon">
            <CloudUploadOutlined style={{ fontSize: 36, color: '#B34141' }} />
          </p>
          <p style={{ color: '#E0E3E8' }}>点击或拖拽数据字典文件到此区域</p>
          <p style={{ color: '#6E7681', fontSize: 13 }}>支持 .csv 和 .xlsx 格式</p>
        </Dragger>
      </Card>

      {/* Preview */}
      {preview && (
        <Card title="文件预览" style={{ marginBottom: 16 }}>
          <Table
            dataSource={preview.rows.map((row, i) => {
              const record: Record<string, unknown> = { _key: i };
              preview.columns.forEach((col, j) => {
                record[col] = row[j] ?? '';
              });
              return record;
            })}
            columns={preview.columns.map((col) => ({
              title: col,
              dataIndex: col,
              key: col,
              ellipsis: true,
            }))}
            size="small"
            pagination={false}
            rowKey="_key"
            scroll={{ x: 'max-content' }}
          />
          <Text type="secondary" style={{ marginTop: 8, display: 'block' }}>
            共 {preview.total_rows} 行（预览前 20 行）
          </Text>
        </Card>
      )}

      {/* Actions */}
      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<UploadOutlined />}
          onClick={handleBuild}
          loading={loading}
          disabled={!file}
          size="large"
        >
          构建索引
        </Button>
        <Button
          icon={<ReloadOutlined />}
          onClick={handleBuild}
          loading={loading}
          disabled={!file}
          size="large"
        >
          重建索引
        </Button>
      </Space>

      {/* Status */}
      {indexStatus && (
        <>
          {indexStatus.ready ? (
            <Alert
              type="success"
              message={
                <span>
                  索引已就绪 — 包含 <Tag color="volcano">{indexStatus.count}</Tag> 条记录
                </span>
              }
              showIcon
            />
          ) : (
            <Alert
              type="warning"
              message="尚未构建索引。请上传数据字典文件并点击「构建索引」。"
              showIcon
            />
          )}
          {indexStatus.error && (
            <Alert type="error" title={indexStatus.error} style={{ marginTop: 8 }} showIcon />
          )}
        </>
      )}

      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="正在构建 ChromaDB 索引..." />
        </div>
      )}
    </div>
  );
}
