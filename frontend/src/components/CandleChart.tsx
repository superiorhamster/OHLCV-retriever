import React, { useEffect, useRef } from 'react';
import { createChart, IChartApi, ColorType } from 'lightweight-charts';
import { CandleData, VolumeData } from '../types';

interface CandleChartProps {
  candles: CandleData[];
  volumes: VolumeData[];
  symbol: string;
}

export const CandleChart: React.FC<CandleChartProps> = ({ candles, volumes, symbol }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current || candles.length === 0) return;

    // Create chart instance
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#090d16' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        vertLine: { color: '#475569', width: 1, style: 1 },
        horzLine: { color: '#475569', width: 1, style: 1 },
      },
      rightPriceScale: {
        borderColor: '#334155',
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: 380,
    });

    chartRef.current = chart;

    // Add Candlestick Series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    // Add Volume Series
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '', // overlay
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    // Sort ascending by time
    const sortedCandles = [...candles].sort((a, b) => (a.time > b.time ? 1 : -1));
    const sortedVolumes = [...volumes].sort((a, b) => (a.time > b.time ? 1 : -1));

    candleSeries.setData(sortedCandles);
    volumeSeries.setData(sortedVolumes);

    chart.timeScale().fitContent();

    // Resize handler
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [candles, volumes]);

  if (candles.length === 0) {
    return (
      <div className="h-80 flex items-center justify-center text-slate-500 text-sm bg-slate-950/60 rounded-lg border border-slate-800">
        No candlestick price points available for {symbol}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-slate-400 px-1">
        <span>Candlestick & Volume ({candles.length} sessions)</span>
        <span className="font-mono text-emerald-400 font-bold">{symbol}</span>
      </div>
      <div
        ref={chartContainerRef}
        className="w-full h-[380px] rounded-lg overflow-hidden border border-slate-800 bg-[#090d16]"
      />
    </div>
  );
};
