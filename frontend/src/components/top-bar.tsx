import { LogOut } from "lucide-react";
import { useLocation } from "react-router-dom";

import { NAV_GROUPS } from "@/app/nav";
import { useAuth } from "@/app/providers";
import { ThemeSwitch } from "@/components/theme-switch";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { usePageBanner } from "@/lib/pageBanner";

const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

function currentLabel(pathname: string): string {
  const match = ALL_ITEMS.find((i) => pathname === i.to || pathname.startsWith(i.to + "/"));
  return match?.label ?? "Console";
}

export function TopBar() {
  const { pathname } = useLocation();
  const { email, role, logout } = useAuth();
  const initials = (email || "?").slice(0, 2).toUpperCase();
  const banner = usePageBanner((s) => s.banner);

  return (
    <header className="sticky top-0 z-20 flex h-20 shrink-0 items-center gap-3 border-b bg-gradient-to-r from-background via-background to-ai-accent/5 px-6 backdrop-blur-md">
      {/* Mobile-only: the sidebar is an off-canvas drawer there and this is its one way in.
          On desktop the sidebar always stays open — no collapse/close control. */}
      <SidebarTrigger className="-ml-1 md:hidden" />
      {banner ? (
        <div className="flex min-w-0 items-center gap-3">
          {banner.icon && (
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
              <banner.icon className="size-5" />
            </span>
          )}
          <div className="min-w-0 leading-tight">
            <p className="font-display truncate text-base font-semibold">{banner.title}</p>
            <p className="truncate text-sm text-muted-foreground">{banner.subtitle}</p>
          </div>
        </div>
      ) : (
        <Breadcrumb className="hidden sm:block">
          <BreadcrumbList>
            <BreadcrumbItem className="text-muted-foreground">Console</BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{currentLabel(pathname)}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
      )}

      <div className="ml-auto flex items-center gap-2">
        <ThemeSwitch />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-lg" className="rounded-full" aria-label="Account">
              <Avatar className="size-9">
                <AvatarFallback className="bg-primary/10 text-xs font-medium text-primary">
                  {initials}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72 overflow-hidden p-0">
            <div className="flex items-center gap-3 bg-gradient-to-br from-secondary/70 to-secondary/20 px-4 py-4">
              <Avatar className="size-11 shrink-0 shadow-sm ring-2 ring-background">
                <AvatarFallback className="bg-primary text-sm font-semibold text-primary-foreground">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-muted-foreground">{email || "Signed in"}</p>
                <span className="mt-1 inline-flex items-center rounded-full border bg-card px-2 py-0.5 text-[11px] font-medium capitalize text-muted-foreground">
                  {role ?? "—"}
                </span>
              </div>
            </div>
            <DropdownMenuSeparator className="mx-3 my-0" />
            <div className="p-1.5">
              <DropdownMenuItem
                variant="destructive"
                className="cursor-pointer justify-center"
                onClick={() => void logout()}
              >
                <LogOut className="size-3.5" />
                <span className="text-xs">Log out</span>
              </DropdownMenuItem>
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
