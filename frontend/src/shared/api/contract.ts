export function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Expected an object');
  }
  return value as Record<string, unknown>;
}

export function asString(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new Error(`Expected ${field} to be a string`);
  }
  return value;
}

export function asOptionalString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return asString(value, field);
}

export function asNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Expected ${field} to be a finite number`);
  }
  return value;
}

export function asBoolean(value: unknown, field: string): boolean {
  if (typeof value !== 'boolean') {
    throw new Error(`Expected ${field} to be a boolean`);
  }
  return value;
}

export function asArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`Expected ${field} to be an array`);
  }
  return value;
}

export function asEnum<const T extends readonly string[]>(
  value: unknown,
  values: T,
  field: string,
): T[number] {
  if (typeof value !== 'string' || !values.includes(value)) {
    throw new Error(`Unexpected ${field}`);
  }
  return value as T[number];
}
