export interface UniverseSymbol {
  symbol: string;
  company_name: string;
  status: 'current' | 'historical' | string;
  listing_date?: string | null;
  delisting_date?: string | null;
  has_data: boolean;
  row_count: number;
  start_date?: string | null;
  end_date?: string | null;
}

export interface UniverseResponse {
  total: number;
  current: number;
  historical: number;
  with_data: number;
  symbols: UniverseSymbol[];
}

export interface JobCounts {
  DONE: number;
  RUNNING: number;
  PENDING: number;
  PARTIAL: number;
  FAILED: number;
}

export interface LogEntry {
  time: string;
  level: string;
  message: string;
}

export interface RetrieverStatus {
  is_running: boolean;
  run_id: string;
  total_targets: number;
  counts: JobCounts;
  active_symbols: string[];
  logs: LogEntry[];
}

export interface StartJobParams {
  symbols: string[] | 'ALL';
  mode: 'full' | 'update';
  start_date?: string;
  end_date?: string;
  workers?: number;
  providers?: string[];
  refresh?: boolean;
}

export interface PreviewMetrics {
  raw_prices_count: number;
  chart_prices_count: number;
  has_raw_prices: boolean;
  quality_flags: string[];
  latest_quote?: Record<string, any>;
}

export interface PreviewResponse {
  has_data: boolean;
  symbol: string;
  message?: string;
  total_rows?: number;
  slice?: 'head' | 'tail' | 'all';
  limit?: number;
  sort?: 'asc' | 'desc';
  earliest_date?: string;
  latest_date?: string;
  metrics?: PreviewMetrics;
  columns?: string[];
  rows?: Record<string, any>[];
}

export interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumeData {
  time: string;
  value: number;
  color: string;
}

export interface ChartResponse {
  symbol: string;
  candles: CandleData[];
  volumes: VolumeData[];
}
