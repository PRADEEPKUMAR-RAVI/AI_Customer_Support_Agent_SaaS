/** FE-Auth — `/reset`. The reset link lands here with `?token=...`. Sets a new password via the
 * single-use token, then sends the user to sign in. Same split-card shell as `/signup`, `/login`,
 * and `/forgot` (`AuthBrand.tsx`) — a user following a reset-password email link shouldn't land
 * on a visually plainer page than the rest of the auth flow. */

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { api, unwrap } from "@/lib/api";

import { AuthSplitShell } from "./AuthBrand";

const resetSchema = z
  .object({
    new_password: z.string().min(8, "Use at least 8 characters"),
    confirm: z.string().min(1, "Confirm your new password"),
  })
  .refine((values) => values.new_password === values.confirm, {
    message: "Passwords don't match",
    path: ["confirm"],
  });

type ResetValues = z.infer<typeof resetSchema>;

export function ResetPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const navigate = useNavigate();

  const form = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { new_password: "", confirm: "" },
  });

  const mutation = useMutation({
    mutationFn: async (values: ResetValues) =>
      unwrap(
        await api.POST("/api/v1/auth/reset-password", {
          body: { token: token ?? "", new_password: values.new_password },
        }),
      ),
    onSuccess: () => {
      toast.success("Password updated", { description: "Sign in with your new password." });
      navigate("/login", { replace: true });
    },
    onError: (err) =>
      toast.error("Couldn't reset password", {
        description: err instanceof Error ? err.message : "The link may have expired.",
      }),
  });

  if (!token) {
    return (
      <AuthSplitShell>
        <div className="space-y-6">
          <div className="relative grid size-14 place-items-center">
            <div aria-hidden className="absolute size-14 rounded-full bg-destructive/25 blur-md" />
            <div className="relative grid size-14 place-items-center rounded-full border-2 border-destructive/40 bg-background text-destructive">
              <AlertCircle className="size-6" />
            </div>
          </div>
          <div className="space-y-2">
            <h1 className="text-xl font-semibold tracking-tight">Invalid reset link</h1>
            <p className="text-xs text-muted-foreground">
              This link is missing its token. Request a new one to continue.
            </p>
          </div>
          <Button asChild size="lg" variant="outline" className="w-full">
            <Link to="/forgot">Request a new link</Link>
          </Button>
        </div>
      </AuthSplitShell>
    );
  }

  return (
    <AuthSplitShell>
      <div className="space-y-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Choose a new password</h1>
          <p className="text-xs text-muted-foreground">Set a new password for your account.</p>
        </div>

        <Form {...form}>
          <form onSubmit={form.handleSubmit((values) => mutation.mutate(values))} className="space-y-4">
            <FormField
              control={form.control}
              name="new_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs">New password</FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      placeholder="••••••••"
                      autoComplete="new-password"
                      className="text-sm placeholder:text-base placeholder:font-bold placeholder:tracking-[0.2em] placeholder:text-foreground/40"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="confirm"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs">Confirm password</FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      placeholder="••••••••"
                      autoComplete="new-password"
                      className="text-sm placeholder:text-base placeholder:font-bold placeholder:tracking-[0.2em] placeholder:text-foreground/40"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <Button
              type="submit"
              size="lg"
              className="w-full shadow-lg shadow-brand-900/20 transition-shadow hover:shadow-xl hover:shadow-brand-900/25"
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Updating…" : "Update password"}
            </Button>
          </form>
        </Form>

        <p className="text-center text-xs text-muted-foreground">
          Remembered it?{" "}
          <Link to="/login" className="font-medium text-foreground hover:text-primary">
            Sign in
          </Link>
        </p>
      </div>
    </AuthSplitShell>
  );
}
