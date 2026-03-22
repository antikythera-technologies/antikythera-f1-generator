"use client";

import Link from "next/link";
import { Team } from "@/lib/api";
import { Card, CardContent } from "@/components/ui";

interface TeamCardProps {
  team: Team;
}

export function TeamCard({ team }: TeamCardProps) {
  return (
    <Link href={`/teams/${team.id}`}>
      <Card hover glow="cyan" className="overflow-hidden">
        {/* Colour bar at top */}
        <div className="flex h-3">
          {team.primary_colour && (
            <div className="flex-1" style={{ backgroundColor: team.primary_colour }} />
          )}
          {team.secondary_colour && (
            <div className="flex-1" style={{ backgroundColor: team.secondary_colour }} />
          )}
          {team.accent_colour && (
            <div className="flex-1" style={{ backgroundColor: team.accent_colour }} />
          )}
        </div>

        <CardContent className="space-y-3">
          <div>
            <h3 className="text-lg font-bold text-white">{team.name}</h3>
            {team.constructor_name && (
              <p className="text-sm text-white/50">{team.constructor_name}</p>
            )}
          </div>

          <div className="space-y-1.5 text-sm">
            {team.principal_name && (
              <div className="flex items-center gap-2 text-white/60">
                <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                <span>{team.principal_name}</span>
              </div>
            )}
            {team.engine_supplier && (
              <div className="flex items-center gap-2 text-white/60">
                <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                <span>{team.engine_supplier}</span>
              </div>
            )}
            {team.headquarters && (
              <div className="flex items-center gap-2 text-white/60">
                <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <span>{team.headquarters}</span>
              </div>
            )}
          </div>

          {team.car_description && (
            <p className="line-clamp-2 text-xs text-white/40">{team.car_description}</p>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
