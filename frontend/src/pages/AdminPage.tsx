/**
 * AdminPage — 系统管理：用户 / 部门 / 业务线 / 表-业务线映射 管理
 *
 * 4 个 Tabs，每个 Tab 含表格 + 创建按钮（Modal 表单）。
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Tabs, Table, Button, Modal, Form, Input, Select, Switch, message,
  Space, Tag, TreeSelect, Typography,
} from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';

import {
  adminApi,
  type AdminUser,
  type AdminDepartment,
  type AdminBusinessLine,
  type AdminTableLineMapping,
} from '../api/admin';

const { Title, Text } = Typography;

// ---------- helpers ----------

/** Build Ant Design TreeSelect treeData from flat department list */
function buildDepartmentTree(depts: AdminDepartment[]) {
  const map = new Map<number, { title: string; value: number; key: number; children: unknown[] }>();
  const roots: { title: string; value: number; key: number; children: unknown[] }[] = [];

  for (const d of depts) {
    map.set(d.id, { title: d.name, value: d.id, key: d.id, children: [] });
  }
  for (const d of depts) {
    const node = map.get(d.id);
    if (!node) continue;
    if (d.parent_id && map.has(d.parent_id)) {
      map.get(d.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

// ---------- Tag colors ----------

const statusTagColor = (active: boolean) => (active ? 'green' : 'default');
const adminTagColor = (admin: boolean) => (admin ? 'volcano' : 'default');

// ====================================================================

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('users');

  // ---------- Data state ----------
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [departments, setDepartments] = useState<AdminDepartment[]>([]);
  const [businessLines, setBusinessLines] = useState<AdminBusinessLine[]>([]);
  const [mappings, setMappings] = useState<AdminTableLineMapping[]>([]);

  // ---------- Loading state ----------
  const [usersLoading, setUsersLoading] = useState(false);
  const [deptsLoading, setDeptsLoading] = useState(false);
  const [linesLoading, setLinesLoading] = useState(false);
  const [mappingsLoading, setMappingsLoading] = useState(false);

  // ---------- Modal state ----------
  const [showUserModal, setShowUserModal] = useState(false);
  const [showDeptModal, setShowDeptModal] = useState(false);
  const [showLineModal, setShowLineModal] = useState(false);
  const [showMappingModal, setShowMappingModal] = useState(false);

  const [modalSubmitting, setModalSubmitting] = useState(false);

  // ---------- Form refs ----------
  const [userForm] = Form.useForm();
  const [deptForm] = Form.useForm();
  const [lineForm] = Form.useForm();
  const [mappingForm] = Form.useForm();

  // ---------- Data fetchers ----------

  const fetchUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const { data } = await adminApi.listUsers();
      setUsers(data);
    } catch (e: unknown) {
      message.error(`加载用户列表失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setUsersLoading(false);
  }, []);

  const fetchDepartments = useCallback(async () => {
    setDeptsLoading(true);
    try {
      const { data } = await adminApi.listDepartments();
      setDepartments(data);
    } catch (e: unknown) {
      message.error(`加载部门列表失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setDeptsLoading(false);
  }, []);

  const fetchBusinessLines = useCallback(async () => {
    setLinesLoading(true);
    try {
      const { data } = await adminApi.listBusinessLines();
      setBusinessLines(data);
    } catch (e: unknown) {
      message.error(`加载业务线列表失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLinesLoading(false);
  }, []);

  const fetchMappings = useCallback(async () => {
    setMappingsLoading(true);
    try {
      const { data } = await adminApi.listTableLineMappings();
      setMappings(data);
    } catch (e: unknown) {
      message.error(`加载表-业务线映射失败: ${e instanceof Error ? e.message : String(e)}`);
    }
    setMappingsLoading(false);
  }, []);

  // Fetch on mount
  useEffect(() => { fetchUsers(); }, [fetchUsers]);
  useEffect(() => { fetchDepartments(); }, [fetchDepartments]);
  useEffect(() => { fetchBusinessLines(); }, [fetchBusinessLines]);
  useEffect(() => { fetchMappings(); }, [fetchMappings]);

  // ---------- Create handlers ----------

  const handleCreateUser = async () => {
    try {
      const values = await userForm.validateFields();
      setModalSubmitting(true);
      await adminApi.createUser(values);
      message.success('用户创建成功');
      setShowUserModal(false);
      userForm.resetFields();
      fetchUsers();
    } catch (e: unknown) {
      if (e instanceof Error) {
        message.error(`创建用户失败: ${e.message}`);
      }
    }
    setModalSubmitting(false);
  };

  const handleCreateDepartment = async () => {
    try {
      const values = await deptForm.validateFields();
      setModalSubmitting(true);
      await adminApi.createDepartment(values);
      message.success('部门创建成功');
      setShowDeptModal(false);
      deptForm.resetFields();
      fetchDepartments();
    } catch (e: unknown) {
      if (e instanceof Error) {
        message.error(`创建部门失败: ${e.message}`);
      }
    }
    setModalSubmitting(false);
  };

  const handleCreateBusinessLine = async () => {
    try {
      const values = await lineForm.validateFields();
      setModalSubmitting(true);
      await adminApi.createBusinessLine(values);
      message.success('业务线创建成功');
      setShowLineModal(false);
      lineForm.resetFields();
      fetchBusinessLines();
    } catch (e: unknown) {
      if (e instanceof Error) {
        message.error(`创建业务线失败: ${e.message}`);
      }
    }
    setModalSubmitting(false);
  };

  const handleAddMapping = async () => {
    try {
      const values = await mappingForm.validateFields();
      setModalSubmitting(true);
      await adminApi.addTableLineMapping(values);
      message.success('映射添加成功');
      setShowMappingModal(false);
      mappingForm.resetFields();
      fetchMappings();
    } catch (e: unknown) {
      if (e instanceof Error) {
        message.error(`添加映射失败: ${e.message}`);
      }
    }
    setModalSubmitting(false);
  };

  const handleDeleteMapping = async (tableName: string, lineId: number) => {
    try {
      await adminApi.removeTableLineMapping(tableName, lineId);
      message.success('映射已删除');
      fetchMappings();
    } catch (e: unknown) {
      message.error(`删除映射失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // ---------- Department tree for TreeSelect ----------
  const deptTreeData = buildDepartmentTree(departments);

  // ---------- Render ----------

  return (
    <div>
      <Title level={3} style={{ color: '#E0E3E8', marginBottom: 8 }}>
        系统管理
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
        用户 / 部门 / 业务线 / 表-业务线映射 管理
      </Text>

      <Tabs activeKey={activeTab} onChange={setActiveTab}>

        {/* ===== Tab 1: Users ===== */}
        <Tabs.TabPane tab="用户管理" key="users">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowUserModal(true)}
                  style={{ marginBottom: 16 }}>
            创建用户
          </Button>
          <Table
            dataSource={users}
            rowKey="id"
            loading={usersLoading}
            size="small"
            columns={[
              { title: '用户名', dataIndex: 'username', key: 'username', width: 140 },
              { title: '姓名', dataIndex: 'real_name', key: 'real_name', width: 120 },
              { title: '部门', dataIndex: 'department_name', key: 'dept', width: 150 },
              {
                title: '管理员', dataIndex: 'is_admin', key: 'admin', width: 90,
                render: (v: boolean) => <Tag color={adminTagColor(v)}>{v ? '是' : '否'}</Tag>,
              },
              {
                title: '状态', dataIndex: 'is_active', key: 'active', width: 80,
                render: (v: boolean) => <Tag color={statusTagColor(v)}>{v ? '活跃' : '禁用'}</Tag>,
              },
              { title: '创建时间', dataIndex: 'created_at', key: 'created', width: 170 },
            ]}
            scroll={{ x: 'max-content' }}
          />
        </Tabs.TabPane>

        {/* ===== Tab 2: Departments ===== */}
        <Tabs.TabPane tab="部门管理" key="departments">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowDeptModal(true)}
                  style={{ marginBottom: 16 }}>
            创建部门
          </Button>
          <Table
            dataSource={departments}
            rowKey="id"
            loading={deptsLoading}
            size="small"
            columns={[
              { title: '名称', dataIndex: 'name', key: 'name', width: 160 },
              { title: '路径', dataIndex: 'path', key: 'path', width: 260, ellipsis: true },
              { title: '层级', dataIndex: 'level', key: 'level', width: 70 },
              {
                title: '状态', dataIndex: 'is_active', key: 'active', width: 80,
                render: (v: boolean) => <Tag color={statusTagColor(v)}>{v ? '活跃' : '禁用'}</Tag>,
              },
            ]}
            scroll={{ x: 'max-content' }}
          />
        </Tabs.TabPane>

        {/* ===== Tab 3: Business Lines ===== */}
        <Tabs.TabPane tab="业务线管理" key="businessLines">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowLineModal(true)}
                  style={{ marginBottom: 16 }}>
            创建业务线
          </Button>
          <Table
            dataSource={businessLines}
            rowKey="id"
            loading={linesLoading}
            size="small"
            columns={[
              { title: '名称', dataIndex: 'name', key: 'name', width: 160 },
              { title: '编码', dataIndex: 'code', key: 'code', width: 120 },
              { title: '描述', dataIndex: 'description', key: 'desc', width: 280, ellipsis: true },
              {
                title: '状态', dataIndex: 'is_active', key: 'active', width: 80,
                render: (v: boolean) => <Tag color={statusTagColor(v)}>{v ? '活跃' : '禁用'}</Tag>,
              },
            ]}
            scroll={{ x: 'max-content' }}
          />
        </Tabs.TabPane>

        {/* ===== Tab 4: Table-Line Mappings ===== */}
        <Tabs.TabPane tab="表-业务线映射" key="mappings">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowMappingModal(true)}
                  style={{ marginBottom: 16 }}>
            添加映射
          </Button>
          <Table
            dataSource={mappings}
            rowKey={(r) => `${r.table_name}-${r.business_line_id}`}
            loading={mappingsLoading}
            size="small"
            columns={[
              { title: '表名', dataIndex: 'table_name', key: 'table', width: 260 },
              { title: '业务线 ID', dataIndex: 'business_line_id', key: 'lineId', width: 120 },
              {
                title: '操作', key: 'actions', width: 80,
                render: (_: unknown, r: AdminTableLineMapping) => (
                  <Button type="link" danger icon={<DeleteOutlined />}
                          onClick={() => handleDeleteMapping(r.table_name, r.business_line_id)}>
                    删除
                  </Button>
                ),
              },
            ]}
            scroll={{ x: 'max-content' }}
          />
        </Tabs.TabPane>
      </Tabs>

      {/* ===== Modals ===== */}

      {/* User Modal */}
      <Modal
        title="创建用户"
        open={showUserModal}
        onOk={handleCreateUser}
        onCancel={() => { setShowUserModal(false); userForm.resetFields(); }}
        confirmLoading={modalSubmitting}
        destroyOnClose
      >
        <Form form={userForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="real_name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="department_id" label="部门"
                     rules={[{ required: true, message: '请选择部门' }]}>
            <Select
              placeholder="选择部门"
              loading={deptsLoading}
              options={departments
                .filter((d) => d.is_active)
                .map((d) => ({ label: d.path || d.name, value: d.id }))}
            />
          </Form.Item>
          <Form.Item name="business_line_ids" label="业务线">
            <Select
              mode="multiple"
              placeholder="选择业务线（可选）"
              loading={linesLoading}
              options={businessLines
                .filter((l) => l.is_active)
                .map((l) => ({ label: `${l.name} (${l.code})`, value: l.id }))}
            />
          </Form.Item>
          <Form.Item name="is_admin" label="管理员" valuePropName="checked" initialValue={false}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* Department Modal */}
      <Modal
        title="创建部门"
        open={showDeptModal}
        onOk={handleCreateDepartment}
        onCancel={() => { setShowDeptModal(false); deptForm.resetFields(); }}
        confirmLoading={modalSubmitting}
        destroyOnClose
      >
        <Form form={deptForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="部门名称" rules={[{ required: true, message: '请输入部门名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="parent_id" label="上级部门">
            <TreeSelect
              treeData={deptTreeData}
              placeholder="选择上级部门（可选）"
              allowClear
              treeDefaultExpandAll
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* Business Line Modal */}
      <Modal
        title="创建业务线"
        open={showLineModal}
        onOk={handleCreateBusinessLine}
        onCancel={() => { setShowLineModal(false); lineForm.resetFields(); }}
        confirmLoading={modalSubmitting}
        destroyOnClose
      >
        <Form form={lineForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="code" label="编码" rules={[{ required: true, message: '请输入编码' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Mapping Modal */}
      <Modal
        title="添加表-业务线映射"
        open={showMappingModal}
        onOk={handleAddMapping}
        onCancel={() => { setShowMappingModal(false); mappingForm.resetFields(); }}
        confirmLoading={modalSubmitting}
        destroyOnClose
      >
        <Form form={mappingForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="table_name" label="表名"
                     rules={[{ required: true, message: '请输入表名' }]}>
            <Input placeholder="例如: dws_customer_loan" />
          </Form.Item>
          <Form.Item name="business_line_id" label="业务线"
                     rules={[{ required: true, message: '请选择业务线' }]}>
            <Select
              placeholder="选择业务线"
              loading={linesLoading}
              options={businessLines
                .filter((l) => l.is_active)
                .map((l) => ({ label: `${l.name} (${l.code})`, value: l.id }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
