declare module 'vite' {
  export function defineConfig(config: unknown): unknown
}

declare module '@vitejs/plugin-react' {
  export default function react(): unknown
}

declare module 'react' {
  export type ReactNode = unknown
  export interface RefObject<T> {
    current: T | null
  }
  export interface MutableRefObject<T> {
    current: T
  }
  export interface MouseEvent<T = Element> {
    target: EventTarget | T
    preventDefault(): void
  }
  export function StrictMode(props: { children?: unknown }): unknown
  export function useCallback<T extends (...args: never[]) => unknown>(callback: T, deps?: unknown[]): T
  export function useEffect(effect: () => void | (() => void), deps?: unknown[]): void
  export function useLayoutEffect(effect: () => void | (() => void), deps?: unknown[]): void
  export function useMemo<T>(factory: () => T, deps?: unknown[]): T
  export function useRef<T>(initialValue: T): MutableRefObject<T>
  export function useRef<T>(initialValue: T | null): RefObject<T>
  export function useState<T>(initialState: T): [T, (value: T | ((previous: T) => T)) => void]
}

declare module 'react-dom/client' {
  export function createRoot(container: Element | DocumentFragment): {
    render(node: unknown): void
  }
}

declare module 'react/jsx-runtime' {
  export const Fragment: unknown
  export function jsx(type: unknown, props: unknown, key?: unknown): unknown
  export function jsxs(type: unknown, props: unknown, key?: unknown): unknown
}

declare namespace JSX {
  interface IntrinsicElements {
    [elemName: string]: unknown
  }
}
