export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly supportId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
const PUBLIC_MESSAGES: Record<string, string> = {
  CHAT_NOT_READY: '问答服务尚未就绪，请稍后重试。',
  DIAGNOSTIC_TRACE_REQUIRES_ADMIN: '诊断级轨迹仅管理员可查看。',
  RETRIEVAL_UNAVAILABLE: '证据检索暂时不可用，请稍后重试。',
  LLM_UPSTREAM_UNAVAILABLE: '回答模型暂时不可用，请稍后重试。',
  CHAT_INTERNAL_ERROR: '问答服务出现内部错误，请使用支持编号排查。',
};
function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const root = asRecord(body);
  const detail = asRecord(root?.detail);
  const codeValue = detail?.code ?? root?.code;
  const supportValue = detail?.support_id ?? root?.support_id;
  const code = typeof codeValue === 'string' ? codeValue : `HTTP_${response.status}`;
  const supportId = typeof supportValue === 'string' ? supportValue : undefined;
  const statusMessage: Record<number, string> = {
    401: '登录信息无效或会话已过期，请重新登录。',
    403: '当前管理员没有执行此操作的权限。',
    409: '当前状态不允许执行此操作，请刷新后重试。',
    413: '文件超过服务端允许的大小。',
    415: '文件类型或内容格式不受支持。',
    422: '输入内容不符合要求，请检查后重试。',
    500: '服务出现内部错误，请稍后重试。',
    503: '管理服务尚未就绪，请检查本地基础设施。',
  };
  const message =
    PUBLIC_MESSAGES[code] ??
    statusMessage[response.status] ??
    `请求失败（HTTP ${response.status}）。`;
  return new ApiError(message, response.status, code, supportId);
}
export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  );
}
