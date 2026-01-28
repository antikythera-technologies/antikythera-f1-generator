"use client";

import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  hover?: boolean;
  glow?: "cyan" | "red" | "blue" | "purple" | null;
  onClick?: () => void;
}

export function Card({ children, className, hover = false, glow = null, onClick }: CardProps) {
  const glowClasses = {
    cyan: "hover:shadow-glow-cyan",
    red: "hover:shadow-glow-red",
    blue: "hover:shadow-glow-blue",
    purple: "hover:shadow-[0_0_20px_rgba(153,51,255,0.3)]",
  };

  return (
    <div
      onClick={onClick}
      className={cn(
        "rounded-xl border border-white/10 bg-midnight/50 backdrop-blur-lg",
        "transition-all duration-300",
        hover && "cursor-pointer hover:border-neon-cyan/30 hover:bg-midnight/70",
        glow && glowClasses[glow],
        className
      )}
    >
      {children}
    </div>
  );
}

interface CardHeaderProps {
  children: ReactNode;
  className?: string;
}

export function CardHeader({ children, className }: CardHeaderProps) {
  return (
    <div className={cn("border-b border-white/10 px-6 py-4", className)}>
      {children}
    </div>
  );
}

interface CardTitleProps {
  children: ReactNode;
  className?: string;
}

export function CardTitle({ children, className }: CardTitleProps) {
  return (
    <h3 className={cn("text-lg font-semibold text-white", className)}>
      {children}
    </h3>
  );
}

interface CardContentProps {
  children: ReactNode;
  className?: string;
}

export function CardContent({ children, className }: CardContentProps) {
  return <div className={cn("p-6", className)}>{children}</div>;
}

interface CardFooterProps {
  children: ReactNode;
  className?: string;
}

export function CardFooter({ children, className }: CardFooterProps) {
  return (
    <div className={cn("border-t border-white/10 px-6 py-4", className)}>
      {children}
    </div>
  );
}
