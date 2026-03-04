import { BrowserRouter, Routes, Route } from "react-router-dom"
import Dashboard from "./pages/Dashboard"
import NewCampaign from "./pages/NewCampaign"
import ApprovalScreen from "./pages/ApprovalScreen"
import Reports from "./pages/Reports"

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<NewCampaign />} />
        <Route path="/approve/:id" element={<ApprovalScreen />} />
        <Route path="/reports/:id" element={<Reports />} />
      </Routes>
    </BrowserRouter>
  )
}