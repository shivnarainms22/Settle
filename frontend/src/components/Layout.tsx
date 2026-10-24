import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './AuthProvider'
import { AutonomyBanner, AutonomyControl } from './Autonomy'
import { HealthBanner, HealthIndicator, useHealth } from './Health'
import { useSim } from './SimProvider'
import { ROLE_LABEL, ROLE_STYLE } from '../pages/Login'
import Fingerprint from './Fingerprint'
import VerifyBadge from './VerifyBadge'
import { Button, Chip, ErrorBanner } from './ui'

const NAV = [
  { to: '/', label: 'Command center', end: true },
  { to: '/approvals', label: 'Approvals', badge: true },
  { to: '/worklist', label: 'Worklist' },
  { to: '/customers', label: 'Customers' },
  { to: '/playbooks', label: 'Playbooks' },
  { to: '/eval', label: 'Eval' },
  { to: '/forecast', label: 'Forecast' },
  { to: '/trace/run', label: 'Trace', prefix: '/trace' },
  { to: '/ledger', label: 'Ledger' },
  { to: '/verify', label: 'Verify' },
  { to: '/import', label: 'Bring your books' },
  { to: '/stack', label: 'Why each component' },
]

export default function Layout() {
  const { sim, error } = useSim()
  const { user, logout } = useAuth()
  const health = useHealth()
  const { pathname } = useLocation()
  const pending = sim?.kpis.awaiting_approval_count ?? 0
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col bg-ink-950 px-4 py-6 text-slate-300">
        <div className="mb-8 px-2">
          <div className="text-2xl font-bold tracking-tight text-white">
            Settle<span className="text-indigo-400">.</span>
          </div>
          <div className="mt-1 text-xs text-slate-500">Autonomous accounts receivable</div>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex items-center justify-between rounded-md px-3 py-2 text-sm font-medium transition ${
                  isActive || (n.prefix && pathname.startsWith(n.prefix)) ? 'bg-accent text-white' : 'hover:bg-ink-800 hover:text-white'
                }`
              }
            >
              {n.label}
              {n.badge && pending > 0 && (
                <span className="tnum rounded-full bg-amber-500 px-2 py-0.5 text-xs font-bold text-white">{pending}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-2 text-[11px] leading-relaxed text-slate-500">
          Built at Cal Hacks 13.0
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-7">
        <div className="mb-4 flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          <div className="mr-auto shrink-0"><AutonomyControl /></div>
          <HealthIndicator health={health} />
          {sim && (
            <>
            <Chip className={`${sim.mode === 'import' ? 'bg-emerald-600' : 'bg-slate-500'} px-2.5 text-[10px] font-bold uppercase tracking-wide text-white`}>
              {sim.mode === 'import' ? 'Your books' : 'Simulation'}
            </Chip>
            <Fingerprint sim={sim} />
            <VerifyBadge />
            </>
          )}
          <div className="flex shrink-0 items-center gap-2 whitespace-nowrap">
            <span className="text-sm font-medium text-slate-700">{user.name}</span>
            <Chip className={ROLE_STYLE[user.role]}>{ROLE_LABEL[user.role]}</Chip>
            <Button variant="ghost" className="!py-1 text-xs" onClick={logout}>Log out</Button>
          </div>
        </div>
        <HealthBanner health={health} />
        <AutonomyBanner />
        {error && <ErrorBanner error={error} />}
        <Outlet />
      </main>
    </div>
  )
}
