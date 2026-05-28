/**
 * Vitest setup — Node 25 added a built-in `localStorage` global that lacks
 * `removeItem` / `clear`. When jsdom is also enabled, Node's incomplete shim
 * still wins. This polyfill replaces both with a Map-backed implementation
 * that's reset between test runs.
 */
class MemoryStorage implements Storage {
	private store = new Map<string, string>();
	get length(): number {
		return this.store.size;
	}
	key(index: number): string | null {
		return Array.from(this.store.keys())[index] ?? null;
	}
	getItem(key: string): string | null {
		return this.store.has(key) ? this.store.get(key)! : null;
	}
	setItem(key: string, value: string): void {
		this.store.set(key, String(value));
	}
	removeItem(key: string): void {
		this.store.delete(key);
	}
	clear(): void {
		this.store.clear();
	}
}

Object.defineProperty(globalThis, 'localStorage', {
	value: new MemoryStorage(),
	writable: true,
	configurable: true
});
Object.defineProperty(globalThis, 'sessionStorage', {
	value: new MemoryStorage(),
	writable: true,
	configurable: true
});
Object.defineProperty(window, 'localStorage', {
	value: globalThis.localStorage,
	writable: true,
	configurable: true
});
Object.defineProperty(window, 'sessionStorage', {
	value: globalThis.sessionStorage,
	writable: true,
	configurable: true
});

// @testing-library/jest-dom matchers — `toBeInTheDocument`, `toHaveAttribute`,
// etc. Pulled in via setup so individual test files don't repeat the import.
import '@testing-library/jest-dom/vitest';
