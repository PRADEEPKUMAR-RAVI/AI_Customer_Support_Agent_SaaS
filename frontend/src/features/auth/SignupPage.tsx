/** FE-Auth — `/signup`. Workspace name + email + password + industry pick in one step: the
 * backend's `SignupRequest` already requires an industry (it provisions the record schema +
 * default agent_settings atomically), so there is no separate "pick an industry" screen for
 * the walking skeleton — this form *is* the Phase-1 "industry pick". */

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
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { signup, type Industry } from "../../lib/auth";

const INDUSTRIES: { value: Industry; label: string }[] = [
  { value: "retail", label: "Retail / E-commerce" },
  { value: "logistics", label: "Logistics / Courier" },
  { value: "telecom", label: "Telecom / ISP" },
  { value: "healthcare", label: "Healthcare / Clinic" },
  { value: "travel", label: "Travel / Hospitality" },
];

const signupSchema = z.object({
  workspace_name: z.string().min(1, "Workspace name is required"),
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(8, "Use at least 8 characters"),
  industry: z.enum(["retail", "logistics", "telecom", "healthcare", "travel"]),
});

type SignupValues = z.infer<typeof signupSchema>;

export function SignupPage() {
  const [sentTo, setSentTo] = useState<string | null>(null);

  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      workspace_name: "",
      email: "",
      password: "",
      industry: "retail",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: SignupValues) => signup(values),
    onSuccess: (_data, values) => setSentTo(values.email),
    onError: (err) =>
      toast.error("Couldn't create workspace", {
        description: err instanceof Error ? err.message : "Please try again.",
      }),
  });

  if (sentTo) {
    return (
      <Card>
        <CardHeader className="items-center text-center">
          <div className="mb-1 grid size-11 place-items-center rounded-full bg-primary/10 text-primary">
            <MailCheck className="size-6" />
          </div>
          <CardTitle className="text-xl">Check your email</CardTitle>
          <CardDescription>
            We sent a verification link to{" "}
            <span className="font-medium text-foreground">{sentTo}</span> to finish setting up
            your workspace.
          </CardDescription>
        </CardHeader>
        <CardFooter className="flex-col gap-3">
          <Button asChild variant="outline" className="w-full">
            <Link to="/login">Back to sign in</Link>
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Didn&apos;t get it? Check your spam folder or try signing up again.
          </p>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">Create your workspace</CardTitle>
        <CardDescription>Spin up an AI support console for your team.</CardDescription>
      </CardHeader>
      <Form {...form}>
        <form onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
          <CardContent className="grid gap-4">
            <FormField
              control={form.control}
              name="workspace_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Workspace name</FormLabel>
                  <FormControl>
                    <Input placeholder="Acme Support" autoComplete="organization" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="you@company.com"
                      autoComplete="email"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Password</FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      placeholder="At least 8 characters"
                      autoComplete="new-password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="industry"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Industry</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select your industry" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {INDUSTRIES.map((i) => (
                        <SelectItem key={i.value} value={i.value}>
                          {i.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
          <CardFooter className="mt-6 flex-col gap-3">
            <Button type="submit" className="w-full" disabled={mutation.isPending}>
              {mutation.isPending ? "Creating…" : "Create workspace"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link to="/login" className="font-medium text-primary hover:underline">
                Sign in
              </Link>
            </p>
          </CardFooter>
        </form>
      </Form>
    </Card>
  );
}
