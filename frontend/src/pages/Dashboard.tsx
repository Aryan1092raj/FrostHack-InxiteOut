import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getCampaigns } from "../lib/api"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

// This is the shape of a campaign object — TypeScript needs to know this
interface Campaign {
  id: string
  status: string
  brief: string
  metrics: {
    open_rate: number
    click_rate: number
    total_sent: number
  }
  created_at: string
}

// Color coding for each status so users know at a glance what's happening
const statusStyles: Record<string, string> = {
  planning: "bg-blue-100 text-blue-700",
  awaiting_approval: "bg-yellow-100 text-yellow-800",
  running: "bg-green-100 text-green-700",
  monitoring: "bg-teal-100 text-teal-700",
  optimizing: "bg-purple-100 text-purple-700",
  done: "bg-gray-100 text-gray-600",
}

export default function Dashboard() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const navigate = useNavigate()

  // When the page loads, fetch campaigns
  useEffect(() => {
    getCampaigns()
      .then(data => setCampaigns(data as Campaign[]))
      .catch(() => setCampaigns([]))
  }, [])

  // Build chart data from campaigns
  const chartData = campaigns.map((c, i) => ({
    name: `Campaign ${i + 1}`,
    open_rate: Math.round(c.metrics.open_rate * 100),
    click_rate: Math.round(c.metrics.click_rate * 100),
  }))

  return (
    <div className="min-h-screen bg-gray-50 p-6">

      {/* Header */}
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">CampaignX</h1>
          <p className="text-gray-500 text-sm">AI-Powered Marketing for SuperBFSI</p>
        </div>
        <button
          onClick={() => navigate("/new")}
          className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg font-semibold"
        >
          + New Campaign
        </button>
      </div>

      {/* Performance Chart */}
      {campaigns.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
          <h2 className="font-semibold text-gray-700 mb-4">Overall Performance Trend</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <XAxis dataKey="name" />
              <YAxis unit="%" />
              <Tooltip />
              <Bar dataKey="open_rate" fill="#a5b4fc" name="Open Rate %" />
              <Bar dataKey="click_rate" fill="#6ee7b7" name="Click Rate %" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Campaign List */}
      <div className="space-y-3">
        <h2 className="font-semibold text-gray-700">All Campaigns</h2>
        {campaigns.map(campaign => (
          <div key={campaign.id} className="bg-white rounded-xl shadow-sm p-4 flex justify-between items-center">
            <div>
              <p className="font-medium text-gray-800 mb-1">{campaign.brief.slice(0, 70)}...</p>
              <div className="flex items-center gap-3">
                <span className={`text-xs px-2 py-1 rounded font-medium ${statusStyles[campaign.status] || "bg-gray-100 text-gray-500"}`}>
                  {campaign.status.replace("_", " ").toUpperCase()}
                </span>
                <span className="text-xs text-gray-400">
                  Opens: {Math.round(campaign.metrics.open_rate * 100)}% · Clicks: {Math.round(campaign.metrics.click_rate * 100)}%
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              {campaign.status === "awaiting_approval" && (
                <button
                  onClick={() => navigate(`/approve/${campaign.id}`)}
                  className="bg-yellow-500 text-white px-4 py-2 rounded-lg text-sm font-semibold"
                >
                  Review
                </button>
              )}
              <button
                onClick={() => navigate(`/reports/${campaign.id}`)}
                className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg text-sm"
              >
                Report
              </button>
            </div>
          </div>
        ))}
      </div>

    </div>
  )
}