import { STATUS_TYPES } from "../config/constants";

interface StatusIndicatorProps {
  status: keyof typeof STATUS_TYPES;
  size?: "sm" | "md" | "lg";
  showText?: boolean;
  text?: string;
  tooltip?: string;
  className?: string;
}

export default function StatusIndicator({
  status,
  size = "md",
  showText = true,
  text,
  tooltip,
  className = "",
}: StatusIndicatorProps) {
  const getStatusConfig = () => {
    const statusValue = STATUS_TYPES[status];
    switch (statusValue) {
      case "online":
        return {
          color: "bg-green-500",
          textColor: "text-green-500",
          label: "Online",
          icon: "●",
        };
      case "degraded":
        return {
          color: "bg-yellow-500",
          textColor: "text-yellow-500",
          label: "Degraded",
          icon: "●",
        };
      case "offline":
        return {
          color: "bg-red-500",
          textColor: "text-red-500",
          label: "Offline",
          icon: "●",
        };
      case "good":
        return {
          color: "bg-green-500",
          textColor: "text-green-500",
          label: "Good",
          icon: "●",
        };
      case "warning":
        return {
          color: "bg-orange-500",
          textColor: "text-orange-500",
          label: "Warning",
          icon: "⚠",
        };
      case "bad":
        return {
          color: "bg-red-500",
          textColor: "text-red-500",
          label: "Bad",
          icon: "●",
        };
      default:
        return {
          color: "bg-gray-500",
          textColor: "text-gray-500",
          label: "Unknown",
          icon: "?",
        };
    }
  };

  const getSizeClasses = () => {
    switch (size) {
      case "sm":
        return "w-2 h-2 text-xs";
      case "lg":
        return "w-4 h-4 text-lg";
      default:
        return "w-3 h-3 text-sm";
    }
  };

  const config = getStatusConfig();
  const sizeClasses = getSizeClasses();
  const displayText = text || config.label;

  return (
    <div
      data-testid="status-indicator"
      className={`inline-flex items-center gap-2 ${className}`}
      title={tooltip || displayText}
    >
      <div
        data-testid="status-dot"
        className={`${config.color} ${sizeClasses} rounded-full flex items-center justify-center`}
      >
        <span className={`${sizeClasses} flex items-center justify-center text-white`}>
          {config.icon}
        </span>
      </div>
      
      {showText && (
        <span className={`text-sm font-medium ${config.textColor}`}>
          {displayText}
        </span>
      )}
    </div>
  );
}
