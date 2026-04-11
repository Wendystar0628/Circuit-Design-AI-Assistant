declare module 'vite' {
  export function defineConfig(config: unknown): unknown
}

declare module '@vitejs/plugin-react' {
  export default function react(): unknown
}

declare module 'react' {
  export type ReactNode = unknown
  export function StrictMode(props: { children?: unknown }): unknown
  export function useEffect(effect: () => void | (() => void), deps?: unknown[]): void
  export function useMemo<T>(factory: () => T, deps?: unknown[]): T
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

declare module '*.css' {
  const value: string
  export default value
}

declare namespace JSX {
  interface Element {}
  interface IntrinsicElements {
    [elemName: string]: unknown
  }
}
