import { Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Empty, Spinner } from './components/ui'
import { featureUis } from './lib/feature'
import { PlantProvider } from './plant'
import { Shell } from './Shell'

export default function App() {
  const hasHome = featureUis.some((f) => f.route === '/')
  return (
    <PlantProvider>
      <Shell>
        <Suspense fallback={<div className="p-6"><Spinner /></div>}>
          <Routes>
            {featureUis.map((f) => (
              <Route key={f.id} path={f.route} element={<f.element />} />
            ))}
            {!hasHome && <Route path="/" element={<Navigate to="/features" replace />} />}
            <Route path="*" element={<div className="p-6"><Empty>Page not found.</Empty></div>} />
          </Routes>
        </Suspense>
      </Shell>
    </PlantProvider>
  )
}
