import React, { useCallback, useEffect, useState } from "react";
import {
  Box, Paper, Typography, Grid, Button, Chip, TextField, IconButton,
  Table, TableBody, TableCell, TableHead, TableRow, Snackbar, Alert,
  CircularProgress, Divider, Tooltip,
} from "@mui/material";
import {
  PlayArrow, Stop, Refresh, Delete, Add, Memory, Videocam,
  Cable, Bluetooth, Psychology, Public, Wifi,
} from "@mui/icons-material";
import {
  AGENT_URL, getHealth, startMachine, stopMachine, getStock, getRfids,
  saveRfids, getLogs, MachineHealth, StockRow,
} from "../service/machine.service";

/**
 * Máy & Thẻ - drives the shelf itself through the Control Agent on the Jetson.
 * Works with no internet: the agent is on the shelf's own wifi.
 */
const HEALTH_ITEMS: Array<{ key: keyof MachineHealth; label: string; icon: React.ReactNode }> = [
  { key: "container", label: "Container", icon: <Memory /> },
  { key: "camera", label: "Camera", icon: <Videocam /> },
  { key: "serial", label: "Cổng cân (serial)", icon: <Cable /> },
  { key: "bluetooth", label: "Bluetooth", icon: <Bluetooth /> },
  { key: "engine", label: "Model AI", icon: <Psychology /> },
  { key: "internet", label: "Internet", icon: <Public /> },
];

