/**
 * 流式控制：停止 + AbortController 兜底 + 定时器清理（§9.3 / qa.ts:222-239 同范式）。
 *
 * 停止策略：先写服务端停止标记，若 2s 内未收到 stopped/done，再 abort 断连兜底，
 * 避免服务端逻辑卡住时前端一直挂起。
 */
export class StreamController {
  private abort: AbortController | null = null;
  private fallback: ReturnType<typeof setTimeout> | null = null;

  /** 开始流式：返回本次请求的 AbortSignal。 */
  signal(): AbortSignal {
    this.abort = new AbortController();
    return this.abort.signal;
  }

  /** 停止：通知服务端写标记，并预约 2s 兜底断连。 */
  async stop(notifyServer: () => Promise<unknown>): Promise<void> {
    await notifyServer().catch(() => undefined);
    this.fallback = setTimeout(() => this.abort?.abort(), 2000);
  }

  /** 收到 stopped/done 后撤销兜底定时器（无需再断连）。 */
  clearFallback(): void {
    if (this.fallback) {
      clearTimeout(this.fallback);
      this.fallback = null;
    }
  }

  /** 组件卸载时清理，避免定时器/请求泄漏。 */
  dispose(): void {
    this.clearFallback();
    this.abort?.abort();
  }
}
