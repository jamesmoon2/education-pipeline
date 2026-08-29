import { useCallback, useState } from "react";
import { ApiRequestError } from "../api/client";

interface RunOptions<T> {
  retryWithOverwrite?: () => Promise<T>;
  /** A function form is for actions whose outcome is only known once they
   *  have run (e.g. "Approve & continue", whose message depends on how far
   *  the chain got); it sees the value the action resolved with. */
  successMessage?: string | ((value: T) => string);
  /** For actions that resolve with a partial outcome — nothing threw, but
   *  part of the work did not land (an approval whose follow-up failed) —
   *  so the feedback must not read as a plain success. Tone only: onSuccess
   *  still runs, because the part that did land has to be reflected. */
  errorTone?: (value: T) => boolean;
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
        let value: T;
        try {
          value = await fn();
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
            value = await opts.retryWithOverwrite();
          } else {
            throw err;
          }
        }
        const { successMessage } = opts;
        setFeedback(
          typeof successMessage === "function"
            ? successMessage(value)
            : successMessage ?? "Done.",
        );
        setIsError(opts.errorTone?.(value) ?? false);
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