const MachinePage: React.FC = () => {
  const [health, setHealth] = useState<MachineHealth | null>(null);
  const [stock, setStock] = useState<StockRow[]>([]);
  const [rfids, setRfids] = useState<string[]>([]);
  const [newCard, setNewCard] = useState("");
  const [logs, setLogs] = useState("");
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
  const [toast, setToast] = useState<{ msg: string; sev: "success" | "error" | "info" } | null>(null);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await getHealth());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await refreshHealth();
    try {
      setStock(await getStock());
      setRfids(await getRfids());
    } catch {
      /* agent unreachable - health banner already says so */
    }
  }, [refreshHealth]);

  useEffect(() => {
    refreshAll();
    const t = setInterval(refreshHealth, 4000);
    return () => clearInterval(t);
  }, [refreshAll, refreshHealth]);

  const act = async (kind: "start" | "stop") => {
    setBusy(true);
    try {
      const msg = kind === "start" ? await startMachine() : await stopMachine();
      setToast({ msg, sev: "success" });
      setTimeout(refreshAll, 1500);
    } catch (e: any) {
      setToast({ msg: "Không gọi được máy: " + e.message, sev: "error" });
    } finally {
      setBusy(false);
    }
  };

  const addCard = () => {
    const v = newCard.trim();
    if (v && !rfids.includes(v)) setRfids([...rfids, v]);
    setNewCard("");
  };

  const persistCards = async (cards: string[]) => {
    try {
      const msg = await saveRfids(cards);
      setRfids(cards);
      setToast({ msg, sev: "success" });
    } catch (e: any) {
      setToast({ msg: "Lưu thẻ lỗi: " + e.message, sev: "error" });
    }
  };

  const loadLogs = async () => {
    try {
      setLogs(await getLogs());
    } catch (e: any) {
      setLogs("Không đọc được log: " + e.message);
    }
  };

  const running = !!health?.vending_running;

  return (
    <Box sx={{ p: { xs: 1, md: 3 } }}>
      <Typography variant="h5" gutterBottom>
        Máy &amp; Thẻ
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Điều khiển trực tiếp kệ qua Control Agent · {AGENT_URL}
      </Typography>

      {offline && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Không kết nối được máy. Hãy nối wifi <b>SmartShelf-CS17IUH</b> rồi thử lại.
        </Alert>
      )}

      <Grid container spacing={2}>
        {/* Health + control */}
        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Tình trạng máy
            </Typography>
            <Grid container spacing={1}>
              {HEALTH_ITEMS.map((it) => {
                const ok = !!health?.[it.key];
                return (
                  <Grid item xs={6} sm={4} key={String(it.key)}>
                    <Box
                      sx={{
                        display: "flex", alignItems: "center", gap: 1, p: 1,
                        borderRadius: 1, border: "1px solid",
                        borderColor: ok ? "success.light" : "error.light",
                        bgcolor: ok ? "rgba(46,125,50,0.08)" : "rgba(211,47,47,0.08)",
                      }}
                    >
                      <Box sx={{ color: ok ? "success.main" : "error.main", display: "flex" }}>
                        {it.icon}
                      </Box>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="caption" display="block" noWrap>
                          {it.label}
                        </Typography>
                        <Typography variant="body2" fontWeight={600}
                          color={ok ? "success.main" : "error.main"}>
                          {ok ? "OK" : "chưa"}
                        </Typography>
                      </Box>
                    </Box>
                  </Grid>
                );
              })}
              <Grid item xs={12}>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1, mt: 0.5 }}>
                  <Wifi fontSize="small" color="action" />
                  <Typography variant="body2" color="text.secondary" noWrap>
                    {health?.wifi || "—"}
                  </Typography>
                </Box>
              </Grid>
            </Grid>

            <Divider sx={{ my: 2 }} />

            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1.5 }}>
              <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                Vòng bán hàng
              </Typography>
              <Chip
                size="small"
                color={running ? "success" : "warning"}
                label={running ? "Đang chạy" : "Chưa chạy"}
              />
            </Box>
            <Box sx={{ display: "flex", gap: 1 }}>
              <Button
                fullWidth variant="contained" color="success" size="large"
                startIcon={busy ? <CircularProgress size={18} color="inherit" /> : <PlayArrow />}
                disabled={busy || offline}
                onClick={() => act("start")}
              >
                Khởi động máy
              </Button>
              <Button
                fullWidth variant="contained" color="error" size="large"
                startIcon={<Stop />} disabled={busy || offline}
                onClick={() => act("stop")}
              >
                Dừng máy
              </Button>
            </Box>
          </Paper>
        </Grid>

        {/* RFID cards */}
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Thẻ quản trị (RFID)
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Thẻ trong danh sách này được quyền nạp hàng trên kệ.
            </Typography>
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, my: 1.5, minHeight: 40 }}>
              {rfids.length ? rfids.map((c, i) => (
                <Chip
                  key={c} label={c}
                  onDelete={() => persistCards(rfids.filter((_, j) => j !== i))}
                  deleteIcon={<Delete />}
                />
              )) : (
                <Typography variant="body2" color="text.secondary">Chưa có thẻ nào</Typography>
              )}
            </Box>
            <Box sx={{ display: "flex", gap: 1 }}>
              <TextField
                size="small" fullWidth label="Mã thẻ mới" value={newCard}
                onChange={(e) => setNewCard(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addCard()}
                placeholder="vd 0001529690"
              />
              <Tooltip title="Thêm vào danh sách">
                <span>
                  <IconButton color="primary" onClick={addCard} disabled={!newCard.trim()}>
                    <Add />
                  </IconButton>
                </span>
              </Tooltip>
            </Box>
            <Button
              fullWidth variant="contained" sx={{ mt: 1.5 }}
              disabled={offline} onClick={() => persistCards(rfids)}
            >
              Lưu thẻ vào máy
            </Button>
          </Paper>
        </Grid>

        {/* Stock */}
        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 2 }}>
            <Box sx={{ display: "flex", alignItems: "center", mb: 1 }}>
              <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                Tồn kho theo ngăn
              </Typography>
              <IconButton size="small" onClick={refreshAll}><Refresh /></IconButton>
            </Box>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Ngăn</TableCell>
                  <TableCell>Vị trí</TableCell>
                  <TableCell>Sản phẩm</TableCell>
                  <TableCell align="right">SL</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {stock.map((s) => (
                  <TableRow key={s.slot}>
                    <TableCell>{s.slot}</TableCell>
                    <TableCell>T{s.floor}·C{s.column}</TableCell>
                    <TableCell>{s.name}</TableCell>
                    <TableCell align="right">
                      {s.err
                        ? <Chip size="small" color="error" variant="outlined" label={s.err} />
                        : s.qty}
                    </TableCell>
                  </TableRow>
                ))}
                {!stock.length && (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Typography variant="body2" color="text.secondary">
                        Chưa có dữ liệu
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            <Typography variant="caption" color="text.secondary">
              Mã 200/222 = đặt sai vị trí · 255 = lỗi đọc cân
            </Typography>
          </Paper>
        </Grid>

        {/* Logs */}
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 2 }}>
            <Box sx={{ display: "flex", alignItems: "center", mb: 1 }}>
              <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                Nhật ký máy
              </Typography>
              <IconButton size="small" onClick={loadLogs}><Refresh /></IconButton>
            </Box>
            <Box
              component="pre"
              sx={{
                m: 0, p: 1.5, borderRadius: 1, bgcolor: "grey.900", color: "grey.100",
                fontSize: 11, lineHeight: 1.5, maxHeight: 320, overflow: "auto",
              }}
            >
              {logs || "Bấm nút tải lại để xem log"}
            </Box>
          </Paper>
        </Grid>
      </Grid>

      <Snackbar
        open={!!toast} autoHideDuration={4000} onClose={() => setToast(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert severity={toast?.sev || "info"} onClose={() => setToast(null)}>
          {toast?.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default MachinePage;
