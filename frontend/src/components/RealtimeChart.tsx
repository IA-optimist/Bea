import { useMemo } from 'react';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

interface DataPoint {
  timestamp: string;
  value: number;
  [key: string]: any;
}

interface RealtimeChartProps {
  data: DataPoint[];
  dataKeys: { key: string; name: string; color: string }[];
  title?: string;
  type?: 'line' | 'area';
  height?: number;
  yAxisLabel?: string;
  showLegend?: boolean;
  maxDataPoints?: number;
}

export const RealtimeChart = ({
  data,
  dataKeys,
  title,
  type = 'line',
  height = 300,
  yAxisLabel,
  showLegend = true,
  maxDataPoints = 30,
}: RealtimeChartProps) => {
  // Keep only the most recent data points
  const trimmedData = useMemo(() => {
    return data.slice(-maxDataPoints);
  }, [data, maxDataPoints]);

  // Format timestamp for display
  const formatTime = (timestamp: string) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      });
    } catch {
      return timestamp;
    }
  };

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload || !payload.length) return null;

    return (
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3 shadow-lg">
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          {formatTime(label)}
        </p>
        {payload.map((entry: any, index: number) => (
          <div key={index} className="flex items-center gap-2 text-sm">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-gray-700 dark:text-gray-300">
              {entry.name}:
            </span>
            <span className="font-semibold text-gray-900 dark:text-white">
              {typeof entry.value === 'number'
                ? entry.value.toFixed(2)
                : entry.value}
            </span>
          </div>
        ))}
      </div>
    );
  };

  const ChartComponent = type === 'area' ? AreaChart : LineChart;

  return (
    <div className="space-y-2">
      {title && (
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {title}
        </h3>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <ChartComponent
          data={trimmedData}
          margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#e5e7eb"
            className="dark:stroke-gray-700"
          />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatTime}
            stroke="#9ca3af"
            style={{ fontSize: '12px' }}
            interval="preserveStartEnd"
            minTickGap={50}
          />
          <YAxis
            stroke="#9ca3af"
            style={{ fontSize: '12px' }}
            label={
              yAxisLabel
                ? {
                    value: yAxisLabel,
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: '12px', fill: '#9ca3af' },
                  }
                : undefined
            }
          />
          <Tooltip content={<CustomTooltip />} />
          {showLegend && (
            <Legend
              wrapperStyle={{ fontSize: '12px' }}
              iconType="circle"
            />
          )}
          {dataKeys.map((key) =>
            type === 'area' ? (
              <Area
                key={key.key}
                type="monotone"
                dataKey={key.key}
                name={key.name}
                stroke={key.color}
                fill={key.color}
                fillOpacity={0.3}
                strokeWidth={2}
                animationDuration={300}
                dot={false}
              />
            ) : (
              <Line
                key={key.key}
                type="monotone"
                dataKey={key.key}
                name={key.name}
                stroke={key.color}
                strokeWidth={2}
                dot={false}
                animationDuration={300}
              />
            )
          )}
        </ChartComponent>
      </ResponsiveContainer>
    </div>
  );
};
