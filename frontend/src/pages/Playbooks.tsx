import { api } from '../api'
import { useResource } from '../hooks'
import PlaybookCard from '../components/PlaybookCard'
import { Card, Empty, ErrorBanner, Loading, PageHeader } from '../components/ui'

export default function Playbooks() {
  const res = useResource(api.playbooks, [], 5000)
  return (
    <div>
      <PageHeader title="Playbooks" subtitle="Per-customer routines the agent learned from approved decisions." />
      {res.error && <ErrorBanner error={res.error} />}
      {res.loading && !res.data ? (
        <Loading />
      ) : res.data && res.data.length === 0 ? (
        <Card><Empty>No playbooks yet. They are proposed once the agent sees a pattern repeat.</Empty></Card>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {res.data?.map((p) => <PlaybookCard key={p.id} p={p} onChanged={res.reload} />)}
        </div>
      )}
    </div>
  )
}
