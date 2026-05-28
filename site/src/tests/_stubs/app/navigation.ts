// Stub for `$app/navigation` in vitest mode.
export async function goto(_url: string): Promise<void> {}
export async function invalidate(_url: string): Promise<void> {}
export async function invalidateAll(): Promise<void> {}
export function afterNavigate(_cb: () => void): void {}
export function beforeNavigate(_cb: () => void): void {}
