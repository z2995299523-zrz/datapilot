/**
 * SQL 代码块组件 — 深色背景 + SQL 语法展示
 */

import { Typography } from 'antd';
import { CopyOutlined } from '@ant-design/icons';

interface Props {
  sql: string;
  maxHeight?: number;
}

export default function SqlCodeBlock({ sql, maxHeight = 400 }: Props) {
  if (!sql) return null;

  return (
    <div style={{ position: 'relative' }}>
      <Typography.Paragraph
        copyable={{
          text: sql,
          icon: [<CopyOutlined key="copy" />, <CopyOutlined key="copied" />],
          tooltips: ['复制 SQL', '已复制'],
        }}
        style={{
          position: 'absolute',
          top: 8,
          right: 8,
          zIndex: 1,
          margin: 0,
        }}
      />
      <pre
        style={{
          background: '#0D1117',
          border: '1px solid #2D333B',
          borderRadius: 6,
          padding: '16px 44px 16px 16px',
          maxHeight,
          overflow: 'auto',
          fontSize: 13,
          fontFamily: '"Cascadia Code", "Fira Code", "JetBrains Mono", Consolas, monospace',
          lineHeight: 1.7,
          color: '#E0E3E8',
          margin: 0,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        <code>{sql}</code>
      </pre>
    </div>
  );
}
