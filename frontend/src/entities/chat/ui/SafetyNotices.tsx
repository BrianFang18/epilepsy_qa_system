import { Alert } from 'antd';
import type { SafetyEventData } from '../model/contracts';
interface SafetyNoticesProps {
  events: readonly SafetyEventData[];
}
function copyFor(event: SafetyEventData) {
  switch (event.code) {
    case 'EMERGENCY_DETECTED':
      return {
        type: 'error' as const,
        message: '检测到可能的紧急情况',
        description: '请优先查看回答中的急救指引，并尽快联系当地急救服务或专业医务人员。',
      };
    case 'INSUFFICIENT_EVIDENCE':
      return {
        type: 'info' as const,
        message: '当前证据不足',
        description: '系统没有找到足以支持可靠回答的本地证据，因此不会猜测作答。',
      };
    case 'INVALID_CITATION_REMOVED':
      return {
        type: 'warning' as const,
        message: '已移除无效引用',
        description: '答案中无法对应到检索证据的引用标记已被安全移除。',
      };
    case 'DIRECT_DIAGNOSIS_BLOCKED':
      return {
        type: 'warning' as const,
        message: '已阻止直接诊断表述',
        description: '回答已调整为一般健康信息，不能替代专业医生的诊断。',
      };
    case 'INDIVIDUAL_MEDICATION_ADVICE_BLOCKED':
      return {
        type: 'warning' as const,
        message: '已阻止个体化用药建议',
        description: '请勿自行调整抗癫痫药物，具体方案应由专业医生评估。',
      };
  }
}
export function SafetyNotices({ events }: SafetyNoticesProps) {
  if (events.length === 0) return null;
  return (
    <div className="space-y-2" aria-label="安全提示">
      {events.map((event) => {
        const copy = copyFor(event);
        return (
          <Alert
            key={event.code}
            type={copy.type}
            message={copy.message}
            description={copy.description}
            role={event.level === 'critical' ? 'alert' : 'status'}
            showIcon
          />
        );
      })}
    </div>
  );
}
