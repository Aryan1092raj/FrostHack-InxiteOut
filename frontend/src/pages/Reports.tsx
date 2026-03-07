import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { getCampaign, getCampaignReports } from "../lib/api"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
  LineChart, Line, CartesianGrid
} from "recharts"

export default function Reports() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [campaign, setCampaign] = useState<any>(null)
  const [reports, setReports] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getCampaign(id!),
      getCampaignReports(id!)
    ]).then(([camp, reps]) => {
      setCampaign(camp)
      setReports(reps)
      setLoading(false)
    })
  }, [id])

  if (loading || !campaign) return <div className="p-6">Loading report...</div>

  // 1. Build Optimization Cycle Progress
  const optimizationHistory = reports.map((r, i) => ({
    iteration: `Cycle ${i + 1}`,
    open_rate: Math.round(r.open_rate * 100),
    click_rate: Math.round(r.click_rate * 100),
  }))

  // 2. Build Segment Breakdown (from latest report)
  const latestReport = reports[reports.length - 1]
  const rawData = latestReport?.raw_report?.data || []

  const segments = campaign.strategy?.segments || []
  const segmentData = segments.map((seg: any) => {
    const custIds = new Set(seg.customer_ids)
    const segmentContacts = rawData.filter((r: any) => custIds.has(r.customer_id))
    const total = segmentContacts.length
    const opens = segmentContacts.filter((r: any) => r.EO === "Y").length
    const clicks = segmentContacts.filter((r: any) => r.EC === "Y").length

    return {
      segment: seg.name,
      open_rate: total > 0 ? Math.round((opens / total) * 100) : 0,
      click_rate: total > 0 ? Math.round((clicks / total) * 100) : 0,
    }
  })

  // 3. Build A/B Breakdown
  const emails = campaign.emails || []
  const abData = emails.map((email: any) => {
    const custIds = new Set(email.customer_ids)
    const variantContacts = rawData.filter((r: any) => custIds.has(r.customer_id))
    const total = variantContacts.length
    const opens = variantContacts.filter((r: any) => r.EO === "Y").length
    const clicks = variantContacts.filter((r: any) => r.EC === "Y").length

    return {
      variant: email.variant.replace("_", " ").toUpperCase(),
      open_rate: total > 0 ? Math.round((opens / total) * 100) : 0,
      click_rate: total > 0 ? Math.round((clicks / total) * 100) : 0,
    }
  })

  // 4. Get Agent analysis
  const agentAnalysis = campaign.metrics?.analysis
    || latestReport?.raw_report?.computed_metrics?.analysis
    || "Agent is still analyzing performance data..."

  return (
    <div className="min-h-screen bg-gray-50 p-6 max-w-4xl mx-auto">

      <button onClick={() => navigate("/")} className="text-gray-400 text-sm mb-6 hover:text-gray-600">
        ← Back to Dashboard
      </button>

      <h1 className="text-xl font-bold text-gray-800 mb-8">Campaign Performance Report</h1>

      {/* Optimization loop progress */}
      <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
        <h2 className="font-semibold text-gray-700 mb-1">📈 Optimization Loop Progress</h2>
        <p className="text-xs text-gray-400 mb-4">Each point = one agent-run campaign iteration</p>
        {optimizationHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={optimizationHistory}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="iteration" />
              <YAxis unit="%" />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="open_rate" stroke="#6366f1" name="Open Rate %" strokeWidth={2} dot />
              <Line type="monotone" dataKey="click_rate" stroke="#22c55e" name="Click Rate %" strokeWidth={2} dot />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-gray-400 italic">No historical data yet. Waiting for first execution...</p>
        )}
      </div>

      {/* Segment breakdown */}
      <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
        <h2 className="font-semibold text-gray-700 mb-4">👥 Performance by Segment</h2>
        {segmentData.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={segmentData}>
              <XAxis dataKey="segment" />
              <YAxis unit="%" />
              <Tooltip />
              <Legend />
              <Bar dataKey="open_rate" fill="#818cf8" name="Open Rate %" />
              <Bar dataKey="click_rate" fill="#34d399" name="Click Rate %" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-gray-400 italic">Segment data will appear once the campaign is executed.</p>
        )}
      </div>

      {/* A/B comparison */}
      <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
        <h2 className="font-semibold text-gray-700 mb-4">🆚 A/B Variant Comparison</h2>
        {abData.length > 0 ? (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={abData} layout="vertical">
              <XAxis type="number" unit="%" />
              <YAxis type="category" dataKey="variant" width={100} />
              <Tooltip />
              <Legend />
              <Bar dataKey="open_rate" fill="#818cf8" name="Open Rate %" />
              <Bar dataKey="click_rate" fill="#34d399" name="Click Rate %" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-gray-400 italic">A/B data will appear once the campaign is executed.</p>
        )}
      </div>

      {/* Agent insight box */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
        <h2 className="font-semibold text-amber-800 mb-3">🤖 Agent Analysis & Insights</h2>
        <div className="text-sm text-amber-900 leading-relaxed">
          {agentAnalysis}
        </div>
      </div>

    </div>
  )
}
