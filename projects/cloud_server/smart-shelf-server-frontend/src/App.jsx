import { BrowserRouter, Routes, Route } from "react-router-dom";
import ShelfInterface from "./components/ShelfInterface";
import ProductPage from "./pages/ProductPage";
import UserPage from "./pages/UserPage";
import ReceiptPage from "./pages/ReceiptPage";
import LoginPage from "./pages/LoginPage";
import MainLayout from "./layout/MainLayout";
import TaskPage from "./pages/TaskPage";
import RequireRole from "./components/RequireRole";
import { Dashboard } from "@mui/icons-material";
import DashboardPage from "./pages/DashboardPage";
import ComboPage from "./pages/ComboPage";
import HistoryPage from "./pages/HistoryPage";
import PostersPage from "./pages/PostersPage";
import ConfigPage from "./pages/ConfigPage";
import NotificationPage from "./pages/NotificationPage";
import MachinePage from "./pages/MachinePage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* protect MainLayout + its nested routes */}
        <Route
          element={
            <RequireRole>
              <MainLayout />
            </RequireRole>
          }
        >
          <Route path="/" element={<DashboardPage />} />
          <Route path="/shelf" element={<ShelfInterface />} />
          <Route path="/products" element={<ProductPage />} />
          <Route path="/combo" element={<ComboPage />} />
          <Route path="/users" element={<UserPage />} />
          <Route path="/tasks" element={<TaskPage />} />
          <Route path="/receipts" element={<ReceiptPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/posters" element={<PostersPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="/notifications" element={<NotificationPage />} />
          <Route path="/machine" element={<MachinePage />} />
        </Route>

        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
