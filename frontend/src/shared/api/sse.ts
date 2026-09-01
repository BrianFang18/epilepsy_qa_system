export interface RawSseEvent {
  event?: string;
  id?: string;
  data: string;
}

export class IncrementalSseParser {
  private buffer = '';

  push(chunk: string): RawSseEvent[] {
    this.buffer += chunk;
    return this.drain(false);
  }

  finish(): RawSseEvent[] {
    return this.drain(true);
  }

  private drain(flush: boolean): RawSseEvent[] {
    const events: RawSseEvent[] = [];
    let boundary = /\r?\n\r?\n/.exec(this.buffer);

    while (boundary?.index !== undefined) {
      const frame = this.buffer.slice(0, boundary.index);
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length);
      const parsed = this.parseFrame(frame);
      if (parsed) events.push(parsed);
      boundary = /\r?\n\r?\n/.exec(this.buffer);
    }

    if (flush && this.buffer.trim()) {
      const parsed = this.parseFrame(this.buffer);
      if (parsed) events.push(parsed);
      this.buffer = '';
    }

    return events;
  }

  private parseFrame(frame: string): RawSseEvent | null {
    let event: string | undefined;
    let id: string | undefined;
    const data: string[] = [];

    for (const line of frame.split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon >= 0 ? line.slice(0, colon) : line;
      let value = colon >= 0 ? line.slice(colon + 1) : '';
      if (value.startsWith(' ')) value = value.slice(1);

      if (field === 'event') event = value;
      else if (field === 'id') id = value;
      else if (field === 'data') data.push(value);
    }

    if (data.length === 0) return null;
    return { event, id, data: data.join('\n') };
  }
}

function abortReason(signal: AbortSignal): Error {
  return signal.reason instanceof Error
    ? signal.reason
    : new DOMException('The operation was aborted', 'AbortError');
}

export async function* readSseStream(
  stream: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<RawSseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const parser = new IncrementalSseParser();
  const cancelReader = () => void reader.cancel(signal.reason).catch(() => undefined);
  signal.addEventListener('abort', cancelReader, { once: true });

  try {
    while (true) {
      if (signal.aborted) throw abortReason(signal);
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of parser.push(decoder.decode(value, { stream: true }))) {
        yield event;
      }
    }

    if (signal.aborted) throw abortReason(signal);
    const decoderTail = decoder.decode();
    for (const event of parser.push(decoderTail)) yield event;
    for (const event of parser.finish()) yield event;
  } finally {
    signal.removeEventListener('abort', cancelReader);
    reader.releaseLock();
  }
}
