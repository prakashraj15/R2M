"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "@/lib/api";
import { useLive, errorText } from "./LiveProvider";
export function useResource<T>(path: string | null) {
  const { session } = useLive();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const version = useRef(0);
  const reload = useCallback(async () => {
    const v = ++version.current;
    setData(null);
    setError("");
    if (!path || !session) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const next = await request<T>(path);
      if (v === version.current) setData(next);
    } catch (e) {
      if (v === version.current) setError(errorText(e));
    } finally {
      if (v === version.current) setLoading(false);
    }
  }, [path, session?.user.id]);
  useEffect(() => {
    void reload();
    return () => {
      version.current++;
    };
  }, [reload]);
  return { data, error, loading, reload };
}
export function ResourceStatus({
  error,
  loading,
}: {
  error: string;
  loading: boolean;
}) {
  return (
    <>
      {loading && (
        <p role="status" className="soft-note">
          Loading from backend…
        </p>
      )}
      {error && (
        <p role="alert" className="live-error">
          {error}
        </p>
      )}
    </>
  );
}
