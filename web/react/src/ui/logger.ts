/**
 * Centralized logging utility for MERID UI
 * Environment-aware logging with proper levels
 */

export enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
}

interface LogEntry {
  level: LogLevel;
  message: string;
  data?: any;
  timestamp: Date;
  source?: string;
}

class Logger {
  private static instance: Logger;
  private logs: LogEntry[] = [];
  private maxLogs = 1000;
  private currentLogLevel = LogLevel.INFO;

  private constructor() {
    // Set log level based on environment
    if (process.env.NODE_ENV === 'development') {
      this.currentLogLevel = LogLevel.DEBUG;
    } else {
      this.currentLogLevel = LogLevel.WARN;
    }
  }

  static getInstance(): Logger {
    if (!Logger.instance) {
      Logger.instance = new Logger();
    }
    return Logger.instance;
  }

  private shouldLog(level: LogLevel): boolean {
    return level >= this.currentLogLevel;
  }

  private addLog(level: LogLevel, message: string, data?: any, source?: string): void {
    const entry: LogEntry = {
      level,
      message,
      data,
      timestamp: new Date(),
      source,
    };

    this.logs.push(entry);
    
    // Keep only the most recent logs
    if (this.logs.length > this.maxLogs) {
      this.logs = this.logs.slice(-this.maxLogs);
    }

    // Console output in development
    if (process.env.NODE_ENV === 'development' && this.shouldLog(level)) {
      const timestamp = entry.timestamp.toISOString();
      const prefix = `[${timestamp}] [${LogLevel[level]}] ${source ? `[${source}] ` : ''}`;
      
      switch (level) {
        case LogLevel.DEBUG:
          console.debug(prefix, message, data);
          break;
        case LogLevel.INFO:
          console.info(prefix, message, data);
          break;
        case LogLevel.WARN:
          console.warn(prefix, message, data);
          break;
        case LogLevel.ERROR:
          console.error(prefix, message, data);
          break;
      }
    }
  }

  debug(message: string, data?: any, source?: string): void {
    this.addLog(LogLevel.DEBUG, message, data, source);
  }

  info(message: string, data?: any, source?: string): void {
    this.addLog(LogLevel.INFO, message, data, source);
  }

  warn(message: string, data?: any, source?: string): void {
    this.addLog(LogLevel.WARN, message, data, source);
  }

  error(message: string, data?: any, source?: string): void {
    this.addLog(LogLevel.ERROR, message, data, source);
  }

  getLogs(level?: LogLevel): LogEntry[] {
    if (level !== undefined) {
      return this.logs.filter(log => log.level >= level);
    }
    return [...this.logs];
  }

  clearLogs(): void {
    this.logs = [];
  }

  setLogLevel(level: LogLevel): void {
    this.currentLogLevel = level;
  }
}

// Export singleton instance
export const logger = Logger.getInstance();

// Export convenience functions
export const log = {
  debug: (message: string, data?: any, source?: string) => logger.debug(message, data, source),
  info: (message: string, data?: any, source?: string) => logger.info(message, data, source),
  warn: (message: string, data?: any, source?: string) => logger.warn(message, data, source),
  error: (message: string, data?: any, source?: string) => logger.error(message, data, source),
  getLogs: (level?: LogLevel) => logger.getLogs(level),
  clear: () => logger.clearLogs(),
  setLevel: (level: LogLevel) => logger.setLogLevel(level),
};
