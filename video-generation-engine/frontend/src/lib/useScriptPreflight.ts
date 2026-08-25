import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import { ApiError } from "./api";
import { qk } from "./queries";
import { applyBreakSuggestions, scriptCheckKey } from "./script";
import type {
  BreakSuggestion,
  ScriptPreflightResponse,
  ScriptRewriteResponse,
} from "./types";

const DEBOUNCE_MS = 1500;

function errText(err: unknown): string {
  if (err instanceof ApiError) {
    return typeof err.detail === "string" ? err.detail : err.message;
  }
  if (err instanceof Error) return err.message;
  return "Script check failed.";
}

export function useScriptPreflight(opts: {
  name: string;
  script: string;
  style: string;
  frameAspect: string | null;
  languageCode: string | null;
}) {
  const qc = useQueryClient();
  const latest = useRef(opts);
  latest.current = opts;

  const projectIdRef = useRef<string | null>(null);
  const lastSynced = useRef<{
    style: string;
    frameAspect: string | null;
    languageCode: string | null;
  } | null>(null);
  const gen = useRef(0);
  const debounceRef = useRef<number | null>(null);

  const [projectId, setProjectId] = useState<string | null>(null);
  const [result, setResult] = useState<ScriptPreflightResponse | null>(null);
  const [checkedKey, setCheckedKey] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rewrite, setRewrite] = useState<ScriptRewriteResponse | null>(null);
  const [rewriting, setRewriting] = useState(false);
  const [rewriteError, setRewriteError] = useState<string | null>(null);

  const stale =
    result !== null &&
    checkedKey !== scriptCheckKey(opts.script, opts.style);

  const ensureProject = useCallback(async (): Promise<string> => {
    const { name, style, frameAspect, languageCode } = latest.current;
    if (!name.trim()) {
      throw new Error("Give the project a name to check this script.");
    }
    let id = projectIdRef.current;
    if (!id) {
      const project = await api.createProject(name.trim(), {
        render_style: style,
        frame_aspect: frameAspect ?? undefined,
        language_code: languageCode ?? undefined,
      });
      id = project.id;
      projectIdRef.current = id;
      lastSynced.current = { style, frameAspect, languageCode };
      setProjectId(id);
      void qc.invalidateQueries({ queryKey: qk.projects });
      return id;
    }
    const synced = lastSynced.current;
    if (
      !synced ||
      synced.style !== style ||
      synced.frameAspect !== frameAspect
    ) {
      await api.setRenderStyle(id, style, frameAspect);
    }
    if (!synced || synced.languageCode !== languageCode) {
      await api.setLanguage(id, languageCode);
    }
    lastSynced.current = { style, frameAspect, languageCode };
    return id;
  }, [qc]);

  const runCheck = useCallback(async (): Promise<ScriptPreflightResponse | null> => {
    const { script, style } = latest.current;
    if (!script.trim()) {
      setResult(null);
      setCheckedKey(null);
      setError(null);
      return null;
    }
    if (debounceRef.current != null) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    const my = ++gen.current;
    setChecking(true);
    setError(null);
    setRewrite(null);
    setRewriteError(null);
    try {
      const id = await ensureProject();
      const data = await api.preflightScript(id, script, style);
      if (my !== gen.current) return null;
      setResult(data);
      setCheckedKey(scriptCheckKey(script, style));
      return data;
    } catch (err) {
      if (my !== gen.current) return null;
      setError(errText(err));
      return null;
    } finally {
      if (my === gen.current) setChecking(false);
    }
  }, [ensureProject]);

  useEffect(() => {
    if (!opts.script.trim()) {
      gen.current += 1;
      setResult(null);
      setCheckedKey(null);
      setError(null);
      setRewrite(null);
      setChecking(false);
      return;
    }
    if (!opts.name.trim()) return;
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      void runCheck();
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current != null) {
        window.clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, [opts.script, opts.style, opts.frameAspect, opts.name, runCheck]);

  const applyBreaks = useCallback(
    (suggestions: BreakSuggestion[]): string | null => {
      const { script } = latest.current;
      if (!result || stale) return null;
      if (scriptCheckKey(script, latest.current.style) !== checkedKey) return null;
      return applyBreakSuggestions(script, suggestions);
    },
    [result, stale, checkedKey],
  );

  const runRewrite = useCallback(async (): Promise<ScriptRewriteResponse | null> => {
    const { script, style } = latest.current;
    if (!script.trim()) return null;
    setRewriting(true);
    setRewriteError(null);
    try {
      const id = await ensureProject();
      const data = await api.rewriteScript(id, script, style, false);
      setRewrite(data);
      if (!data.attempted) {
        setRewriteError("Rewrite is not available right now (dry-run, or no model configured).");
      } else if (!data.accepted) {
        setRewriteError(
          data.rejection_reasons.length
            ? data.rejection_reasons.join(" ")
            : "The rewrite was rejected — numbers or names would have changed.",
        );
      }
      return data;
    } catch (err) {
      setRewriteError(errText(err));
      return null;
    } finally {
      setRewriting(false);
    }
  }, [ensureProject]);

  return {
    projectId,
    result,
    checking,
    error,
    stale,
    rewrite,
    rewriting,
    rewriteError,
    runCheck,
    ensureProject,
    applyBreaks,
    runRewrite,
    clearRewrite: () => {
      setRewrite(null);
      setRewriteError(null);
    },
  };
}
