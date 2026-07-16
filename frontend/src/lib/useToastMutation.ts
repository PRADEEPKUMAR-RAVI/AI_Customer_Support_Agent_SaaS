import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { toast } from "sonner";

interface ToastMutationOptions<TData, TVariables> {
  mutationFn: (variables: TVariables) => Promise<TData>;
  /** Toast shown on success — a plain string, or derived from the result/variables. */
  successMessage: string | ((data: TData, variables: TVariables) => string);
  /** Shown only when the thrown error has no message of its own. */
  errorMessage?: string;
  /** Query keys to invalidate once the mutation settles successfully. */
  invalidateKeys?: QueryKey[];
  /** Extra caller-specific side effect (reset a form, close a dialog, clear local state, ...). */
  onSuccess?: (data: TData, variables: TVariables) => void;
}

/** Wraps `useMutation` with the "mutate → toast → invalidate → reset/close" shape repeated across
 * nearly every feature page in the console. Reach for `useMutation` directly instead when a call
 * site needs bespoke error handling beyond a toast (rare — most just need the message). */
export function useToastMutation<TData, TVariables>({
  mutationFn,
  successMessage,
  errorMessage = "Please try again.",
  invalidateKeys = [],
  onSuccess,
}: ToastMutationOptions<TData, TVariables>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (data, variables) => {
      const message =
        typeof successMessage === "function" ? successMessage(data, variables) : successMessage;
      toast.success(message);
      invalidateKeys.forEach((key) => void qc.invalidateQueries({ queryKey: key }));
      onSuccess?.(data, variables);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : errorMessage),
  });
}
