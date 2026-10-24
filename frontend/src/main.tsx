import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import Layout from './components/Layout'
import { AuthGate } from './components/AuthProvider'
import { SimProvider } from './components/SimProvider'
import CommandCenter from './pages/CommandCenter'
import Approvals from './pages/Approvals'
import Customers from './pages/Customers'
import CustomerDetailPage from './pages/CustomerDetail'
import Playbooks from './pages/Playbooks'
import DecisionDetailPage from './pages/DecisionDetail'
import Eval from './pages/Eval'
import Ledger from './pages/Ledger'
import Trace from './pages/Trace'
import Forecast from './pages/Forecast'
import Verify from './pages/Verify'
import Import from './pages/Import'
import Stack from './pages/Stack'
import Worklist from './pages/Worklist'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthGate>
      <SimProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<CommandCenter />} />
            <Route path="approvals" element={<Approvals />} />
            <Route path="worklist" element={<Worklist />} />
            <Route path="customers" element={<Customers />} />
            <Route path="customers/:id" element={<CustomerDetailPage />} />
            <Route path="playbooks" element={<Playbooks />} />
            <Route path="decisions/:id" element={<DecisionDetailPage />} />
            <Route path="eval" element={<Eval />} />
            <Route path="ledger" element={<Ledger />} />
            <Route path="trace/:ref" element={<Trace />} />
            <Route path="forecast" element={<Forecast />} />
            <Route path="verify" element={<Verify />} />
            <Route path="import" element={<Import />} />
            <Route path="stack" element={<Stack />} />
            <Route path="*" element={<div className="py-16 text-center text-slate-500">Page not found</div>} />
          </Route>
        </Routes>
      </SimProvider>
      </AuthGate>
    </BrowserRouter>
  </StrictMode>,
)
