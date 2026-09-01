import { MedicineBoxOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { Tag, Typography } from 'antd';

import { ChatWorkspace } from '../../../widgets/chat-workspace/ui/ChatWorkspace';

export function ChatPage() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-teal-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-3 px-3 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-teal-700 text-xl text-white shadow-sm">
              <MedicineBoxOutlined />
            </div>
            <div className="min-w-0">
              <Typography.Title level={2} className="!mb-0 !mt-0 !text-xl sm:!text-2xl">
                癫痫循证问答助手
              </Typography.Title>
              <Typography.Text type="secondary" className="text-xs sm:text-sm">
                本地 Agentic RAG 演示 · 回答基于可追溯证据
              </Typography.Text>
            </div>
          </div>
          <Tag color="cyan" icon={<SafetyCertificateOutlined />}>
            隐私会话
          </Tag>
        </div>
      </header>

      <ChatWorkspace />

      <footer className="mx-auto max-w-[1440px] px-4 pb-6 text-center text-xs leading-6 text-slate-500">
        本系统仅用于健康科普与技术演示，不提供诊断或个体化治疗建议；紧急情况请联系当地急救服务。
      </footer>
    </div>
  );
}
