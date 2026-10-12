"use client";
import { useEffect, useState } from "react";
import { request } from "@/lib/api";
/** Fetch one live R2M resource for a screen; null while loading or unavailable. */
export function useLive<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let live = true;
    if (path) request<T>(path).then((d) => live && setData(d)).catch(() => live && setData(null));
    return () => {
      live = false;
    };
  }, [path]);
  return data;
}
