"use client";

import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface StatsWidgetProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  trend?: {
    value: number;
    label?: string;
  };
  color?: "cyan" | "red" | "blue" | "green" | "purple" | "orange";
  className?: string;
}

export function StatsWidget({
  title,
  value,
  subtitle,
  icon,
  trend,
  color = "cyan",
  className,
}: StatsWidgetProps) {
  const colorClasses = {
    cyan: "from-neon-cyan/20 to-transparent border-neon-cyan/30 text-neon-cyan",
    red: "from-racing-red/20 to-transparent border-racing-red/30 text-racing-red",
    blue: "from-electric-blue/20 to-transparent border-electric-blue/30 text-electric-blue",
    green: "from-success-green/20 to-transparent border-success-green/30 text-success-green",
    purple: "from-cyber-purple/20 to-transparent border-cyber-purple/30 text-cyber-purple",
    orange: "from-warning-orange/20 to-transparent border-warning-orange/30 text-warning-orange",
  };

  const trendColor = trend && trend.value > 0 ? "text-success-green" : "text-racing-red";

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border bg-gradient-to-br p-6",
        "backdrop-blur-lg transition-all duration-300",
        "hover:scale-[1.02] hover:shadow-lg",
        colorClasses[color],
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-white/60">{title}</p>
          <p className="mt-2 text-3xl font-bold text-white">{value}</p>
          {subtitle && (
            <p className="mt-1 text-sm text-white/50">{subtitle}</p>
          )}
          {trend && (
            <div className={cn("mt-2 flex items-center gap-1 text-sm", trendColor)}>
              <span>{trend.value > 0 ? "↑" : "↓"}</span>
              <span>{Math.abs(trend.value)}%</span>
              {trend.label && <span className="text-white/50">{trend.label}</span>}
            </div>
          )}
        </div>
        {icon && (
          <div className={cn("rounded-lg p-3", `bg-gradient-to-br ${colorClasses[color].split(" ")[0]}`)}>
            {icon}
          </div>
        )}
      </div>
      
      {/* Decorative corner accent */}
      <div
        className={cn(
          "absolute -right-4 -top-4 h-24 w-24 rounded-full opacity-20 blur-2xl",
          color === "cyan" && "bg-neon-cyan",
          color === "red" && "bg-racing-red",
          color === "blue" && "bg-electric-blue",
          color === "green" && "bg-success-green",
          color === "purple" && "bg-cyber-purple",
          color === "orange" && "bg-warning-orange"
        )}
      />
    </div>
  );
}
