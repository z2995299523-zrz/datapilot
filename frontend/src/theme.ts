/**
 * DataPilot 黑暗主题 — 黑色为主，勃艮第酒红为辅
 *
 * 基于 Ant Design 5 darkAlgorithm 定制。
 * 在 App.tsx 中通过 ConfigProvider 注入。
 */

import type { ThemeConfig } from 'antd';

export const themeConfig: ThemeConfig = {
  algorithm: undefined, // 将在 ConfigProvider 中设置
  token: {
    colorPrimary: '#B34141',
    colorPrimaryHover: '#C96060',
    colorPrimaryActive: '#8B3030',
    colorPrimaryBg: 'rgba(179, 65, 65, 0.10)',
    colorPrimaryBgHover: 'rgba(179, 65, 65, 0.18)',
    colorPrimaryBorder: 'rgba(179, 65, 65, 0.30)',
    colorPrimaryBorderHover: 'rgba(179, 65, 65, 0.50)',
    colorPrimaryText: '#C96060',
    colorPrimaryTextHover: '#D98080',

    colorBgBase: '#0B0E14',
    colorBgContainer: '#141820',
    colorBgLayout: '#0B0E14',
    colorBgElevated: '#1A2130',
    colorBgSpotlight: '#141820',

    colorBorder: '#2D333B',
    colorBorderSecondary: '#1E2430',

    colorText: '#E0E3E8',
    colorTextSecondary: '#9099A4',
    colorTextTertiary: '#6E7681',
    colorTextQuaternary: '#505A66',

    colorSuccess: '#2D8A4E',
    colorWarning: '#C08030',
    colorError: '#B34141',
    colorInfo: '#3050A0',

    borderRadius: 6,
    borderRadiusLG: 8,
    borderRadiusSM: 4,

    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    fontSize: 14,

    controlHeight: 36,
    lineHeight: 1.6,
  },
  components: {
    Layout: {
      siderBg: '#080B10',
      bodyBg: '#0B0E14',
      headerBg: '#0B0E14',
    },
    Menu: {
      darkItemBg: '#080B10',
      darkItemSelectedBg: 'rgba(179, 65, 65, 0.12)',
      darkItemHoverBg: 'rgba(179, 65, 65, 0.06)',
      darkSubMenuItemBg: '#080B10',
      darkItemColor: '#9099A4',
      darkItemSelectedColor: '#C96060',
      darkItemHoverColor: '#E0E3E8',
    },
    Button: {
      primaryColor: '#FFFFFF',
      defaultBg: '#141820',
      defaultBorderColor: '#2D333B',
      defaultColor: '#E0E3E8',
      defaultHoverBorderColor: '#B34141',
      defaultHoverColor: '#C96060',
    },
    Input: {
      activeBorderColor: '#B34141',
      activeShadow: '0 0 0 2px rgba(179, 65, 65, 0.12)',
      hoverBorderColor: '#2D333B',
    },
    Collapse: {
      contentBg: '#141820',
      headerBg: '#141820',
    },
    Table: {
      headerBg: '#1A2130',
      headerColor: '#9099A4',
      rowHoverBg: '#1A2130',
      borderColor: '#2D333B',
    },
    Card: {
      colorBgContainer: '#141820',
    },
    Tag: {
      defaultBg: '#1E2430',
      defaultColor: '#9099A4',
    },
    Upload: {
      colorBgContainer: '#141820',
    },
    Select: {
      colorBgContainer: '#141820',
      colorBgElevated: '#1A2130',
      optionSelectedBg: 'rgba(179, 65, 65, 0.12)',
    },
    Tooltip: {
      colorBgSpotlight: '#1A2130',
    },
    Modal: {
      colorBgElevated: '#141820',
    },
    Notification: {
      colorBgElevated: '#141820',
    },
    Progress: {
      defaultColor: '#B34141',
      remainingColor: '#1E2430',
    },
  },
};
