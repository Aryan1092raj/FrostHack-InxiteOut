import { useNavigate, useParams } from "react-router-dom"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
  LineChart, Line, CartesianGrid
} from "recharts"

const optimizationHistory = [
  { iteration: "Campaign 1", open_rate: 28, click_rate: 9 },
  { iteration: "Campaign 2", open_rate: 38, click_rate: 16 },
  { iteration: "Campaign 3", open_rate: 47, click_rate: 24 },
]

const segmentData = [
  { segment: "Young Urban", open_rate: 52, click_rate: 28 },
  { segment: "Female Seniors", open_rate: 61, click_rate: 31 },
  { segment: "Inactive", open_rate: 18, click_rate: 6 },
  { segment: "Mid-age", open_rate: 44, click_rate: 19 },
]

const abData = [
  { variant: "Variant A", open_rate: 42, click_rate: 18 },
  { variant: "Variant B", open_rate: 51, click_rate: 26 },
]

export default function Reports() {
  const navigate = useNavigate()

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
      </div>

      {/* Segment breakdown */}
      <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
        <h2 className="font-semibold text-gray-700 mb-4">👥 Performance by Segment</h2>
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
      </div>

      {/* A/B comparison */}
      <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
        <h2 className="font-semibold text-gray-700 mb-4">🆚 A/B Variant Comparison</h2>
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
      </div>

      {/* Agent insight box */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
        <h2 className="font-semibold text-amber-800 mb-3">🤖 Agent Analysis & Insights</h2>
        <ul className="text-sm text-amber-900 space-y-2">
          <li>✅ Female Senior Citizens: highest click rate at 31% — expand targeting in next campaign</li>
          <li>⚠️ Inactive customers: only 6% click rate — agent will adjust tone or reduce frequency</li>
          <li>✅ Friendly variant (B) outperformed formal variant (A) by 8 percentage points on click rate</li>
          <li>✅ Evening send times produced 40% better open rates than morning across all segments</li>
        </ul>
      </div>

    </div>
  )
}