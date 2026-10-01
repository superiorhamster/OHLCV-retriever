import {
  UniverseResponse,
  RetrieverStatus,
  StartJobParams,
  PreviewResponse,
  ChartResponse
} from './types';

const BASE_URL = '/api';

export async function fetchUniverse(): Promise<UniverseResponse> {
  const res = await fetch(`${BASE_URL}/universe`);
  if (!res.ok) throw new Error(`Failed to fetch universe: ${res.statusText}`);
  return res.json();
}

export async function fetchRetrieverStatus(): Promise<RetrieverStatus> {
  const res = await fetch(`${BASE_URL}/retriever/status`);
  if (!res.ok) throw new Error(`Failed to fetch retriever status: ${res.statusText}`);
  return res.json();
}

export async function startRetriever(params: StartJobParams): Promise<{ status: string; symbols_count: number }> {
  const res = await fetch(`${BASE_URL}/retriever/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to start retriever: ${res.statusText}`);
  }
  return res.json();
}

export async function stopRetriever(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE_URL}/retriever/stop`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed to stop retriever: ${res.statusText}`);
  return res.json();
}

export async function fetchPreview(
  symbol: string,
  slice: 'head' | 'tail' | 'all' = 'head',
  limit: number = 20,
  sort: 'asc' | 'desc' = 'desc'
): Promise<PreviewResponse> {
  const params = new URLSearchParams({
    slice,
    limit: limit.toString(),
    sort
  });
  const res = await fetch(`${BASE_URL}/preview/${symbol}?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to preview ${symbol}: ${res.statusText}`);
  return res.json();
}

export async function fetchChart(symbol: string): Promise<ChartResponse> {
  const res = await fetch(`${BASE_URL}/chart/${symbol}`);
  if (!res.ok) throw new Error(`Failed to load chart for ${symbol}: ${res.statusText}`);
  return res.json();
}

export function getExportUrl(symbol: string): string {
  return `${BASE_URL}/export/${symbol}`;
}
