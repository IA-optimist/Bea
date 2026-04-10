import { useEffect, useRef, useState, useCallback } from 'react';

export interface WebSocketMessage<T = any> {
  data: T;
  timestamp: string;
}

export interface UseWebSocketOptions {
  // Reconnect on close
  reconnect?: boolean;
  // Reconnect interval in ms
  reconnectInterval?: number;
  // Max reconnect attempts (0 = unlimited)
  maxReconnectAttempts?: number;
  // Called when connection opens
  onOpen?: () => void;
  // Called when connection closes
  onClose?: () => void;
  // Called on error
  onError?: (error: Event) => void;
  // Called when receiving message
  onMessage?: (data: any) => void;
}

export interface UseWebSocketReturn<T> {
  // Latest received data
  data: T | null;
  // Connection status
  isConnected: boolean;
  // Is attempting to reconnect
  isReconnecting: boolean;
  // Connection error
  error: string | null;
  // Manually reconnect
  reconnect: () => void;
  // Manually disconnect
  disconnect: () => void;
  // Send message (if needed for bi-directional communication)
  send: (data: any) => void;
}

/**
 * Custom hook for WebSocket connections with auto-reconnect.
 * 
 * @example
 * ```tsx
 * const { data, isConnected } = useWebSocket<MetricsData>(
 *   'ws://localhost:8000/ws/metrics',
 *   {
 *     reconnect: true,
 *     onMessage: (data) => console.log('Received:', data)
 *   }
 * );
 * ```
 */
export function useWebSocket<T = any>(
  url: string | null,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn<T> {
  const {
    reconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 0,
    onOpen,
    onClose,
    onError,
    onMessage,
  } = options;

  const [data, setData] = useState<T | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const shouldReconnectRef = useRef(true);

  const connect = useCallback(() => {
    if (!url) return;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WebSocket] Connected to', url);
        setIsConnected(true);
        setIsReconnecting(false);
        setError(null);
        reconnectAttemptsRef.current = 0;
        onOpen?.();
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          setData(parsed);
          onMessage?.(parsed);
        } catch (err) {
          console.error('[WebSocket] Failed to parse message:', err);
        }
      };

      ws.onerror = (event) => {
        console.error('[WebSocket] Error:', event);
        setError('WebSocket connection error');
        onError?.(event);
      };

      ws.onclose = () => {
        console.log('[WebSocket] Disconnected');
        setIsConnected(false);
        wsRef.current = null;
        onClose?.();

        // Attempt reconnect if enabled
        if (
          reconnect &&
          shouldReconnectRef.current &&
          (maxReconnectAttempts === 0 || reconnectAttemptsRef.current < maxReconnectAttempts)
        ) {
          setIsReconnecting(true);
          reconnectAttemptsRef.current += 1;
          
          console.log(
            `[WebSocket] Reconnecting... (attempt ${reconnectAttemptsRef.current}${
              maxReconnectAttempts > 0 ? `/${maxReconnectAttempts}` : ''
            })`
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        } else {
          setIsReconnecting(false);
          if (reconnectAttemptsRef.current >= maxReconnectAttempts && maxReconnectAttempts > 0) {
            setError('Max reconnection attempts reached');
          }
        }
      };
    } catch (err) {
      console.error('[WebSocket] Connection failed:', err);
      setError('Failed to establish WebSocket connection');
    }
  }, [url, reconnect, reconnectInterval, maxReconnectAttempts, onOpen, onClose, onError, onMessage]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsConnected(false);
    setIsReconnecting(false);
  }, []);

  const manualReconnect = useCallback(() => {
    shouldReconnectRef.current = true;
    reconnectAttemptsRef.current = 0;
    disconnect();
    setTimeout(connect, 100);
  }, [connect, disconnect]);

  const send = useCallback((data: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    } else {
      console.warn('[WebSocket] Cannot send, connection not open');
    }
  }, []);

  useEffect(() => {
    if (url) {
      shouldReconnectRef.current = true;
      connect();
    }

    return () => {
      disconnect();
    };
  }, [url, connect, disconnect]);

  return {
    data,
    isConnected,
    isReconnecting,
    error,
    reconnect: manualReconnect,
    disconnect,
    send,
  };
}
