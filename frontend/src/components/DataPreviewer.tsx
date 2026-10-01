import React, { useState, useEffect } from 'react';
import {
  Table,
  BarChart3,
  Download,
  AlertCircle,
  FileSpreadsheet,
  Search,
  ArrowUpDown,
  Filter,
  CheckCircle,
  Calendar,
  DollarSign,
  TrendingUp,
  TrendingDown
} from 'lucide-react';
import { UniverseSymbol, PreviewResponse, ChartResponse } from '../types';
import { fetchPreview, fetchChart, getExportUrl } from '../api';
import { CandleChart } from './CandleChart';

interface DataPreviewerProps {
  universe: UniverseSymbol[];
  selectedSymbol?: string;
  onSelectSymbol: (symbol: string) => void;
}

export const DataPreviewer: React.FC<DataPreviewerProps> = ({
  universe,
  selectedSymbol,
  onSelectSymbol,
}) => {
  const [sliceMode, setSliceMode] = useState<'head' | 'tail'>('head');
  const [limit, setLimit] = useState<number>(20);
  const [sort, setSort] = useState<'desc' | 'asc'>('desc');
  const [activeTab, setActiveTab] = useState<'table' | 'chart'>('table');
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [chartData, setChartData] = useState<ChartResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [symbolSearch, setSymbolSearch] = useState('');

  // Symbols that have local parquet data
  const retrievedSymbols = universe.filter(s => s.has_data);

  // Default to first retrieved symbol if none selected
  const activeSymbol = selectedSymbol || (retrievedSymbols.length > 0 ? retrievedSymbols[0].symbol : '');

  // Load preview data
  useEffect(() => {
    if (!activeSymbol) return;

    let isMounted = true;
    setLoading(true);

    Promise.all([
      fetchPreview(activeSymbol, sliceMode, limit, sort).catch(err => {
        console.error('Preview error:', err);
        return null;
      }),
      fetchChart(activeSymbol).catch(err => {
        console.error('Chart error:', err);
        return null;
      })
    ]).then(([prevData, cData]) => {
      if (!isMounted) return;
      setPreview(prevData);
      setChartData(cData);
      setLoading(false);
    });

    return () => {
      isMounted = false;
    };
  }, [activeSymbol, sliceMode, limit, sort]);

  const filteredRetrieved = retrievedSymbols.filter(s =>
    s.symbol.toUpperCase().includes(symbolSearch.trim().toUpperCase())
  );

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
      {/* Header & Ticker Picker */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-2">
          <FileSpreadsheet className="w-5 h-5 text-emerald-400" />
          <h2 className="text-base font-semibold text-white">Data Preview & Analysis</h2>
          {retrievedSymbols.length > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-mono">
              {retrievedSymbols.length} available
            </span>
          )}
        </div>

        {/* Symbol Selector Bar */}
        <div className="flex items-center space-x-2">
          <div className="relative">
            <select
              value={activeSymbol}
              onChange={e => onSelectSymbol(e.target.value)}
              className="pl-3 pr-8 py-1.5 bg-slate-950 border border-slate-700/80 rounded-lg text-xs font-mono font-bold text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              {retrievedSymbols.length === 0 ? (
                <option value="">No local data yet</option>
              ) : (
                retrievedSymbols.map(s => (
                  <option key={s.symbol} value={s.symbol}>
                    {s.symbol} ({s.row_count} rows)
                  </option>
                ))
              )}
            </select>
          </div>

          {activeSymbol && (
            <a
              href={getExportUrl(activeSymbol)}
              download={`${activeSymbol}_ohlcv.csv`}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg border border-slate-700 transition-colors"
            >
              <Download className="w-3.5 h-3.5 text-emerald-400" />
              <span>Export CSV</span>
            </a>
          )}
        </div>
      </div>

      {retrievedSymbols.length === 0 ? (
        <div className="py-16 text-center text-slate-500 space-y-2">
          <AlertCircle className="w-8 h-8 mx-auto text-slate-600" />
          <div className="text-sm font-medium text-slate-400">No Retrieved Datasets Found</div>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            Select one or more tickers above and click <strong>Start Retrieval</strong> to collect and save canonical OHLCV datasets.
          </p>
        </div>
      ) : (
        <>
          {/* Summary Metric Cards */}
          {preview && preview.has_data && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                <div className="text-[11px] text-slate-400 flex items-center space-x-1">
                  <DatabaseIcon className="w-3 h-3 text-emerald-400" />
                  <span>Total Records</span>
                </div>
                <div className="text-lg font-bold font-mono text-white mt-1">
                  {preview.total_rows?.toLocaleString()}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">sessions stored</div>
              </div>

              <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                <div className="text-[11px] text-slate-400 flex items-center space-x-1">
                  <Calendar className="w-3 h-3 text-blue-400" />
                  <span>Date Range</span>
                </div>
                <div className="text-xs font-bold font-mono text-white mt-1 truncate">
                  {preview.earliest_date} → {preview.latest_date}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">point-in-time window</div>
              </div>

              <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                <div className="text-[11px] text-slate-400 flex items-center space-x-1">
                  <TrendingUp className="w-3 h-3 text-emerald-400" />
                  <span>Latest Price</span>
                </div>
                <div className="text-lg font-bold font-mono text-emerald-400 mt-1">
                  {(
                    preview.metrics?.latest_quote?.close ||
                    preview.metrics?.latest_quote?.provider_close ||
                    0
                  ).toLocaleString()}{' '}
                  <span className="text-xs font-normal text-slate-500">VND</span>
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  as of {preview.latest_date}
                </div>
              </div>

              <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                <div className="text-[11px] text-slate-400 flex items-center space-x-1">
                  <CheckCircle className="w-3 h-3 text-amber-400" />
                  <span>Price Provenance</span>
                </div>
                <div className="text-xs font-bold text-amber-300 mt-1">
                  {preview.metrics?.has_raw_prices ? 'Raw Unadjusted' : 'Chart-Adjusted'}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5 truncate">
                  {preview.metrics?.has_raw_prices
                    ? 'Verified raw transaction prices'
                    : 'Provider chart feed (kbs/vci)'}
                </div>
              </div>
            </div>
          )}

          {/* Controls & View Switcher */}
          <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-950/70 p-3 rounded-lg border border-slate-800">
            {/* Slice Controls: Head vs Tail vs Limit */}
            <div className="flex items-center space-x-2">
              <span className="text-xs text-slate-400 font-medium">Slice:</span>
              <div className="flex bg-slate-900 border border-slate-800 rounded-md p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => setSliceMode('head')}
                  className={`px-2.5 py-1 rounded transition-colors ${
                    sliceMode === 'head'
                      ? 'bg-emerald-500 text-white font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Head (First N)
                </button>
                <button
                  type="button"
                  onClick={() => setSliceMode('tail')}
                  className={`px-2.5 py-1 rounded transition-colors ${
                    sliceMode === 'tail'
                      ? 'bg-emerald-500 text-white font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Tail (Last N)
                </button>
              </div>

              <div className="flex items-center space-x-1.5 ml-2">
                <span className="text-xs text-slate-400">Rows:</span>
                <select
                  value={limit}
                  onChange={e => setLimit(parseInt(e.target.value, 10))}
                  className="px-2 py-1 bg-slate-900 border border-slate-800 rounded text-xs text-white"
                >
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>

              <button
                type="button"
                onClick={() => setSort(s => (s === 'desc' ? 'asc' : 'desc'))}
                className="flex items-center space-x-1 px-2 py-1 bg-slate-900 border border-slate-800 hover:bg-slate-800 rounded text-xs text-slate-300 ml-2"
                title="Toggle sort order"
              >
                <ArrowUpDown className="w-3 h-3 text-slate-400" />
                <span className="uppercase">{sort}</span>
              </button>
            </div>

            {/* View Tab Switcher: Table vs Chart */}
            <div className="flex bg-slate-900 border border-slate-800 rounded-md p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setActiveTab('table')}
                className={`flex items-center space-x-1.5 px-3 py-1 rounded transition-colors ${
                  activeTab === 'table'
                    ? 'bg-slate-800 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Table className="w-3.5 h-3.5" />
                <span>Table</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('chart')}
                className={`flex items-center space-x-1.5 px-3 py-1 rounded transition-colors ${
                  activeTab === 'chart'
                    ? 'bg-slate-800 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <BarChart3 className="w-3.5 h-3.5 text-emerald-400" />
                <span>Interactive Chart</span>
              </button>
            </div>
          </div>

          {/* Main Content View */}
          {loading ? (
            <div className="h-64 flex items-center justify-center text-slate-400 text-sm">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-emerald-500 mr-2"></div>
              <span>Loading {activeSymbol} dataset...</span>
            </div>
          ) : activeTab === 'chart' && chartData ? (
            <CandleChart
              candles={chartData.candles}
              volumes={chartData.volumes}
              symbol={activeSymbol}
            />
          ) : preview && preview.has_data && preview.rows ? (
            <div className="border border-slate-800 rounded-lg overflow-hidden bg-slate-950">
              <div className="overflow-x-auto max-h-96">
                <table className="w-full text-xs text-left border-collapse">
                  <thead className="bg-slate-900/90 text-slate-400 uppercase font-mono tracking-wider sticky top-0 border-b border-slate-800">
                    <tr>
                      <th className="py-2.5 px-3 font-semibold">Date</th>
                      <th className="py-2.5 px-3 font-semibold text-right">Close (VND)</th>
                      <th className="py-2.5 px-3 font-semibold text-right">Open (VND)</th>
                      <th className="py-2.5 px-3 font-semibold text-right">High (VND)</th>
                      <th className="py-2.5 px-3 font-semibold text-right">Low (VND)</th>
                      <th className="py-2.5 px-3 font-semibold text-right">Volume</th>
                      <th className="py-2.5 px-3 font-semibold">Quality Flags</th>
                      <th className="py-2.5 px-3 font-semibold">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {preview.rows.map((row, i) => {
                      const closeVal = row.close ?? row.provider_close;
                      const openVal = row.open ?? row.provider_open;
                      const highVal = row.high ?? row.provider_high;
                      const lowVal = row.low ?? row.provider_low;
                      const isUp = closeVal !== null && openVal !== null && closeVal >= openVal;

                      return (
                        <tr key={i} className="hover:bg-slate-900/40 transition-colors">
                          <td className="py-2 px-3 font-bold text-white whitespace-nowrap">
                            {row.date}
                          </td>
                          <td
                            className={`py-2 px-3 text-right font-bold whitespace-nowrap ${
                              isUp ? 'text-emerald-400' : 'text-red-400'
                            }`}
                          >
                            {closeVal?.toLocaleString() ?? '—'}
                          </td>
                          <td className="py-2 px-3 text-right text-slate-300 whitespace-nowrap">
                            {openVal?.toLocaleString() ?? '—'}
                          </td>
                          <td className="py-2 px-3 text-right text-slate-300 whitespace-nowrap">
                            {highVal?.toLocaleString() ?? '—'}
                          </td>
                          <td className="py-2 px-3 text-right text-slate-300 whitespace-nowrap">
                            {lowVal?.toLocaleString() ?? '—'}
                          </td>
                          <td className="py-2 px-3 text-right text-slate-300 whitespace-nowrap">
                            {row.volume?.toLocaleString() ?? '—'}
                          </td>
                          <td className="py-2 px-3 whitespace-nowrap">
                            {row.quality_flags ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                                {row.quality_flags}
                              </span>
                            ) : (
                              <span className="text-[10px] text-slate-500">ok</span>
                            )}
                          </td>
                          <td className="py-2 px-3 text-slate-400 uppercase text-[11px] whitespace-nowrap">
                            {row.source}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="py-10 text-center text-slate-500 text-xs">
              No preview rows to display.
            </div>
          )}
        </>
      )}
    </div>
  );
};

function DatabaseIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 5V19A9 3 0 0 0 21 19V5" />
      <path d="M3 12A9 3 0 0 0 21 12" />
    </svg>
  );
}
