/** FE-Auth — `/signup`. A single centered split card (not the shared centered `AuthLayout`
 * column): the pitch sits on the left on a softly tinted panel, the form on the right on the
 * card surface — separated by a background shift, not a hairline. Company name + email +
 * password only — industry is chosen in onboarding step 1 (`IndustryStep` in
 * `OnboardingPage.tsx`), not here, so a brand-new tenant has no industry until the admin picks
 * one there (immutable afterward).
 *
 * Follows the app's normal light/dark theme (the `.dark` class on `<html>`) via the standard
 * semantic tokens — no pinned palette. Shares its pitch panel + theme switch with `/login`
 * via `AuthBrand.tsx`. */

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";

import { signup } from "../../lib/auth";
import { AuthSplitShell } from "./AuthBrand";

const signupSchema = z.object({
  company_name: z.string().min(1, "Company is required"),
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(8, "Use at least 8 characters"),
});

type SignupValues = z.infer<typeof signupSchema>;

export function SignupPage() {
  const [sentTo, setSentTo] = useState<string | null>(null);

  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      company_name: "",
      email: "",
      password: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: SignupValues) => signup(values),
    onSuccess: (_data, values) => setSentTo(values.email),
    onError: (err) =>
      toast.error("Couldn't create account", {
        description: err instanceof Error ? err.message : "Please try again.",
      }),
  });

  return (
    <AuthSplitShell>
      {sentTo ? (
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
              We sent a verification link to{" "}
              <span className="font-medium text-foreground">{sentTo}</span>. Click it to
              activate your account, then sign in below.
            </p>
          </div>
          <div className="space-y-3">
            <Button asChild size="lg" className="w-full shadow-lg shadow-brand-900/20">
              <Link to="/login">Back to sign in</Link>
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Didn&apos;t get it? Check your spam folder or try signing up again.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="space-y-1.5">
            <h1 className="text-xl font-semibold tracking-tight">Create Your Account</h1>
            <p className="text-xs text-muted-foreground">
              Set up your AI support agent to deliver fast, accurate customer support around
              the clock.
            </p>
          </div>

          <Form {...form}>
            <form
              onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
              className="space-y-4"
            >
              <FormField
                control={form.control}
                name="company_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs">Company</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="Soft Suave"
                        autoComplete="organization"
                        className="text-sm"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage className="text-xs" />
                    <FormDescription className="text-[11px]">
                      The organization your AI support agent represents in customer
                      conversations.
                    </FormDescription>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs">Work email</FormLabel>
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
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs">Password</FormLabel>
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
                {mutation.isPending ? "Creating…" : "Create Account"}
              </Button>
            </form>
          </Form>

          <p className="text-center text-xs text-muted-foreground">
            Already have an account?{" "}
            <Link to="/login" className="font-medium text-foreground hover:text-primary">
              Sign in
            </Link>
          </p>
        </div>
      )}
    </AuthSplitShell>
  );
}
