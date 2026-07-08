/** "Add source" dialog: one entry point with three tabs (File / Paste text / URL), each posting
 * to its existing endpoint. On success it toasts, resets, invalidates the source list so the new
 * row appears and polling picks it up, then closes the dialog. */

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardPaste, FileText, Link2, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

import { createPasteSource, createUrlSource, uploadFileSource } from "./api";

const SOURCES_KEY = ["kb", "sources"] as const;

interface TabProps {
  onDone: () => void;
}

/** Paste-text tab — name + free-form content. */
function PasteTab({ onDone }: TabProps) {
  const qc = useQueryClient();
  const schema = z.object({
    name: z.string().trim().min(1, "Give this source a name."),
    content: z.string().trim().min(1, "Paste the text you want indexed."),
  });
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", content: "" },
  });
  const mut = useMutation({
    mutationFn: (v: z.infer<typeof schema>) => createPasteSource(v.name, v.content),
    onSuccess: () => {
      toast.success("Source added — indexing started.");
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
      form.reset();
      onDone();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit((v) => mut.mutate(v))} className="space-y-4">
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl>
                <Input placeholder="Return policy" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="content"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Text</FormLabel>
              <FormControl>
                <Textarea
                  rows={7}
                  placeholder="Paste the content the assistant should learn from…"
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <DialogFooter>
          <Button type="submit" disabled={mut.isPending}>
            {mut.isPending ? "Adding…" : "Add source"}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

/** URL tab — name + a URL to crawl. */
function UrlTab({ onDone }: TabProps) {
  const qc = useQueryClient();
  const schema = z.object({
    name: z.string().trim().min(1, "Give this source a name."),
    url: z.string().trim().url("Enter a valid URL, including https://"),
  });
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", url: "" },
  });
  const mut = useMutation({
    mutationFn: (v: z.infer<typeof schema>) => createUrlSource(v.name, v.url),
    onSuccess: () => {
      toast.success("URL queued for crawling.");
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
      form.reset();
      onDone();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit((v) => mut.mutate(v))} className="space-y-4">
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl>
                <Input placeholder="Help center" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="url"
          render={({ field }) => (
            <FormItem>
              <FormLabel>URL</FormLabel>
              <FormControl>
                <Input type="url" placeholder="https://example.com/help" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <DialogFooter>
          <Button type="submit" disabled={mut.isPending}>
            {mut.isPending ? "Crawling…" : "Add source"}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

/** File tab — a .txt/.md/.pdf/.docx upload with an optional display name. Native file inputs don't
 * bind cleanly to react-hook-form, so this tab keeps local state. */
function FileTab({ onDone }: TabProps) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const mut = useMutation({
    mutationFn: () => uploadFileSource(file as File, name.trim() || undefined),
    onSuccess: () => {
      toast.success("File uploaded — indexing started.");
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
      setFile(null);
      setName("");
      onDone();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (file) mut.mutate();
      }}
      className="space-y-4"
    >
      <div className="space-y-2">
        <Label htmlFor="kb-file">File</Label>
        <Input
          id="kb-file"
          type="file"
          accept=".txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <p className="text-xs text-muted-foreground">Accepts .txt, .md, .pdf, and .docx.</p>
      </div>
      <div className="space-y-2">
        <Label htmlFor="kb-file-name">
          Name <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <Input
          id="kb-file-name"
          placeholder="Defaults to the file name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <DialogFooter>
        <Button type="submit" disabled={!file || mut.isPending}>
          {mut.isPending ? "Uploading…" : "Upload file"}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Trigger button + dialog that gathers a new knowledge source through one of three tabs. Rendered
 * as the Knowledge page header action. */
export function UploadForm() {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus />
          Add source
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a knowledge source</DialogTitle>
          <DialogDescription>
            Upload a file, paste text, or crawl a URL. New sources are chunked and embedded
            automatically.
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="file">
          <TabsList className="w-full">
            <TabsTrigger value="file">
              <FileText />
              File
            </TabsTrigger>
            <TabsTrigger value="paste">
              <ClipboardPaste />
              Paste text
            </TabsTrigger>
            <TabsTrigger value="url">
              <Link2 />
              URL
            </TabsTrigger>
          </TabsList>
          <TabsContent value="file" className="pt-4">
            <FileTab onDone={close} />
          </TabsContent>
          <TabsContent value="paste" className="pt-4">
            <PasteTab onDone={close} />
          </TabsContent>
          <TabsContent value="url" className="pt-4">
            <UrlTab onDone={close} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
