import { useEffect, useState } from "react";
import { fetchContext, type ContextInfo } from "../api";

interface Props {
  refresh?: number;
}

export function ContextBar({ refresh = 0 }: Props) {
  const [ctx, setCtx] = useState<ContextInfo | null>(null);

  useEffect(() => {
    fetchContext().then(setCtx).catch(() => {});
  }, [refresh]);

  if (!ctx) return null;

  return (
    <div className="context-bar">
      <span>📍 {ctx.location}</span>
      <span>📅 {ctx.date}</span>
      <span>🕐 {ctx.time}</span>
      {ctx.weather && <span>🌤 {ctx.weather}</span>}
    </div>
  );
}
