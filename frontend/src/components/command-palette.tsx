import { LogOut, Monitor, Moon, Search, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { NAV_GROUPS } from "@/app/nav";
import { useAuth } from "@/app/providers";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { hasPermission } from "@/lib/rbac";
import { useTheme } from "@/lib/useTheme";

/** ⌘K / Ctrl-K command palette: jump to any permitted page, switch theme, or log out. Renders
 * its own trigger (a search affordance) for the top bar. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { role, logout } = useAuth();
  const { setTheme } = useTheme();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-9 w-full max-w-64 items-center gap-2 rounded-lg border border-input bg-background px-3 text-sm text-muted-foreground transition-colors hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <Search className="size-4" />
        <span className="flex-1 text-left">Search…</span>
        <kbd className="pointer-events-none hidden rounded border bg-muted px-1.5 font-mono text-[10px] font-medium sm:inline">
          ⌘K
        </kbd>
      </button>

      <CommandDialog open={open} onOpenChange={setOpen} title="Command menu" description="Jump to a page or run an action">
        <CommandInput placeholder="Type a command or search…" />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          {NAV_GROUPS.map((group) => {
            const items = group.items.filter((i) => !i.permission || hasPermission(role, i.permission));
            if (items.length === 0) return null;
            return (
              <CommandGroup key={group.label} heading={group.label}>
                {items.map((item) => (
                  <CommandItem
                    key={item.to}
                    value={`${item.label} ${item.keywords ?? ""}`}
                    onSelect={() => run(() => navigate(item.to))}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            );
          })}
          <CommandSeparator />
          <CommandGroup heading="Theme">
            <CommandItem value="theme light" onSelect={() => run(() => setTheme("light"))}>
              <Sun /> Light
            </CommandItem>
            <CommandItem value="theme dark" onSelect={() => run(() => setTheme("dark"))}>
              <Moon /> Dark
            </CommandItem>
            <CommandItem value="theme system auto" onSelect={() => run(() => setTheme("system"))}>
              <Monitor /> System
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Account">
            <CommandItem value="log out sign out" onSelect={() => run(() => void logout())}>
              <LogOut /> Log out
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </>
  );
}
