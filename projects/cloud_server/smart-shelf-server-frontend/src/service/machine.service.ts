import axios from "axios";

/**
 * Talks to the Control Agent running on the Jetson HOST (systemd, port 8088).
 *
 * This is deliberately NOT the cloud backend: the agent lives on the shelf
 * itself, so the machine can be started, stopped and inspected over the
 * shelf's own wifi with no internet at all.
 *
 * Override with VITE_AGENT_URL when the shelf is reachable at another address
 * (e.g. the old iPhone-hotspot layout on 172.20.10.7).
 */
export const AGENT_URL: string =
  import.meta.env.VITE_AGENT_URL || "http://10.42.0.1:8088";

// Short default: health polls every few seconds, so an unreachable shelf must
// surface as "offline" quickly rather than hanging. Start/stop opt into longer.
const agent = axios.create({ baseURL: AGENT_URL, timeout: 6000 });
const SLOW = { timeout: 60000 };

export interface MachineHealth {
  container: boolean;
  vending_running: boolean;
  camera: boolean;
  serial: boolean;
  bluetooth: boolean;
  engine: boolean;
  wifi: string;
  internet: boolean;
}

export interface StockRow {
  slot: number;
  floor: number;
  column: number;
  name: string;
  qty: number;
  err: string;
}

export const getHealth = async (): Promise<MachineHealth> =>
  (await agent.get("/api/health")).data;

export const startMachine = async (): Promise<string> =>
  (await agent.post("/api/start", null, SLOW)).data?.result ?? "";

export const stopMachine = async (): Promise<string> =>
  (await agent.post("/api/stop", null, SLOW)).data?.result ?? "";

export const getStock = async (): Promise<StockRow[]> =>
  (await agent.get("/api/stock")).data;

export const getRfids = async (): Promise<string[]> =>
  (await agent.get("/api/rfids")).data;

export const saveRfids = async (cards: string[]): Promise<string> =>
  (await agent.post("/api/rfids", cards)).data?.result ?? "";

export const getLogs = async (): Promise<string> =>
  (await agent.get("/api/logs", SLOW)).data;
