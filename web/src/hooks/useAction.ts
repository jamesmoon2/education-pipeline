import { useCallback, useState } from "react";
import { ApiRequestError } from "../api/client";

interface RunOptions<T> {
  retryWithOverwrite?: () => Promise<T>;
  successMessage?: string;
}

export function useAction(onSuccess?: () => void) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  const run = useCallback(
    async <T>(fn: () => Promise<T>, opts: RunOptions<T> = {}): Promise<boolean> => {
      setBusy(true);
      setFeedback(null);
      setIsError(false);
      try {
        try {
          await fn();
        } catch (err) {
          const conflict =
            err instanceof ApiRequestError &&
            err.status === 409 &&
            err.code === "already_exists";
          if (
            conflict &&
            opts.retryWithOverwrite &&
            window.confirm(`${(err as Error).message}\n\nOverwrite?`)
          ) {
            await opts.retryWithOverwrite();
          } else {
            throw err;
          }
        }
        setFeedback(opts.successMessage ?? "Done.");
        onSuccess?.();
        return true;
      } catch (err) {
        setIsError(true);
        setFeedback(err instanceof Error ? err.message : String(err));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [onSuccess],
  );

  return { busy, feedback, isError, run };
}
