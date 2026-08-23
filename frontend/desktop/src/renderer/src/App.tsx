import { DesktopLayout } from './layout/DesktopLayout'
import { AppStateProvider } from './lib/app-state'

export function App() {
  return (
    <AppStateProvider>
      <DesktopLayout />
    </AppStateProvider>
  )
}
