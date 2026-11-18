import { useState } from 'react'
import { Page, Tabs } from '../../components/ui'
import AbPanel, { type Ab } from './AbPanel'
import Calculator from './Calculator'

export default function Value() {
  const [tab, setTab] = useState<'ab' | 'roi'>('ab')
  const [ab, setAb] = useState<Ab | null>(null)
  return (
    <Page title="Value realization" subtitle="Two pieces of evidence: (1) a controlled A/B replay on the simulated plant - identical seeds and fault schedule, swarm OFF vs ON - with confidence intervals; (2) the ROI / Azure-consumed-revenue calculator built on the business-case model, which can be seeded with the A/B result.">
      <Tabs tabs={[{ id: 'ab', label: 'A/B value realization' }, { id: 'roi', label: 'ROI / ACR calculator' }]} value={tab} onChange={setTab} />
      <div className={tab === 'ab' ? '' : 'hidden'}><AbPanel onResult={setAb} /></div>
      {tab === 'roi' && <Calculator ab={ab} />}
    </Page>
  )
}
