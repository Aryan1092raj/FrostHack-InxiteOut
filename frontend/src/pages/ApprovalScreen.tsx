import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { approveCampaign, rejectCampaign, getCampaign } from "../lib/api"
import { useEffect } from "react"

export default function ApprovalScreen() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [campaign, setCampaign] = useState<any>(null)
  const [showRejectBox, setShowRejectBox] = useState(false)
  const [rejectNote, setRejectNote] = useState("")

  useEffect(() => {
    getCampaign(id!).then(setCampaign)
  }, [id])

  if (!campaign) return <div className="p-6">Loading...</div>

  const handleApprove = async () => {
    await approveCampaign(id!)
    navigate(`/reports/${id}`)
  }

  const handleRejectSubmit = async () => {
    await rejectCampaign(id!, rejectNote)
    navigate(`/new?replan=${id}&note=${encodeURIComponent(rejectNote)}`)
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6 max-w-3xl mx-auto">

      <button onClick={() => navigate("/")} className="text-gray-400 text-sm mb-6 hover:text-gray-600">
        ← Back to Dashboard
      </button>

      <h1 className="text-xl font-bold text-gray-800 mb-1">Review Campaign</h1>
      <p className="text-gray-500 text-sm mb-6">Review the AI-generated campaign below. Approve to schedule it, or reject with feedback.</p>

      {/* Email previews */}
      {(campaign.emails || []).map((email: any, i: number) => (
        <div key={i} className="bg-white rounded-xl shadow-sm p-5 mb-4 border-l-4 border-purple-400">
          <div className="flex justify-between items-center mb-3">
            <span className="text-xs font-bold bg-purple-100 text-purple-700 px-3 py-1 rounded-full">
              {email.variant.replace("_", " ").toUpperCase()}
            </span>
            <span className="text-xs text-gray-400">
              → {email.customer_ids.length} customers · Sends at: {campaign.strategy?.send_times?.[i] || campaign.strategy?.send_times?.[0] || "TBD"}
            </span>
          </div>
          <p className="font-semibold text-gray-800 mb-2">Subject: {email.subject}</p>
          <div className="bg-gray-50 rounded-lg p-3">
            <p className="text-sm text-gray-700 whitespace-pre-wrap">{email.body}</p>
          </div>
        </div>
      ))}

      {/* Summary box */}
      {campaign.strategy && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 mb-6 text-sm text-blue-800">
          <p className="font-semibold mb-1">Campaign Summary</p>
          <p>Total segments: {campaign.strategy.segments?.length || 0}</p>
          <p>A/B variants: {campaign.strategy.ab_variants?.length || 0}</p>
          <p>Total customers targeted: {campaign.strategy.segments?.flat().length || 0}</p>
        </div>
      )}

      {/* Action buttons */}
      {!showRejectBox ? (
        <div className="flex gap-4">
          <button onClick={handleApprove} className="flex-1 bg-green-600 hover:bg-green-700 text-white py-3 rounded-xl font-semibold text-lg">
            ✅ Approve & Schedule
          </button>
          <button onClick={() => setShowRejectBox(true)} className="flex-1 bg-red-500 hover:bg-red-600 text-white py-3 rounded-xl font-semibold text-lg">
            ❌ Reject
          </button>
        </div>
      ) : (
        <div className="bg-red-50 border border-red-200 rounded-xl p-5">
          <p className="font-semibold text-red-700 mb-3">Tell the agent what to fix:</p>
          <textarea
            className="w-full border border-red-200 rounded-lg p-3 text-sm h-28 resize-none focus:outline-none focus:ring-2 focus:ring-red-300"
            placeholder='e.g. "Make the tone more formal. Only target active customers. Move send time to evening."'
            value={rejectNote}
            onChange={(e) => setRejectNote(e.target.value)}
          />
          <div className="flex gap-3 mt-3">
            <button onClick={handleRejectSubmit} className="bg-red-600 text-white px-6 py-2 rounded-lg text-sm font-semibold">
              Send Feedback & Re-plan
            </button>
            <button onClick={() => setShowRejectBox(false)} className="text-gray-500 px-4 py-2 text-sm hover:text-gray-700">
              Cancel
            </button>
          </div>
        </div>
      )}

    </div>
  )
}