import { useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { startCampaign } from "../lib/api"

// Each event the agent sends looks like this
interface AgentEvent {
  agent: string
  message: string
  type: string
}

// Color for each agent's name label
const agentColors: Record<string, string> = {
  profiler: "text-blue-400",
  strategist: "text-purple-400",
  content_gen: "text-green-400",
  executor: "text-orange-400",
  monitor: "text-teal-400",
  optimizer: "text-red-400",
}
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"

export default function NewCampaign() {
  const [brief, setBrief] = useState("")
  const [campaignId, setCampaignId] = useState<string | null>(null)
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [approvalReady, setApprovalReady] = useState(false)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // If this is a re-plan after rejection, show the original feedback
  const replanNote = searchParams.get("note")
  const replanCampaignId = searchParams.get("campaign_id")

  // Auto-connect to existing campaign stream if this is a re-plan.
  useEffect(() => {
    if (!replanCampaignId) return

    setCampaignId(replanCampaignId)
    const es = new EventSource(`${API_URL}/api/campaign/${replanCampaignId}/stream`)

    es.onmessage = (e) => {
      const event = JSON.parse(e.data)
      setEvents((prev) => [...prev, event])

      if (event.type === "approval_needed") {
        setApprovalReady(true)
        es.close()
      } else if (event.type === "done" || event.type === "error") {
        es.close()
      }
    }

    es.onerror = () => es.close()

    return () => es.close()
  }, [replanCampaignId])

  const handleLaunch = async () => {
    if (!brief.trim()) return
    setLoading(true)
    setEvents([])
    setApprovalReady(false)

    const result = await startCampaign(brief)
    setCampaignId(result.campaign_id)
    setLoading(false)

    // ---- DAY 6 SSE replacement ----
    const es = new EventSource(`${API_URL}/api/campaign/${result.campaign_id}/stream`)

    es.onmessage = (e) => {
      const event = JSON.parse(e.data)
      setEvents((prev) => [...prev, event])

      if (event.type === "approval_needed") {
        setApprovalReady(true)
        es.close()
      } else if (event.type === "done" || event.type === "error") {
        es.close()
      }
    }

    es.onerror = (err) => {
      console.error("SSE Error:", err)
      es.close()
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6 max-w-2xl mx-auto">

      {/* Back button */}
      <button onClick={() => navigate("/")} className="text-gray-400 text-sm mb-6 hover:text-gray-600">
        ← Back to Dashboard
      </button>

      <h1 className="text-xl font-bold text-gray-800 mb-2">New Campaign</h1>
      <p className="text-gray-500 text-sm mb-6">Type your campaign brief in plain English. The AI agents will handle the rest.</p>

      {/* Re-plan notice */}
      {replanNote && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 mb-4 text-sm text-orange-800">
          <p className="font-semibold">🔄 Re-planning based on your feedback:</p>
          <p className="mt-1 italic">"{replanNote}"</p>
        </div>
      )}

      {/* Brief input — only show if agent hasn't started yet */}
      {!campaignId && (
        <>
          <textarea
            className="w-full border border-gray-200 rounded-lg p-4 h-40 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
            placeholder='e.g. "Run email campaign for launching XDeposit, a flagship term deposit product from SuperBFSI, that gives 1 percentage point higher returns than its competitors. Announce an additional 0.25 percentage point higher returns for female senior citizens..."'
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
          />
          <button
            onClick={handleLaunch}
            disabled={loading || !brief.trim()}
            className="mt-3 w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white py-3 rounded-lg font-semibold"
          >
            {loading ? "Starting agents..." : "🚀 Launch AI Agents"}
          </button>
        </>
      )}

      {/* Live agent stream — shows once campaign starts */}
      {campaignId && (
        <div className="mt-4">
          <h2 className="font-semibold text-gray-700 mb-2">🤖 Agents Working...</h2>
          <div className="bg-gray-900 rounded-xl p-4 h-72 overflow-y-auto font-mono text-sm space-y-2">
            {events.map((e, i) => (
              <div key={i} className="flex gap-2">
                <span className={`font-bold shrink-0 ${agentColors[e.agent] || "text-white"}`}>
                  [{e.agent}]
                </span>
                <span className="text-gray-200">{e.message}</span>
              </div>
            ))}
            {events.length === 0 && (
              <span className="text-gray-500">Initializing agents...</span>
            )}
          </div>

          {/* Approve button appears when agents are done */}
          {approvalReady && (
            <button
              onClick={() => navigate(`/approve/${campaignId}`)}
              className="mt-4 w-full bg-yellow-500 hover:bg-yellow-600 text-white py-3 rounded-lg font-semibold"
            >
              👀 Review & Approve Campaign →
            </button>
          )}
        </div>
      )}

    </div>
  )
}
