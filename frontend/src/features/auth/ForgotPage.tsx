/** FE-Auth — `/forgot`. Requests a password-reset link. Always shows the same neutral
 * confirmation on submit (whether or not the email exists) so the form can't be used to
 * enumerate registered accounts. Same split-card shell as `/signup` and `/login`
 * (`AuthBrand.tsx`) rather than the plain `AuthLayout` card, so a user bouncing here from
 * Login's "Forgot password?" link doesn't land on a visually plainer page. */

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { api, unwrap } from "@/lib/api";

import { AuthSplitShell } from "./AuthBrand";

const forgotSchema = z.object({
  email: z.string().email("Enter a valid email address"),
});

type ForgotValues = z.infer<typeof forgotSchema>;

export function ForgotPage() {
  const [submitted, setSubmitted] = useState(false);

  const form = useForm<ForgotValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: "" },
  });

  const mutation = useMutation({
    mutationFn: async (values: ForgotValues) =>
      unwrap(await api.POST("/api/v1/auth/forgot-password", { body: { email: values.email } })),
    onSuccess: () => setSubmitted(true),
    // Fail neutrally too — never reveal whether the address is registered.
    onError: () => setSubmitted(true),
  });

  return (
    <AuthSplitShell>
      {submitted ? (
        <div className="space-y-6">
          <div className="relative grid size-14 place-items-center">
            <div aria-hidden className="absolute size-14 rounded-full bg-blue-500/25 blur-md" />
            <div className="relative grid size-14 place-items-center rounded-full border-2 border-blue-500/40 bg-background text-blue-600 dark:text-blue-400">
              <MailCheck className="size-6" />
            </div>
          </div>
          <div className="space-y-2">
            <h1 className="text-xl font-semibold tracking-tight">Check your email</h1>
            <p className="text-xs text-muted-foreground">
              If that address is registered, we sent a link to choose a new password.
            </p>
          </div>
          <Button asChild size="lg" variant="outline" className="w-full">
            <Link to="/login">Back to sign in</Link>
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="space-y-1.5">
            <h1 className="text-xl font-semibold tracking-tight">Reset your password</h1>
            <p className="text-xs text-muted-foreground">
              Enter your email and we&apos;ll send you a link to choose a new password.
            </p>
          </div>

          <Form {...form}>
            <form onSubmit={form.handleSubmit((values) => mutation.mutate(values))} className="space-y-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs">Email</FormLabel>
                    <FormControl>
                      <Input
                        type="email"
                        placeholder="you@company.com"
                        autoComplete="email"
                        className="text-sm"
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
                {mutation.isPending ? "Sending…" : "Send reset link"}
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
      )}
    </AuthSplitShell>
  );
}
