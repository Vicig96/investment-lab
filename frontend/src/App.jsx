import { useState } from 'react'
import Instruments from './components/Instruments.jsx'
import PriceIngest from './components/PriceIngest.jsx'
import Prices      from './components/Prices.jsx'
import Indicators  from './components/Indicators.jsx'
import Signals     from './components/Signals.jsx'
import Backtest    from './components/Backtest.jsx'
import Portfolio   from './components/Portfolio.jsx'
import Screener         from './components/Screener.jsx'
import ScreenerRotation from './components/ScreenerRotation.jsx'

const TABS = [
  { id: 'instruments', label: 'Instruments' },
  { id: 'ingest',      label: 'Ingest CSV' },
  { id: 'prices',      label: 'Prices' },
  { id: 'indicators',  label: 'Indicators' },
  { id: 'signals',     label: 'Signals' },
  { id: 'backtest',    label: 'Backtest' },
  { id: 'portfolio',   label: 'Portfolio' },
  { id: 'screener',          label: 'Screener' },
  { id: 'screener-rotation', label: 'Rotation' },
]

export default function App() {
  const [tab, setTab] = useState('instruments')

  return (
    <div className="app">
      <header className="topbar">
        <span className="topbar-logo">⬡ Investment Lab</span>
        <nav className="nav">
          {TABS.map(t => (
            <button
              key={t.id}
              className={`nav-btn${tab === t.id ? ' active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="main">
        {tab === 'instruments' && <Instruments />}
        {tab === 'ingest'      && <PriceIngest />}
        {tab === 'prices'      && <Prices />}
        {tab === 'indicators'  && <Indicators />}
        {tab === 'signals'     && <Signals />}
        {tab === 'backtest'    && <Backtest />}
        {tab === 'portfolio'   && <Portfolio />}
        {tab === 'screener'          && <Screener />}
        {tab === 'screener-rotation' && <ScreenerRotation />}
      </main>
    </div>
  )
}
